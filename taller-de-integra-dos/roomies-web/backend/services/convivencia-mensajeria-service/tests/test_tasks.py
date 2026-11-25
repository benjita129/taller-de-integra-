from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.main import create_app
from backend.service_runtime.contracts import Actor
from backend.service_runtime.security import actor


@pytest.fixture
def rentals(empty_database, service):
    def admit(user, publication):
        status, body, _ = service.incorporate(uuid4(), {
            "id_usuario": user, "id_publicacion": publication,
            "id_postulacion": user + 10, "version_capacidad": 1,
        })
        assert status == 201, body
        return body["id_arriendo"]

    shared = admit(2, 7)
    assert admit(3, 7) == shared
    return shared, admit(4, 8)


@pytest.fixture
def client_for(monkeypatch):
    monkeypatch.setenv("CONVIVENCIA_CURSOR_SECRET", "isolated-test-cursor-key-000000000000")

    def client(user=None, *, administrator=False, instance=None):
        application = create_app(instance, run_recovery=False)
        if user is not None:
            application.dependency_overrides[actor] = lambda: Actor(UUID(int=user), user, True, administrator)
        return TestClient(application, raise_server_exceptions=False)

    return client


def create_task(client, path, **data):
    response = client.post(path, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def withdraw(connection, rental, user=3):
    connection.execute("""UPDATE convivencia_mensajeria.pertenencia SET estado='Inactiva'
        WHERE id_arriendo=%s AND id_usuario=%s""", (rental, user))


def test_permisos_y_persistencia_entre_clientes(rentals, client_for):
    rental, other = rentals
    path = f"/api/arriendos/{rental}/tareas"
    with (
        client_for(2) as creator,
        client_for(3) as assignee,
        client_for(4) as outsider,
        client_for(99, administrator=True) as administrator,
        client_for() as anonymous,
    ):
        assert anonymous.get(path).status_code == 401
        assert creator.post(path, json={"titulo": "  "}).status_code == 422
        assert creator.post(path, json={"titulo": "Comprar", "id_asignado": 4}).status_code == 422
        task = create_task(creator, path, titulo="  Comprar jabón  ", descripcion="Para la cocina", id_asignado=3)
        assert task == {"id_tarea": task["id_tarea"], "id_arriendo": rental, "titulo": "Comprar jabón",
                        "descripcion": "Para la cocina", "id_asignado": 3, "estado": "Pendiente",
                        "id_creador": 2, "creada_en": task["creada_en"]}
        assert task["id_tarea"] > 0
        assert datetime.fromisoformat(task["creada_en"]).tzinfo is not None
        task_path = f"/api/tareas/{task['id_tarea']}"
        for client in (outsider, administrator):
            assert client.get(path, params={"cursor": "inválido"}).status_code == 403
            assert client.post(path, json={"titulo": "Comprar"}).status_code == 403
            assert client.patch(task_path, json={"id_asignado": 3}).status_code == 403
            assert client.patch(f"{task_path}/estado", json={"estado": "Completada"}).status_code == 403
        assert outsider.get(f"/api/arriendos/{other}/tareas").json() == {"items": [], "siguiente_cursor": None}
        assert creator.patch(f"{task_path}/estado", json={"estado": "Completada"}).status_code == 403
        assert assignee.patch(f"{task_path}/estado", json={"estado": "Pendiente"}).status_code == 422
        assert creator.patch(task_path, json={"id_asignado": 3, "titulo": "Cambio"}).status_code == 422
        assert creator.patch(task_path, json={"id_asignado": True}).status_code == 422
        assert assignee.get(path).json()["items"] == [task]
        result = assignee.patch(f"{task_path}/estado", json={"estado": "Completada"})
        assert result.status_code == 200, result.text
        assert result.json() == {**task, "estado": "Completada"}
        assert creator.get(path).json()["items"] == [result.json()]
        assert creator.patch(task_path, json={"id_asignado": 2}).status_code == 409


def test_cursor_por_filtro_actor_y_arriendo(rentals, client_for, migrated_database):
    rental, other = rentals
    path = f"/api/arriendos/{rental}/tareas"
    params = {"estado": "Pendiente", "id_asignado": 3, "limite": 1}
    with client_for(2) as creator, client_for(3) as member, client_for(4) as outsider:
        created = [create_task(creator, path, titulo=f"Limpiar {number}", id_asignado=3)
                   for number in range(3)]
        unassigned = create_task(creator, path, titulo="Ordenar")
        assert unassigned["id_asignado"] is None and unassigned["descripcion"] is None
        with psycopg.connect(migrated_database) as connection:
            connection.execute("UPDATE convivencia_mensajeria.tarea SET creada_en='2026-11-23T00:00:00Z'")

        first = creator.get(path, params=params)
        assert first.status_code == 200, first.text
        page = first.json()
        first_cursor = page["siguiente_cursor"]
        assert first_cursor
        assert member.get(path, params={**params, "cursor": first_cursor}).status_code == 422
        assert outsider.get(f"/api/arriendos/{other}/tareas", params={**params, "cursor": first_cursor}).status_code == 422
        assert creator.get(path, params={**params, "estado": "Completada", "cursor": first_cursor}).status_code == 422
        assert creator.get(path, params={**params, "id_asignado": 2, "cursor": first_cursor}).status_code == 422
        assert creator.get(path, params={**params, "cursor": "inválido"}).status_code == 422
        ids = [page["items"][0]["id_tarea"]]
        for _ in range(2):
            assert page["siguiente_cursor"]
            response = creator.get(path, params={**params, "cursor": page["siguiente_cursor"]})
            assert response.status_code == 200, response.text
            page = response.json()
            assert len(page["items"]) == 1
            ids.append(page["items"][0]["id_tarea"])
        assert page["siguiente_cursor"] is None
        assert ids == [task["id_tarea"] for task in reversed(created)]


def test_retiro_desasigna_pendientes_y_conserva_completadas(rentals, client_for, migrated_database):
    rental, _ = rentals
    path = f"/api/arriendos/{rental}/tareas"
    with client_for(2) as member, client_for(3) as assignee:
        done = create_task(member, path, titulo="Pagar cuenta", id_asignado=3)
        pending = create_task(member, path, titulo="Lavar platos", id_asignado=3)
        done_path = f"/api/tareas/{done['id_tarea']}/estado"
        pending_path = f"/api/tareas/{pending['id_tarea']}"
        assert assignee.patch(done_path, json={"estado": "Completada"}).status_code == 200
        with psycopg.connect(migrated_database) as connection:
            withdraw(connection, rental)

        assert assignee.get(path).status_code == 403
        assert assignee.patch(f"{pending_path}/estado", json={"estado": "Completada"}).status_code == 403
        assert member.patch(f"{pending_path}/estado", json={"estado": "Completada"}).status_code == 403
        assert member.patch(pending_path, json={"id_asignado": 3}).status_code == 422
        assert member.get(path, params={"estado": "Pendiente"}).json()["items"] == [{**pending, "id_asignado": None}]
        assert member.get(path, params={"estado": "Completada"}).json()["items"] == [{**done, "estado": "Completada"}]
        reassigned = member.patch(pending_path, json={"id_asignado": 2})
        assert reassigned.status_code == 200, reassigned.text
        assert reassigned.json() == {**pending, "id_asignado": 2}
        assert member.patch(f"{pending_path}/estado", json={"estado": "Completada"}).status_code == 200


def wait_until_blocked(admin_dsn, blocking_pid):
    deadline = monotonic() + 5
    with psycopg.connect(admin_dsn, autocommit=True) as observer:
        while monotonic() < deadline:
            if observer.execute("SELECT 1 FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                                (blocking_pid,)).fetchone():
                return
            sleep(0.02)
    pytest.fail("La segunda transacción no esperó el bloqueo de la primera.")


@pytest.mark.parametrize("withdrawal_first", [True, False])
def test_retiro_y_completar_se_serializan(rentals, client_for, service, migrated_database, monkeypatch, withdrawal_first):
    rental, _ = rentals
    path = f"/api/arriendos/{rental}/tareas"
    with client_for(2) as member, client_for(3, instance=service) as assignee, ThreadPoolExecutor(2) as pool:
        task = create_task(member, path, titulo="Limpiar", id_asignado=3)

        def complete():
            return assignee.patch(f"/api/tareas/{task['id_tarea']}/estado", json={"estado": "Completada"})

        def remove_member():
            with psycopg.connect(migrated_database) as connection:
                withdraw(connection, rental)

        if withdrawal_first:
            with psycopg.connect(migrated_database) as connection:
                withdraw(connection, rental)
                completion = pool.submit(complete)
                wait_until_blocked(migrated_database, connection.info.backend_pid)
            assert completion.result(timeout=10).status_code == 403
            expected = {**task, "id_asignado": None}
        else:
            original_transaction = service.repository.transaction
            lock_holder = Queue()
            release = Event()

            @contextmanager
            def transaction():
                with original_transaction() as connection:
                    yield connection
                    lock_holder.put(connection.info.backend_pid)
                    assert release.wait(timeout=10), "No se liberó la transacción de completado."

            monkeypatch.setattr(service.repository, "transaction", transaction)
            completion = pool.submit(complete)
            try:
                blocking_pid = lock_holder.get(timeout=5)
                withdrawal = pool.submit(remove_member)
                wait_until_blocked(migrated_database, blocking_pid)
            finally:
                release.set()
            assert completion.result(timeout=10).status_code == 200
            withdrawal.result(timeout=10)
            expected = {**task, "estado": "Completada"}

        assert member.get(path).json()["items"] == [expected]
