# Pruebas de Sprint 3 para Benjamín Cabrera

La sección 8.3 del backlog TI2 Sprint 3 v1.4 (pp. 20–23) asigna seis tareas, de S3R-C01 a S3R-C06. Esta guía reúne los cambios de cada tarea, su prueba local y la evidencia que falta para cerrar el sprint.

## Entorno virtual

Abre PowerShell en la raíz del repositorio. Con Python 3.13 y PostgreSQL instalados, ejecuta el lanzador de pruebas.

```powershell
Set-Location .\taller-de-integra-dos\roomies-web
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\integration\run_s3.ps1 -Task All
```

Para ejecutar una sola tarea, usa `-Task C01`, `-Task C02`, `-Task C03`, `-Task C04`, `-Task C05` o `-Task C06`. El [lanzador](../tests/integration/run_s3.ps1) crea o reutiliza `.venv` en la raíz del repositorio e instala las dependencias de las pruebas. Para indicar una instalación específica de PostgreSQL, añade `-PgBin 'C:\Program Files\PostgreSQL\18\bin'`.

Los ensayos de PostgreSQL crean un clúster temporal que escucha en `127.0.0.1` con cuentas, claves y datos de prueba. Al terminar, los runners detienen el clúster de cada ensayo. Los servicios del recorrido de integración se levantan en procesos separados y el proveedor externo de identidad se simula localmente.

Para exigir las comprobaciones de Convivencia en el recorrido local, ejecuta `-Task C06 -StrictC06`. El código `2` indica cobertura pendiente. El código `1` indica un fallo de ejecución o de una comprobación. El modo estricto se puede combinar con `-Task All`.

Para ejecutar directamente C06 con el mismo Python del entorno virtual, usa este comando desde `roomies-web`.

```powershell
..\..\.venv\Scripts\python.exe -I -B -X utf8 tests/integration/run_c03.py --c06
```

## Cambios y criterios de comprobación

| Tarea | Dónde está el código | Qué comprobar |
| --- | --- | --- |
| **S3R-C01 · Base y contrato de Convivencia** | [Contrato y ejemplos](contracts/incorporacion.md), [esquema e índices](../backend/services/convivencia-mensajeria-service/migrations/001_convivencia_schema.up.sql), [servicio](../backend/services/convivencia-mensajeria-service/app/service.py) y [pruebas](../backend/services/convivencia-mensajeria-service/tests/test_incorporaciones.py). La ruta canónica contiene esta base desde `1ce7664`. | `POST /internal/incorporaciones` y consultas de arriendo. Una pertenencia activa por usuario, un arriendo por aviso, reserva/versionado e idempotencia. Un reintento devuelve el mismo recibo y una sola pertenencia. |
| **S3R-C02 · Publicaciones, imágenes y paginación** | [Contrato v2](contracts/publicaciones.md), [rutas de Listado](../backend/services/listado-applications-service/app/api/routes.py), [gestión de imágenes](../backend/services/listado-applications-service/app/application/images.py), [selector geográfico web](../frontend-next/src/features/publicaciones/LocationFields.tsx) y [pruebas SQL de imágenes](../backend/services/listado-applications-service/tests/test_images_postgres.py). Base `d8dddd1`. | Cursor con fechas empatadas, filtro exacto de cupos, catálogo nacional, selector web de La Araucanía, precio entero CLP y validación/límites de imágenes. Comprobar que una edición conserva la fecha y que el cierre conserva imágenes. Los ensayos locales de imágenes combinan SQL real con un adaptador de Storage simulado. |
| **S3R-C03 · Aceptación y recuperación** | [Coordinador de admisión de Listado](../backend/services/listado-applications-service/app/application/admissions.py), [operación y reserva](../backend/services/listado-applications-service/migrations/004_acceptance_operations.sql) y [runner HTTP y SQL](../tests/integration/run_c03.py). Base `225433f`. | Aceptar confirma la postulación cuando existe la pertenencia. Dos candidatos disputan el último cupo, una persona intenta entrar en dos arriendos, y se pierde una respuesta después de confirmar. Comprobar la convergencia con la misma clave y el 409 al reutilizarla con otro recurso. |
| **S3R-C04 · Edición, cancelaciones y estados** | [Ciclo de postulaciones](../backend/services/listado-applications-service/app/application/service.py), [historial y proyecciones](../backend/services/listado-applications-service/migrations/005_postulation_lifecycle.sql) y [escenarios HTTP](../tests/integration/c04.py). Base `a004440`. | Cierre idempotente, historial, cancelación de solicitudes abiertas tras ingreso efectivo, retiro de solicitud, reglas congeladas y capacidad que respeta ocupación. Un evento duplicado o fuera de orden conserva la proyección vigente. |
| **S3R-C05 · Tareas compartidas** | [Permisos y reasignación](../backend/services/convivencia-mensajeria-service/app/tasks.py), [migración de tareas](../backend/services/convivencia-mensajeria-service/migrations/005_tareas_compartidas.up.sql), [pruebas](../backend/services/convivencia-mensajeria-service/tests/test_tasks.py) y [rutas públicas del Gateway](../backend/api-gateway/app/local_routes.py). Base `04781d3`. | Un integrante crea y asigna, solo el asignado activo completa, y otro cliente ve el resultado. Si se retira un integrante, sus pendientes se desasignan, se pueden reasignar y las completadas conservan su historial. |
| **S3R-C06 · Concurrencia y consistencia** | [Runner y fallos controlados de comunicación](../tests/integration/run_c03.py), [puntos de recuperación de admisión](../tests/integration/c06.py) y [pertenencia, tareas y chat](../tests/integration/c06_membership.py). | Correlacionar postulaciones, reservas, ocupación y pertenencias ante operaciones paralelas e interrupciones. Verificar reintentos, recuperación sin reiniciar PostgreSQL, permisos y consistencia de tareas al retirar un integrante. |

