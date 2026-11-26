"""C06: permisos, concurrencia y persistencia de convivencia vía Gateway y PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4


def exercise(client, origins, people, database, eventually, *, callbacks=None):
    owner, resident, assignee, outsider = range(4)
    assignee_id = people[assignee]["business_id"]
    pending_checks = []

    def request(method, path, person, expected=200, **kwargs):
        headers = {"Authorization": "Bearer " + people[person]["access_token"], **kwargs.pop("headers", {})}
        response = client.request(method, origins["gateway"] + path, headers=headers, **kwargs)
        statuses = expected if isinstance(expected, tuple) else (expected,)
        assert response.status_code in statuses, (method, path, expected, response.status_code, response.text[:300])
        return response

    schema = client.get(origins["convivencia"] + "/openapi.json")
    schema.raise_for_status()
    api = schema.json()
    chat_available = "/api/conversaciones" in api["paths"]
    expulsion_api = next((methods["post"] for route, methods in api["paths"].items()
                          if route.startswith("/api/arriendos/{") and route.endswith("}/expulsiones")
                          and "post" in methods), None)

    publication = request("POST", "/api/publicaciones", owner, 201, data={
        "titulo": "C06 convivencia y pertenencia", "descripcion": "Prueba local con datos sintéticos",
        "ubicacion": "Temuco", "precio": "250000", "tipo": "Arrendador", "categoria": "ofrezco",
        "tipo_vivienda": "habitacion", "mascota": "no", "cupos_totales": "2",
        "id_region": "9", "id_comuna": "9101",
    }).json()["id_publicacion"]

    def admit(person):
        application = request("POST", f"/api/publicaciones/{publication}/postulaciones", person, 201).json()
        path = f"/api/postulaciones/{application['id_postulacion']}"
        request("PATCH", path + "/estado", owner, json={"estado": "Preseleccionada"})
        request("PATCH", path + "/estado", owner, (200, 202),
                json={"estado": "Aceptada"}, headers={"Idempotency-Key": str(uuid4())})

        def confirmed():
            row = request("GET", path, person).json()
            return row["id_arriendo"] if row["estado"] == "Aceptada" else None

        return eventually(confirmed)

    def projected(occupancy, *, closed=False):
        row = database.execute("""SELECT ocupacion_confirmada, estado FROM listado_applications.publicacion
            WHERE id_publicacion=%s""", (publication,)).fetchone()
        return row == (occupancy, "Cerrada" if closed else "Activa")

    rental = admit(resident)
    message_path = None
    if chat_available:
        conversations = request("GET", "/api/conversaciones", resident).json()["items"]
        assert len(conversations) == 1 and conversations[0]["id_arriendo"] == rental
        conversation = conversations[0]
        message_path = f"/api/conversaciones/{conversation['id_conversacion']}/mensajes"
        request("POST", message_path, resident, (200, 201),
                json={"contenido": "Mensaje anterior al ingreso", "id_cliente": str(uuid4())})
    else:
        pending_checks.append("F02: chat, exclusión del historial previo y revocación de lectura y envío por API.")

    assert admit(assignee) == rental
    eventually(lambda: projected(2))
    tasks_path = f"/api/arriendos/{rental}/tareas"
    request("POST", tasks_path, resident, (403, 422),
            json={"titulo": "Asignación inválida", "id_asignado": people[outsider]["business_id"]})
    for nonmember in (owner, outsider):
        request("GET", tasks_path, nonmember, 403)
        request("POST", tasks_path, nonmember, 403, json={"titulo": "El actor no es integrante"})

    def task(title):
        return request("POST", tasks_path, resident, 201, json={"titulo": title, "id_asignado": assignee_id}).json()

    def complete(row, actor=assignee, expected=200):
        return request("PATCH", f"/api/tareas/{row['id_tarea']}/estado", actor, expected, json={"estado": "Completada"})

    done, pending, contended = task("Conservar historial"), task("Reasignar tras el retiro"), task("Completar en paralelo")
    complete(done, resident, 403)
    done = complete(done).json()
    filters = {"estado": "Pendiente", "id_asignado": assignee_id, "limite": 1}
    first_page = request("GET", tasks_path, resident, params=filters).json()
    assert first_page["items"] == [contended] and first_page["siguiente_cursor"]
    next_page = request("GET", tasks_path, resident, params={**filters, "cursor": first_page["siguiente_cursor"]}).json()
    assert next_page == {"items": [pending], "siguiente_cursor": None}

    if message_path:
        assert request("GET", message_path, assignee).json()["items"] == []
        message = {"contenido": "Mensaje posterior al ingreso", "id_cliente": str(uuid4())}
        for nonmember in (owner, outsider):
            request("GET", message_path, nonmember, 403)
            request("POST", message_path, nonmember, 403, json=message)
        barrier = Barrier(2, timeout=10)

        def send_same_message():
            barrier.wait()
            return request("POST", message_path, assignee, (200, 201), json=message).json()["id_mensaje"]

        with ThreadPoolExecutor(2) as pool:
            sends = [pool.submit(send_same_message) for _ in range(2)]
            message_ids = [result.result(timeout=20) for result in sends]
        assert len(set(message_ids)) == 1
        messages = request("GET", message_path, assignee).json()["items"]
        assert [row["id_mensaje"] for row in messages] == message_ids[:1]
        print("PASS C06 chat: permiso por pertenencia, historial desde el ingreso y reintentos paralelos sin duplicados", flush=True)

    if expulsion_api:
        expulsion_path = f"/api/arriendos/{rental}/expulsiones"
        body_schema = expulsion_api["requestBody"]["content"]["application/json"]["schema"]
        if "$ref" in body_schema:
            body_schema = api["components"]["schemas"][body_schema["$ref"].rsplit("/", 1)[1]]
        confirmation = "confirmar" if "confirmar" in body_schema["properties"] else "confirmo"
        removal_key = str(uuid4())

        def expel(person, actor=owner, expected=(200, 201), key=removal_key):
            return request("POST", expulsion_path, actor, expected, headers={"Idempotency-Key": key},
                           json={"id_usuario": people[person]["business_id"], "motivo": "Prueba C06", confirmation: True})

        for nonowner in (resident, outsider):
            expel(assignee, nonowner, 403, key=str(uuid4()))

        def attempted_projection(delivered):
            return database.execute("""SELECT count(*) FROM convivencia_mensajeria.retiro_outbox
                WHERE enviado=%s AND ultimo_intento IS NOT NULL AND payload->>'id_publicacion'=%s""",
                (delivered, str(publication))).fetchone() == (1,)

        barrier = Barrier(4 if message_path else 2, timeout=10)

        def race(operation):
            barrier.wait()
            return operation()

        if callbacks is not None:
            callbacks.set("cut")
        try:
            with ThreadPoolExecutor(barrier.parties) as pool:
                completion = pool.submit(race, lambda: complete(contended, expected=(200, 403)))
                removal = pool.submit(race, lambda: expel(assignee))
                if message_path:
                    racing_message = {"contenido": "Envío en paralelo al retiro", "id_cliente": str(uuid4())}
                    chat_read = pool.submit(race, lambda: request("GET", message_path, assignee, (200, 403)))
                    chat_send = pool.submit(race, lambda: request("POST", message_path, assignee, (200, 201, 403), json=racing_message))
                    read = chat_read.result(timeout=20)
                    send = chat_send.result(timeout=20)
                    if read.status_code == 200:
                        assert {row["id_mensaje"] for row in read.json()["items"]}.issuperset(message_ids)
                completion_won = completion.result(timeout=20).status_code == 200
                removal.result(timeout=20)
            request("GET", "/api/arriendos/mio", assignee, 404)
            if message_path:
                request("GET", message_path, assignee, 403)
                request("POST", message_path, assignee, 403, json=message)
                contents = [row["contenido"] for row in request("GET", message_path, resident).json()["items"]]
                assert contents.count(racing_message["contenido"]) == (0 if send.status_code == 403 else 1)
            if callbacks is not None:
                eventually(lambda: attempted_projection(False), 10)
        finally:
            if callbacks is not None:
                callbacks.set("pass")
        eventually(lambda: projected(1))
        expel(assignee, expected=(200, 201))
        if callbacks is not None:
            eventually(lambda: attempted_projection(True))
        audit_table = "retiro" if database.execute("SELECT to_regclass('convivencia_mensajeria.retiro') IS NOT NULL").fetchone()[0] else "expulsion"
        audit = database.execute(f"""SELECT id_actor, motivo FROM convivencia_mensajeria.{audit_table}
            WHERE id_arriendo=%s AND id_usuario=%s""", (rental, assignee_id)).fetchall()
        assert audit == [(people[owner]["business_id"], "Prueba C06")]
        if callbacks is None:
            pending_checks.append("F03: recuperación de su evento con el enlace de red interrumpido.")
    else:
        pending_checks.append("F03: retiro HTTP exclusivo del dueño, auditoría, reintento, recuperación del evento y retiro del último integrante.")
        with ThreadPoolExecutor(2) as pool:
            with database.transaction():
                # Simula el commit de F03 que activa el desasignado de C05 en el PostgreSQL temporal.
                removed = database.execute("""UPDATE convivencia_mensajeria.pertenencia SET estado='Inactiva'
                    WHERE id_arriendo=%s AND id_usuario=%s AND estado='Activa'""", (rental, assignee_id))
                assert removed.rowcount == 1
                database.execute("""UPDATE convivencia_mensajeria.arriendo SET version_ocupacion=version_ocupacion+1
                    WHERE id_arriendo=%s""", (rental,))
                completion = pool.submit(complete, contended, assignee, 403)
                read = pool.submit(request, "GET", tasks_path, assignee, 403)

                def waiting_for_withdrawal():
                    assert not completion.done() and not read.done(), "Una petición terminó antes del commit del retiro."
                    database.execute("SELECT pg_stat_clear_snapshot()")
                    # También cuenta una petición en cola detrás de la otra.
                    return database.execute("""WITH RECURSIVE blocked(pid) AS (
                        SELECT pg_backend_pid()
                        UNION
                        SELECT activity.pid FROM pg_stat_activity activity JOIN blocked
                        ON blocked.pid = ANY(pg_blocking_pids(activity.pid))
                    ) SELECT count(*) FROM blocked""").fetchone()[0] >= 3

                eventually(waiting_for_withdrawal, 10)
            completion.result(timeout=10)
            read.result(timeout=10)
        completion_won = False
        eventually(lambda: projected(1))
        print("PASS C06 retiro simulado por SQL: PostgreSQL bloqueó lectura y completado hasta el commit", flush=True)

    request("GET", "/api/arriendos/mio", assignee, 404)
    request("GET", tasks_path, assignee, 403)
    assert database.execute("""SELECT count(*) FILTER (WHERE estado='Activa'), count(*) FILTER (WHERE estado='Inactiva')
        FROM convivencia_mensajeria.pertenencia WHERE id_arriendo=%s""", (rental,)).fetchone() == (1, 1)
    assert database.execute("SELECT version_ocupacion FROM convivencia_mensajeria.arriendo WHERE id_arriendo=%s",
                            (rental,)).fetchone() == (3,)
    current_tasks = {row["id_tarea"]: row for row in request("GET", tasks_path, resident).json()["items"]}
    assert current_tasks[done["id_tarea"]] == done
    assert current_tasks[pending["id_tarea"]] == {**pending, "id_asignado": None}
    expected_contended = {**contended, "estado": "Completada"} if completion_won else {**contended, "id_asignado": None}
    assert current_tasks[contended["id_tarea"]] == expected_contended
    pending_path = f"/api/tareas/{pending['id_tarea']}"
    request("PATCH", pending_path, resident, (403, 422), json={"id_asignado": assignee_id})
    request("PATCH", pending_path, resident, json={"id_asignado": people[resident]["business_id"]})
    assert complete(pending, resident).json()["estado"] == "Completada"
    print("PASS C06 tareas: permisos, paginación, historial, desasignación y reasignación por HTTP", flush=True)

    if expulsion_api:
        expel(resident, key=str(uuid4()))
        request("GET", "/api/arriendos/mio", resident, 404)
        request("GET", tasks_path, resident, 403)
        eventually(lambda: projected(0, closed=True))
        print("PASS C06 retiro por API: auditoría única, revocación de permisos, liberación de plaza y cierre final", flush=True)

    if message_path and not expulsion_api:
        request("GET", message_path, assignee, 403)
        request("POST", message_path, assignee, 403, json=message)
        pending_checks.append("F02/F03: revocación de chat con retiro ejecutado por API.")
    return pending_checks
