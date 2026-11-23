"""C04: ciclo de las postulaciones y proyección de ocupación con PostgreSQL y HTTP."""
from uuid import uuid4


def exercise(client, origins, people, database, admission_proxy, callbacks, token, eventually):
    def request(method, path, person=0, expected=200, **kwargs):
        headers = {"Authorization": "Bearer " + people[person]["access_token"], **kwargs.pop("headers", {})}
        response = client.request(method, origins["gateway"] + path, headers=headers, **kwargs)
        allowed = expected if isinstance(expected, tuple) else (expected,)
        assert response.status_code in allowed, (method, path, expected, response.status_code, response.text[:300])
        return response.json()

    def snapshot(service, publication_id, payload=None, expected=200, authorized=True):
        url = origins[service] + f"/internal/publicaciones/{publication_id}/ocupacion"
        headers = {"X-Roomies-Service": token} if authorized else {}
        response = client.get(url, headers=headers) if payload is None else client.put(url, headers=headers, json=payload)
        assert response.status_code == expected, (url, expected, response.status_code, response.text[:300])
        return response.json()

    def publication(name, capacity):
        form = {
            "titulo": name, "descripcion": "Solo prueba de integración", "ubicacion": "Temuco", "precio": "250000",
            "tipo": "Arrendador", "categoria": "ofrezco", "tipo_vivienda": "habitacion", "mascota": "no",
            "cupos_totales": str(capacity), "id_region": "9", "id_comuna": "9101", "reglas": '["Sin ruido"]',
        }
        return request("POST", "/api/publicaciones", expected=201, data=form)["id_publicacion"], form

    def postulate(publication_id, person, expected=201):
        return request("POST", f"/api/publicaciones/{publication_id}/postulaciones", person, expected)

    def decide(application_id, state, expected=200, **data):
        return request("PATCH", f"/api/postulaciones/{application_id}/estado", expected=expected,
                       json={"estado": state, **data}, headers={"Idempotency-Key": str(uuid4())})

    def detail(application_id, person=0):
        return request("GET", f"/api/postulaciones/{application_id}", person)

    def accepted(application_id, person):
        def confirmed():
            row = detail(application_id, person)
            return row if row["estado"] == "Aceptada" else None
        return eventually(confirmed)["id_arriendo"]

    def feed(name, vacancies):
        return request("GET", "/api/publicaciones", params={"consulta": name, "cupos_disponibles": vacancies})["items"]

    def wait_for_occupancy(publication_id, expected):
        def projected():
            row = database.execute("SELECT ocupacion_confirmada FROM listado_applications.publicacion WHERE id_publicacion=%s", (publication_id,)).fetchone()
            return row[0] == expected
        eventually(projected)

    first, first_form = publication("C04 gestión activa", 2)
    other, other_form = publication("C04 finalización", 3)
    assert request("PUT", f"/api/publicaciones/{first}", data={**first_form, "reglas": '["Sin fiestas"]'})["reglas"] == ["Sin fiestas"]
    first_form["reglas"] = '["Sin fiestas"]'
    main = postulate(first, 1)["id_postulacion"]
    alternative = postulate(other, 1)["id_postulacion"]
    decide(main, "Preseleccionada")
    decide(alternative, "Preseleccionada")
    callbacks.set("unavailable")
    try:
        admission_proxy.set("hold")
        try:
            assert decide(main, "Aceptada", 202)["estado"] == "Preseleccionada"
            assert detail(alternative, 1)["estado"] == "Preseleccionada"
            request("PUT", f"/api/publicaciones/{first}", expected=409, data={**first_form, "reglas": '[]'})
        finally:
            admission_proxy.set("pass")
        arriendo = accepted(main, 1)
        active = request("GET", f"/api/publicaciones/{first}")
        assert active["estado"] == "Activa" and active["reglas_bloqueadas"]
    finally:
        callbacks.set("pass")
    assert detail(alternative, 1)["estado"] == "Cancelada"
    assert [event["estado"] for event in detail(main, 1)["historial"]] == ["Pendiente", "Preseleccionada", "Aceptada"]
    assert [row["id_publicacion"] for row in feed(first_form["titulo"], 1)] == [first]
    wait_for_occupancy(first, 1)

    edited = request("PUT", f"/api/publicaciones/{first}", data={**first_form, "cupos_totales": "3"})
    assert edited["reglas_bloqueadas"] and edited["cupos_disponibles"] == 2
    request("PUT", f"/api/publicaciones/{first}", expected=409, data={**first_form, "reglas": '[]'})
    second = postulate(first, 2)["id_postulacion"]
    decide(second, "Preseleccionada")
    decide(second, "Aceptada", (200, 202))
    assert accepted(second, 2) == arriendo
    wait_for_occupancy(first, 2)
    too_small = request("PUT", f"/api/publicaciones/{first}", expected=409, data={**first_form, "cupos_totales": "1"})
    assert "ocupación" in too_small["detail"]
    assert [row["id_publicacion"] for row in feed(first_form["titulo"], 1)] == [first]
    print("PASS C04 ingreso efectivo cancela otras solicitudes y mantiene historial, reglas y cupos reales", flush=True)

    pending = postulate(first, 3)["id_postulacion"]
    preselected = postulate(first, 4)["id_postulacion"]
    decide(preselected, "Preseleccionada")
    decide(preselected, "Cancelada", 422)
    request("PATCH", f"/api/publicaciones/{first}/cerrar", 4, 404)
    for _ in range(2):
        assert request("PATCH", f"/api/publicaciones/{first}/cerrar")["estado"] == "Cerrada"
    assert request("GET", f"/api/publicaciones/{first}")["cupos_disponibles"] == 0
    assert not feed(first_form["titulo"], 1)
    for application in (pending, preselected):
        assert detail(application)["estado"] == "Cancelada"
        assert sum(event["estado"] == "Cancelada" for event in detail(application)["historial"]) == 1
    assert request("GET", "/api/arriendos/mio", 1)["id_arriendo"] == arriendo
    assert detail(main, 1)["estado"] == "Aceptada"
    decide(preselected, "Aceptada", 409)
    postulate(first, 5, 409)
    print("PASS C04 cierre repetido conserva integrantes, cancela solo abiertas y deja el aviso consultable", flush=True)

    withdrawal = postulate(other, 5)["id_postulacion"]
    request("POST", f"/api/postulaciones/{withdrawal}/retiro", person=0, expected=403)
    assert request("POST", f"/api/postulaciones/{withdrawal}/retiro", 5)["estado"] == "Cancelada"
    assert detail(withdrawal, 5)["historial"][-1]["motivo"] == "Retiro voluntario"
    rejected = postulate(other, 5)["id_postulacion"]
    decide(rejected, "Rechazada", motivo="La solicitud no se ajusta al aviso")
    postulate(other, 5, 409)
    print("PASS C04 retiro voluntario conserva historial y rechazo impide volver a postular", flush=True)

    members = []
    for person in (3, 4):
        application_id = postulate(other, person)["id_postulacion"]
        decide(application_id, "Preseleccionada")
        decide(application_id, "Aceptada", (200, 202))
        accepted(application_id, person)
        members.append(application_id)
    awaiting_finalization = postulate(other, 6)["id_postulacion"]
    wait_for_occupancy(other, 2)
    source = snapshot("convivencia", other)
    assert source == {"ocupacion": 2, "version_ocupacion": 2, "finalizada": False}
    snapshot("convivencia", other, expected=403, authorized=False)
    snapshot("listado", other, source, expected=403, authorized=False)
    assert request("GET", "/internal/publicaciones/1/ocupacion", expected=404)

    # Simular solo el commit del productor de F03, en la BD temporal del ensayo.
    def remove_member(application, final):
        with database.transaction():
            database.execute("UPDATE convivencia_mensajeria.pertenencia SET estado='Inactiva' WHERE id_postulacion=%s", (application,))
            database.execute("""UPDATE convivencia_mensajeria.arriendo SET version_ocupacion=version_ocupacion+1,estado=%s
                              WHERE id_publicacion=%s""", ("Finalizado" if final else "Activo", other))

    remove_member(members[0], False)
    removed = snapshot("convivencia", other)
    assert removed == {"ocupacion": 1, "version_ocupacion": 3, "finalizada": False}
    snapshot("listado", other, {**removed, "id_usuario_expulsado": people[3]["business_id"]})
    snapshot("listado", other, {**removed, "id_usuario_expulsado": people[3]["business_id"]})
    assert database.execute("SELECT version_ocupacion FROM listado_applications.expulsion_publicacion WHERE id_publicacion=%s AND id_usuario=%s", (other, people[3]["business_id"])).fetchall() == [(3,)]
    snapshot("listado", other, source)
    snapshot("listado", other, {**removed, "ocupacion": 2}, expected=409)
    assert [row["id_publicacion"] for row in feed(other_form["titulo"], 2)] == [other]
    postulate(other, 3, 409)

    remove_member(members[1], True)
    assert snapshot("convivencia", other) == {"ocupacion": 0, "version_ocupacion": 4, "finalizada": True}
    eventually(lambda: request("GET", f"/api/publicaciones/{other}")["estado"] == "Cerrada")
    snapshot("listado", other, removed)
    assert request("GET", f"/api/publicaciones/{other}")["estado"] == "Cerrada"
    assert detail(awaiting_finalization, 6)["estado"] == "Cancelada"
    assert not feed(other_form["titulo"], 2)
    print("PASS C04 versiones duplicadas/atrasadas son inocuas y la reconciliación cierra tras la última salida", flush=True)