## Resultados locales

Entorno de la ejecución del 25/11/2026 en Windows, Python 3.13.15 y PostgreSQL 18.6. Los comandos del lanzador se ejecutan desde `roomies-web`.

| Comando para reproducir | Resultado |
| --- | --- |
| `./tests/integration/run_s3.ps1 -Task C01` | 62 pruebas aprobadas. |
| `./tests/integration/run_s3.ps1 -Task C02` | 51 pruebas aprobadas. |
| `./tests/integration/run_s3.ps1 -Task C03` | Siete escenarios aprobados en la fase C03 de las ejecuciones de C04 y C06. |
| `./tests/integration/run_s3.ps1 -Task C04` | Cuatro escenarios aprobados después de C03. El retiro voluntario se ejecutó por HTTP. Para verificar versiones y cierre final, el runner simuló en SQL temporal el cambio de pertenencia que origina el evento. |
| `./tests/integration/run_s3.ps1 -Task C05` | 5 pruebas aprobadas. |
| `./tests/integration/run_s3.ps1 -Task C06 -StrictC06` | Escenarios disponibles aprobados. El modo estricto señaló como pendientes F02 y F03. |

En los primeros intentos simultáneos apareció HTTP 504 del Gateway. La reejecución que completó los escenarios usó márgenes de 25 segundos de lectura y 30 segundos totales en el proceso de Gateway que inicia el runner. Los proxies de prueba reutilizaron sus clientes HTTP locales. Estos ajustes pertenecen al entorno de la prueba.

En `frontend-next`, con Node 24.22.3, `node --test tests/publications.test.mjs` aprobó 19 casos de publicaciones y `node --test tests/applications.test.mjs` aprobó 11 casos de postulaciones. Ambas suites validan adaptadores de la aplicación web con respuestas controladas.

