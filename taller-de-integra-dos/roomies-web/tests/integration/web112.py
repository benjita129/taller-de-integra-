"""Next/BFF reales sobre los servicios y SQL efímeros de run_c03; sin dotenv."""
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import httpx


def exercise(root, clean, identity, gateway, database, people, port, *, manual=False):
    project = root / "frontend-next"
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Falta Node en PATH para iniciar Next.js.")
    next_cli = project / "node_modules/next/dist/bin/next"
    if not next_cli.is_file():
        raise RuntimeError("Faltan las dependencias de Next.js. Ejecuta npm ci en frontend-next.")
    isolated = Path(tempfile.mkdtemp(prefix=".proxy-test-112-", dir=project))
    linked = False
    process = None
    try:
        for name in ("next.config.ts", "package.json", "tsconfig.json", "src", "public"):
            source = project / name
            if source.is_dir(): shutil.copytree(source, isolated / name)
            else: shutil.copy2(source, isolated / name)
        subprocess.run([node, "-e", "require('fs').symlinkSync(process.argv[1],process.argv[2],process.platform==='win32'?'junction':'dir')", str(project / "node_modules"), str(isolated / "node_modules")], check=True)
        linked = True
        base = f"http://127.0.0.1:{port}"
        env = {**clean, "NODE_ENV":"development", "NEXT_TELEMETRY_DISABLED":"1", "ROOMIES_LOCAL_MODE":"1",
               "ROOMIES_RUNTIME_MODE":"disposable", "WEB_AUTH_ENABLED":"true", "WEB_AUTH_PROVIDER":"supabase",
               "WEB_AUTH_ORIGIN":base, "WEB_AUTH_FASTAPI_ORIGIN":gateway, "FASTAPI_ORIGIN":gateway,
               "WEB_SUPABASE_ORIGIN":identity.origin, "WEB_SUPABASE_PUBLISHABLE_KEY":identity.publishable_key}
        log_path = isolated / "next.log"
        with log_path.open("wb") as log, ExitStack() as clients:
            command = [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", str(port)]
            if manual:
                command.append("--webpack")
            process = subprocess.Popen(command, cwd=isolated, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            sessions = [clients.enter_context(httpx.Client(
                base_url=base, timeout=30, trust_env=False, headers={"Origin": base, "X-Haycupo-CSRF": "1"},
            )) for _ in range(2 if manual else 3)]
            owner, applicant = sessions[:2]
            deadline = time.monotonic() + 90
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    if owner.get("/", timeout=5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.3)
            else:
                raise RuntimeError("Next.js no quedó disponible.\n" + log_path.read_text(encoding="utf-8", errors="replace")[-2500:])

            def request(client,method,path,expected=(200,),**kwargs):
                response=client.request(method,path,**kwargs)
                assert response.status_code in expected,(method,path,response.status_code)
                return response

            accounts = [f"c03-{index}@example.com" for index in (range(2) if manual else range(11, 14))]
            password = "Synthetic-password-123"
            for client, email in zip(sessions, accounts):
                request(client,"POST","/web-api/auth/login",json={"correo":email,"contrasena":password})
                assert request(client,"GET","/web-api/auth/sesion").json()["authenticated"] is True
            title = "Habitación de prueba en Temuco" if manual else "Arriendo D02 integrado"
            form={"titulo":title,"descripcion":"Prueba local con SQL efímero","ubicacion":"Temuco","precio":"150000","cupos_totales":"1","tipo":"Arrendador","categoria":"ofrezco","tipo_vivienda":"habitacion","mascota":"no","id_region":"9","id_comuna":"9101"}
            publication=request(owner,"POST","/web-api/publicaciones",(201,),files=[(k,(None,v)) for k,v in form.items()],headers={"Idempotency-Key":str(uuid4())}).json()["id_publicacion"]
            if manual:
                print(f"MANUAL_URL={base}/", flush=True)
                print(f"Aviso de prueba: {base}/publicaciones/{publication}", flush=True)
                print(f"Arrendador: {accounts[0]} | Postulante: {accounts[1]}", flush=True)
                print(f"Contraseña ficticia para ambas cuentas: {password}", flush=True)
                print("Para detener el entorno, escribe salir o presiona Ctrl+C.", flush=True)
                try:
                    for command in sys.stdin:
                        if command.strip().lower() == "salir":
                            break
                except KeyboardInterrupt:
                    pass
                return
            stranger = sessions[2]
            withdrawn=request(applicant,"POST","/web-api/postulaciones",(201,),json={"publicacion":publication}).json()["id_postulacion"]
            for _ in range(2):
                cancelled=request(applicant,"POST","/web-api/postulaciones",json={"retiro":withdrawn}).json()
                assert cancelled["estado"]=="Cancelada"
            application=request(applicant,"POST","/web-api/postulaciones",(201,),json={"publicacion":publication}).json()["id_postulacion"]
            rows=request(owner,"GET",f"/web-api/postulaciones?publicacion={publication}").json()
            assert rows["items"][0]["id_postulacion"]==application and rows["siguiente_cursor"] is None
            request(stranger,"PATCH","/web-api/postulaciones",(403,),json={"id":application,"estado":"Preseleccionada"})
            other=request(stranger,"POST","/web-api/postulaciones",(201,),json={"publicacion":publication}).json()["id_postulacion"]
            rejected=request(owner,"PATCH","/web-api/postulaciones",json={"id":other,"estado":"Rechazada","motivo":"Otra alternativa"}).json()
            assert rejected["estado"]=="Rechazada" and rejected["motivo"]=="Otra alternativa"
            request(owner,"PATCH","/web-api/postulaciones",json={"id":application,"estado":"Preseleccionada"})
            key=str(uuid4())
            request(owner,"PATCH","/web-api/postulaciones",(200,202),json={"id":application,"estado":"Aceptada"},headers={"Idempotency-Key":key})
            for _ in range(80):
                result=request(owner,"GET",f"/web-api/postulaciones/{application}").json()
                if result["estado"]=="Aceptada": break
                time.sleep(.25)
            else: raise AssertionError("No se confirmó la incorporación por BFF.")
            rental=request(applicant,"GET","/web-api/arriendos/mio").json()
            assert rental["id_arriendo"]==result["id_arriendo"] and rental["integrantes_activos"]==1 and rental["cupos_disponibles"]==0
            for _ in range(2):
                replay=request(owner,"PATCH","/web-api/postulaciones",json={"id":application,"estado":"Aceptada"},headers={"Idempotency-Key":key}).json()
                assert replay["id_arriendo"]==rental["id_arriendo"]
            assert database.execute("SELECT count(*) FROM convivencia_mensajeria.pertenencia WHERE id_usuario=%s AND estado='Activa'",(people[12]["business_id"],)).fetchone()[0]==1
            own=request(applicant,"GET","/web-api/postulaciones").json()["items"]
            assert own[0]["estado"]=="Aceptada" and own[0]["id_arriendo"]==rental["id_arriendo"]
            request(stranger,"GET",f"/web-api/postulaciones/{application}",(404,))
            request(stranger,"POST","/web-api/postulaciones",(409,),json={"publicacion":publication})
            print("PASS D02 web: tres sesiones; Next/BFF/Gateway/Auth/Listado/Convivencia reales; SQL temporal; proveedor de identidad simulado",flush=True)
    finally:
        if process is not None and process.poll() is None:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
            else:
                process.terminate()
            process.wait(timeout=20)
        if isolated.parent.resolve()!=project.resolve() or not isolated.name.startswith(".proxy-test-112-"):
            raise AssertionError("Ruta de limpieza inesperada.")
        if linked:
            if os.name=="nt": os.rmdir(isolated / "node_modules")
            else: (isolated / "node_modules").unlink()
        def cleanup_error(function,path,error):
            if not isinstance(error,FileNotFoundError): raise error
        shutil.rmtree(isolated,onexc=cleanup_error)
