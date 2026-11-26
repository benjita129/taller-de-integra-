"""C06: observar los commits de admisión y recuperar cortes HTTP en PostgreSQL."""
from uuid import uuid4

import httpx


def check_schema(database):
    indexes = dict(database.execute("""
        SELECT indexname, indexdef FROM pg_indexes
        WHERE schemaname IN ('listado_applications', 'convivencia_mensajeria')
    """).fetchall())
    assert "UNIQUE" in indexes["una_pertenencia_activa_por_usuario"]
    assert "Activa" in indexes["una_pertenencia_activa_por_usuario"]
    assert "UNIQUE" in indexes["arriendo_id_publicacion_key"]
    assert "UNIQUE" in indexes["admision_postulacion_vigente"]
    assert "Pendiente" in indexes["admision_recuperacion"]
    assert "Pendiente" in indexes["incorporaciones_pendientes"]
    assert "NOT enviado" in indexes["outbox_pendiente"]
    assert database.execute("""
        SELECT has_table_privilege('sql_listado_applications',
                   'convivencia_mensajeria.pertenencia', 'SELECT'),
               has_table_privilege('sql_convivencia_mensajeria',
                   'listado_applications.admision_operacion', 'UPDATE')
    """).fetchone() == (False, False)
    print("PASS C06 índices de unicidad y recuperación, roles sin acceso cruzado", flush=True)