La prueba web de ubicación pasó en Chrome sin interfaz, sobre Next aislado. `node --test tests/proxy.test.mjs` aprobó 13 casos, incluido el selector de las 32 comunas de La Araucanía, el reintento al cargar y la conservación de la comuna al editar. Para repetirla desde `frontend-next`, activa `PUBLICATIONS_BROWSER_TESTS=1` e indica en `PROFILE_PLAYWRIGHT_PATH` la ruta a Playwright y en `PROFILE_BROWSER_PATH` la ruta al ejecutable de Chrome.

### Cortes de comunicación en C06

El runner comprueba el estado de ambos servicios con la misma clave de operación durante el corte y después de restablecer el enlace. El detalle se imprime sin incluir la clave ni identificadores personales.

| Punto del recorrido | Estado comprobado durante la ejecución local |
| --- | --- |
| Listado guarda la intención de aceptar y se corta el acceso a Convivencia. | Postulación `Preseleccionada`, operación `Pendiente` y ocupación 0. |
| Convivencia guarda la incorporación y se corta la consulta a Identidad. | Incorporación `Pendiente` en `ValidarIdentidad`, sin reserva ni pertenencia. |
| Listado reserva el cupo y se pierde la respuesta. | Reserva `Reservada`, cupo indisponible en el aviso y ocupación confirmada 0. |
| Convivencia confirma la pertenencia y se pierde su respuesta. | Pertenencia `Activa`, ocupación 1 en Convivencia y aceptación pendiente de confirmación en Listado. |
| Listado confirma reserva y ocupación, y Convivencia pierde esa respuesta. | Reserva `Confirmada`, ocupación publicada 1 y confirmación pendiente de registrar en la outbox. |
| Se restablecen las llamadas. | Postulación `Aceptada`, operación `Confirmada`, ocupación publicada 1 y outbox con entrega registrada. |

Tras perder también la respuesta final al cliente, el mismo reintento devolvió el arriendo confirmado. Se comprobó que quedaran una sola pertenencia, un solo evento de aceptación, ocupación dentro de la capacidad y el mismo inicio de PostgreSQL durante el corte y la recuperación.

En la prueba de retiro, se cambió la pertenencia en el PostgreSQL temporal para representar el commit de F03. PostgreSQL mantuvo en espera la lectura y el completado por HTTP hasta el commit y luego el servicio rechazó ambas operaciones del integrante retirado. Un miembro activo pudo reasignar la tarea pendiente y completarla. La tarea completada previamente conservó su asignación y Listado reconcilió la ocupación.

## Cierre de evidencia

- **C01.** Confirmar la firma o aceptación del equipo en el ticket correspondiente. El contrato técnico tiene [evidencia histórica](contracts/incorporacion.evidencia.md).
- **C02.** Queda por verificar Supabase Storage en el entorno común. Crear y editar con imágenes reales, abrirlas desde otro dispositivo, comprobar permisos de escritura del bucket y repetir la lectura tras un redeploy. La validación web/móvil de D11 se registra por cliente.
- **C05/C06.** El retiro de una postulación abierta pertenece a Listado. El cambio de pertenencia probado en SQL acredita el efecto local sobre las tareas. En la revisión de `dev-web` quedaron pendientes las rutas de expulsión de integrante F03 (`POST /api/arriendos/{id}/expulsiones`) y chat F02 (`/api/conversaciones`). Las referencias locales de las ramas SCRUM-126 (`3686d30`) y SCRUM-125 (`27fa9ac`) contienen sus respectivos cambios. El cierre requiere repetir el retiro por HTTP y probar el chat con el dueño no residente, un miembro activo y un integrante retirado en la versión integrada.
- **C06.** Repetir los casos correspondientes en la topología de servicios y persistencia de S3R-B04. Registrar comandos, resultados sanitizados, versión del entorno y el SHA del commit probado. Adjuntar el enlace de PR o Jira cuando esté disponible.

La base de la revisión es `04781d376368e7ba8ceedcd3f52949b4bbd7cba7` en `dev-web`, más los cambios de C06 en el árbol de trabajo. Falta confirmar el enlace específico de PR o Jira de C06.
