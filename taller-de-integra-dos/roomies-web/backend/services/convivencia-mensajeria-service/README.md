# Base de Convivencia - incorporación v1

Base ejecutable del release inicial. Incluye contrato HTTP, persistencia propia,
índices de unicidad, control transaccional de cupos y recuperación durable.
No acredita admisión integrada ni el módulo completo de convivencia/mensajería.

Los proveedores de habilitación de Identidad y reservas de Listado definidos en
`app/ports.py` están pendientes de implementación/aprobación por sus responsables.
Un proveedor ausente falla con 503, sin crear pertenencia ni inventar ocupación.
Listado sigue indicando `incorporacion_pendiente` al aceptar una postulación.

Desde `taller-de-integra-dos/roomies-web`:

```powershell
python -m pip install -r backend/services/convivencia-mensajeria-service/requirements.txt
python backend/services/run_service.py convivencia --env-file ruta/a/configuracion-privada --port 8004
docker build -f backend/services/convivencia-mensajeria-service/Dockerfile -t roomies-convivencia-base .
```

El runner valida entorno y DSN propio `CONVIVENCIA_DATABASE_URL`. Antes de
iniciar el servicio, ejecuta las migraciones pendientes de `migrations/*.up.sql`
en orden con un rol migrador y el login dedicado
`sql_convivencia_mensajeria` sin privilegios heredados.

## Contrato y recuperación

- `POST /internal/incorporaciones`: credencial `X-Roomies-Service` e
  `Idempotency-Key` UUID. Payload estricto: `id_postulacion`, `id_publicacion`,
  `id_usuario`, `version_capacidad` (enteros positivos).
- `GET /api/arriendos/mio` y `GET /api/arriendos/{id}`: identidad autenticada y
  correo confirmado. Un no integrante recibe 404.
- `GET /internal/publicaciones/{id}/ocupacion`: credencial `X-Roomies-Service`.
  Devuelve ocupación activa, versión de ocupación y marca de finalización. Una
  publicación sin arriendo tiene ocupación y versión cero y `finalizada: false`.
- La reserva de Listado es firme, no caduca unilateralmente y usa la misma UUID.
  La incorporación sincroniza la capacidad del arriendo cuando recibe una
  reserva firme de versión más reciente y queda al menos un cupo disponible.
- El ledger y la intención de reservar se confirman antes del HTTP externo.
  La transacción siguiente bloquea operación, usuario, publicación y postulación,
  reserva, incorpora y escribe outbox. Una caída antes del commit se recupera
  repitiendo la misma reserva idempotente. Si la identidad queda deshabilitada,
  primero se resuelve la reserva de esa operación y luego se encola liberación.
- El worker reanuda pendientes y entrega confirmación/liberación idempotente.
  Un rechazo local posterior a reservar escribe una compensación durable.
  Los lotes de 20 rotan por `ultimo_intento` para evitar que fallos permanentes
  impidan recuperar operaciones posteriores.
- La respuesta 201 se persiste y se repite exactamente, con
  `Idempotency-Replayed: true`. `confirmacion_publicacion: Pendiente` describe el
  recibo original; no es una consulta del estado actual de la outbox.

El health solo acredita proceso HTTP. El acta de contrato, pruebas y estado de
firma están en `docs/contracts/incorporacion.*`.

## Tareas compartidas (S3R-C05)

| Operación | Entrada y permiso |
| --- | --- |
| `GET /api/arriendos/{id}/tareas` | Integrante activo. Filtros opcionales `estado` (`Pendiente` o `Completada`) e `id_asignado`. |
| `POST /api/arriendos/{id}/tareas` | Integrante activo. `titulo` obligatorio, `descripcion` e `id_asignado` opcionales. Devuelve 201. |
| `PATCH /api/tareas/{id}` | Integrante activo. Cuerpo con `id_asignado` de un integrante activo del mismo arriendo. Devuelve 409 si la tarea ya está completada. |
| `PATCH /api/tareas/{id}/estado` | Solo el asignado activo. Cuerpo con `estado: "Completada"`. Repetir la operación devuelve la tarea completada. |

Cada tarea incluye `id_tarea`, `id_arriendo`, `titulo`, `descripcion`,
`id_asignado`, `estado`, `id_creador` y `creada_en`. El listado devuelve
`items` y `siguiente_cursor`. Enviar el cursor con la misma cuenta, arriendo
y filtros. `limite` acepta de 1 a 100 y vale 20 por defecto.

Aplicar `005_tareas_compartidas.up.sql` y configurar en Convivencia un
`CONVIVENCIA_CURSOR_SECRET` estable y exclusivo de al menos 32 caracteres
ASCII sin espacios. El Gateway usa `CONVIVENCIA_UPSTREAM_URL`.

La migración desasigna las pendientes en la misma transacción que cambia una
pertenencia de `Activa` a `Inactiva`. El bloqueo del arriendo serializa ese
cambio con las operaciones de tareas. Las completadas conservan su asignación.
El endpoint de retiro por dueño se integra en S3R-F03 con el mismo bloqueo.

El siguiente comando verifica C05 desde `roomies-web` con PostgreSQL efímero
y dos clientes HTTP.

```powershell
python backend/services/convivencia-mensajeria-service/tests/run_isolated.py -k test_tasks
```