def exercise(client, origins, people, database, admission, eligibility, reservations, callbacks, decision, internal_token, eventually):
    check_schema(database)
    postmaster_started = database.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
    owner, candidate = people
    gateway = origins["gateway"]

    def request(method, path, person=owner, *, status=200, origin=gateway, headers=None, **kwargs):
        response = client.request(method, origin + path, headers={
            "Authorization": "Bearer " + person["access_token"], **(headers or {}),
        }, **kwargs)
        assert response.status_code == status, (method, path, response.status_code, response.text[:200])
        return response.json()

    publication = request("POST", "/api/publicaciones", status=201, data={
        "titulo": "Arriendo sintético C06", "descripcion": "Verificación local",
        "ubicacion": "Temuco", "precio": "250000", "tipo": "Arrendador",
        "categoria": "ofrezco", "tipo_vivienda": "habitacion", "mascota": "no",
        "cupos_totales": "1", "id_region": "9", "id_comuna": "9101",
    })["id_publicacion"]
    application = request("POST", f"/api/publicaciones/{publication}/postulaciones", candidate, status=201)["id_postulacion"]
    path = f"/api/postulaciones/{application}/estado"
    request("PATCH", path, json={"estado": "Preseleccionada"})
    key = str(uuid4())
    headers = {"Idempotency-Key": key}

    def state():
        return database.execute("""
            SELECT a.estado, o.estado, i.estado, i.etapa, r.estado, m.estado,
                   x.enviado, p.ocupacion_confirmada, p.version_ocupacion
            FROM listado_applications.admision_operacion o
            JOIN listado_applications.postulacion a USING (id_postulacion)
            JOIN listado_applications.publicacion p ON p.id_publicacion = o.id_publicacion
            LEFT JOIN listado_applications.admision_reserva r USING (id_operacion)
            LEFT JOIN convivencia_mensajeria.incorporacion i USING (id_operacion)
            LEFT JOIN convivencia_mensajeria.pertenencia m USING (id_operacion)
            LEFT JOIN convivencia_mensajeria.outbox x
                ON x.id_operacion = o.id_operacion AND x.accion = 'Confirmar'
            WHERE o.id_operacion = %s
        """, (key,)).fetchone()

    def checkpoint(label, expected):
        try:
            eventually(lambda: state() == expected)
        except AssertionError as error:
            raise AssertionError(f"{label}. Estado esperado {expected}, observado {state()}.") from error
        application_state, operation, incorporation, step, reservation, membership, sent, occupied, version = expected
        print(f"PASS C06 {label} | postulación={application_state} operación={operation} "
              f"incorporación={incorporation}/{step} reserva={reservation} pertenencia={membership} "
              f"outbox_enviada={sent} ocupación_listado={occupied} versión={version}", flush=True)

    admission.set("cut")
    queued = request("PATCH", path, status=202, headers=headers, json={"estado": "Aceptada"})
    assert queued["operacion"] == {"id_operacion": key, "estado": "Pendiente"}
    checkpoint("corte TCP después de persistir intención en Listado", (
        "Preseleccionada", "Pendiente", None, None, None, None, None, 0, 0,
    ))
    request("GET", "/api/arriendos/mio", candidate, status=404)

    eligibility.set("cut")
    admission.set("pass")
    checkpoint("corte TCP a Identidad después de persistir la incorporación", (
        "Preseleccionada", "Pendiente", "Pendiente", "ValidarIdentidad", None, None, None, 0, 0,
    ))

    reservations.set("drop")
    admission.set("drop")
    eligibility.set("pass")
    eventually(lambda: key in reservations.dropped_keys)
    checkpoint("respuesta perdida tras reservar en Listado", (
        "Preseleccionada", "Pendiente", "Pendiente", "Reservar", "Reservada", None, None, 0, 0,
    ))
    assert request("GET", f"/api/publicaciones/{publication}")["cupos_disponibles"] == 0

    callbacks.set("cut")
    reservations.set("pass")
    eventually(lambda: key in admission.dropped_keys)
    checkpoint("respuesta perdida tras confirmar pertenencia y outbox en Convivencia", (
        "Preseleccionada", "Pendiente", "Terminada", "Reservar", "Reservada", "Activa", False, 0, 0,
    ))
    rental = request("GET", "/api/arriendos/mio", candidate)
    assert rental["id_publicacion"] == publication
    source = request("GET", f"/internal/publicaciones/{publication}/ocupacion", origin=origins["convivencia"],
                     headers={"X-Roomies-Service": internal_token})
    assert source == {"ocupacion": 1, "version_ocupacion": 1, "finalizada": False}

    callbacks.set("drop")
    eventually(lambda: key in callbacks.dropped_keys)
    checkpoint("Listado confirma reserva y ocupación, Convivencia pierde la respuesta", (
        "Preseleccionada", "Pendiente", "Terminada", "Reservar", "Confirmada", "Activa", False, 1, 1,
    ))

    admission.set("pass")
    checkpoint("Listado finaliza la aceptación al reanudar HTTP", (
        "Aceptada", "Confirmada", "Terminada", "Reservar", "Confirmada", "Activa", False, 1, 1,
    ))
    decision.set("drop")
    try:
        request("PATCH", path, origin=decision.origin, headers=headers, json={"estado": "Aceptada"})
    except httpx.RemoteProtocolError:
        assert key in decision.dropped_keys
    else:
        raise AssertionError("El cliente debía perder la respuesta de la aceptación confirmada.")

    callbacks.set("pass")
    decision.set("pass")
    checkpoint("reintentos con la misma clave convergen sin reiniciar la BD", (
        "Aceptada", "Confirmada", "Terminada", "Reservar", "Confirmada", "Activa", True, 1, 1,
    ))
    assert request("PATCH", path, origin=decision.origin, headers=headers, json={"estado": "Aceptada"})["id_arriendo"] == rental["id_arriendo"]
    assert request("PATCH", path, status=409, headers=headers, json={"estado": "Aceptada", "motivo": "Otro contenido"})["code"] == "IDEMPOTENCY_CONFLICT"
    detail = request("GET", f"/api/postulaciones/{application}", candidate)
    assert [row["estado"] for row in detail["historial"]] == ["Pendiente", "Preseleccionada", "Aceptada"]
    assert database.execute("SELECT pg_postmaster_start_time()").fetchone()[0] == postmaster_started
    assert database.execute("SELECT count(*) FROM convivencia_mensajeria.pertenencia WHERE id_operacion=%s", (key,)).fetchone() == (1,)
    assert database.execute("""
        SELECT NOT EXISTS (
            SELECT 1 FROM listado_applications.publicacion
            WHERE ocupacion_confirmada < 0 OR ocupacion_confirmada > cupos_totales
        )
    """).fetchone() == (True,)
    print("PASS C06 respuesta final perdida, una pertenencia, una aceptación y ocupación válida", flush=True)
