# Publicaciones v2 - S3R-C02

Implementación de la ficha S3R-C02 del backlog TI2 Sprint 3 v1.4, páginas 8,
20-21 y 42-43 (D06, D10-D12). El proceso de negocio es
`backend/services/listado-applications-service`; `backend/main` es legado.
El OpenAPI del proceso se publica en `/openapi.json`.

## Rutas y transición

| Método/ruta | Contrato |
| --- | --- |
| GET `/api/publicaciones` | Catálogo público, solo Arrendador disponible con ocupación confirmada. |
| GET `/api/publicaciones/{id}` | Detalle público, también después del cierre. |
| GET `/api/publicaciones/{id}/detalle` | Detalle público. Incluye `id_propietario` como entero cuando el Bearer corresponde a una sesión activa con correo confirmado. |
| GET `/api/publicaciones/mias` | JWT confirmado; solo publicaciones del actor, incluidas cerradas. |
| POST `/api/publicaciones` | JWT confirmado; multipart; propietario derivado del JWT. |
| PUT `/api/publicaciones/{id}` | Multipart; solo propietario. Conserva fecha de publicación. |
| PATCH `/api/publicaciones/{id}/cerrar` | Solo propietario. Cancela solicitudes abiertas y conserva imágenes e integrantes. El reintento devuelve el aviso cerrado. |
| GET `/api/postulaciones/{id}` | Postulante o dueño del aviso. Devuelve el estado vigente y el historial cronológico. |
| POST `/api/postulaciones/{id}/retiro` | Solo postulante. Retira una solicitud Pendiente o Preseleccionada. |
| GET `/api/regiones` | Catálogo nacional acotado, sin paginar. |
| GET `/api/regiones/{id}/comunas` | Comunas de esa región. |

`/api/publicaciones/buscar`, `/api/mis-publicaciones` y `/{id}/detalle` son alias
de transición. Los dos listados ahora devuelven un envelope; los consumidores web
se actualizan en este cambio. TI4 debe adoptar el mismo contrato antes de integrar.
Match adapta el envelope al arreglo anterior de hasta 100 resultados en
`/conexiones/publicaciones/buscar`; ese alias no sustituye al catálogo paginado.
Se conservan `id`, `cupos` e `imagen` como alias de transición, además de los
campos canónicos `id_publicacion`, `cupos_totales` e `imagenes`.
`tipo` identifica el origen (`Arrendador`); `tipo_vivienda` es
`casa`, `departamento` o `habitacion`.

## Listas, filtros y disponibilidad

Respuesta: `{"items": [...], "siguiente_cursor": "..."}`; cursor final `null`.
`limite` predeterminado 20, rango 1-100. Orden SQL keyset por
`fecha_publicacion DESC, id_publicacion DESC`. El cursor está firmado, asociado
a filtros/cuenta/lista y se devuelve sin interpretar. No es un snapshot de datos
concurrentes. Cambiar filtros o cuenta inicia una lista nueva.

Filtros combinables: `consulta`, `precio_min`, `precio_max`, `tipo_vivienda`,
`mascota`, `categoria`, `id_region`, `id_comuna`, `cupos_disponibles`.
`cupos_disponibles=n` compara exactamente capacidad menos ocupación confirmada;
`cupos_min=n` conserva temporalmente la comparación mínima. Combinarlos produce
422. `offset` se rechaza. Los alias antiguos `tipo` (vivienda), `mascotas` y
`personas` conservan su semántica anterior durante la transición; la web usa los
campos canónicos. El selector web ofrece las comunas de La Araucanía (CUT 9);
la API conserva las demás regiones y valida siempre la pareja región/comuna.

Una ocupación desconocida se expresa como `null` en el detalle y excluye el aviso
del catálogo de vacantes. Las nuevas publicaciones parten de ocupación cero.
La copia versionada recibe confirmaciones internas de Convivencia. Los cupos
disponibles descuentan también las reservas de incorporaciones en curso.

## Ciclo de postulación y ocupación

El cierre manual y la finalización del arriendo retiran la publicación del
catálogo y cancelan sus solicitudes Pendiente y Preseleccionada. El detalle
público sigue accesible y el aviso cerrado devuelve cero cupos. Si hay una
incorporación en curso, el cierre manual responde 409 hasta recuperar su
resultado. El arrendador decide Preseleccionada, Rechazada o Aceptada.
`Cancelada` se registra por retiro voluntario o por un efecto automático del
servicio. Un rechazo o expulsión impide volver a postular al mismo aviso.

Una incorporación confirmada conserva su propia postulación Aceptada y cancela
las demás solicitudes abiertas de esa persona. Los cambios guardan estado,
fecha y motivo en `historial` y el detalle los devuelve en orden cronológico.
Para registros anteriores a la migración se conserva el último estado conocido.

`PUT /internal/publicaciones/{id}/ocupacion` recibe `ocupacion` y
`version_ocupacion`, con `finalizada` e `id_usuario_expulsado` opcionales.
La llamada exige el token interno compartido y se ejecuta fuera del Gateway
público. Una versión anterior conserva la ocupación vigente. Una versión
repetida con la misma ocupación es inocua. Un cambio en el contenido de la
versión vigente devuelve 409. Un evento finalizado exige ocupación cero y
cierra el aviso en la misma transacción. Un evento de expulsión atrasado
registra el usuario sin modificar la ocupación.

Listado concilia los avisos con ocupación desconocida o positiva consultando
`GET /internal/publicaciones/{id}/ocupacion` en Convivencia cuando
`CONVIVENCIA_UPSTREAM_URL` está configurada. La conciliación espera a que las
incorporaciones en curso resuelvan sus reservas. El flujo F03 debe emitir el
evento cuando el dueño retire a un integrante.

## Formulario e imágenes

Campos: `titulo`, `descripcion`, `ubicacion`, `precio`, `cupos_totales`, `tipo`,
`tipo_vivienda`, `categoria`, `mascota`, `id_region`, `id_comuna`;
`reglas` admite una lista JSON de textos opcional. En edición, omitirla conserva
las reglas existentes. El primer ingreso efectivo fija el campo
`reglas_bloqueadas` y un intento posterior de cambiar las reglas devuelve 409.
El dueño puede ajustar los cupos a partir de la ocupación confirmada. Si hay
una incorporación en curso o la ocupación sigue sin conciliar, el cambio de
capacidad devuelve 409. Convivencia adopta la nueva capacidad al validar la
siguiente reserva. Precio CLP entero entre
0 y 999999999999, tanto en BD `bigint` como en JSON. Fracciones y valores fuera
del rango se rechazan antes de persistir. No se aceptan URLs de fotos nuevas.

Repetir el campo multipart `imagenes` para cada archivo. Al editar,
`imagenes_conservar` es una lista JSON ordenada de IDs pertenecientes al aviso;
`[]` quita todas las anteriores. Omitirla conserva las existentes. Las nuevas
se agregan después de las conservadas; la primera es portada. Máximo total 5,
JPEG/PNG/WebP, 5 000 000 bytes por archivo y 20 000 000 píxeles decodificados
acumulados por archivo. Se validan bytes, MIME y decodificación completa.

Enviar `Idempotency-Key` UUID estable y reutilizarlo al reintentar el mismo cuerpo.
Otro cuerpo con esa clave devuelve 409. El journal persiste antes de subir y usa
rutas únicas por actor/operación/contenido. El commit confirma referencias y versión;
recién después se limpian descartadas. Un fallo de upload/commit compensa objetos
nuevos; el journal permite recuperar interrupciones. La limpieza fallida queda
persistida y se reintenta. Las ediciones concurrentes comprueban versión y rechazan
el conflicto sin borrar la imagen ganadora.

Errores: 401/403 autenticación/permisos, 404 recurso ajeno/no encontrado,
409 conflicto, 413 bytes, 415 tipo, 422 validación y 503 dependencia.

## Migración y configuración

Aplicar como migrador, sobre una copia revisada de B03 y en este orden:

1. `001_publicaciones_contract.up.sql`: inventario y conversión segura del precio,
   columnas de ubicación/reglas/ocupación y restricciones.
2. `002_publication_images.sql`: referencias, versiones, journal y limpieza.
3. `003_catalogo_cut.up.sql`: catálogo CUT nacional de
   [SUBDERE, versión 2018](https://www.subdere.gov.cl/sites/default/files/documentos/CUT_2018_v04.xls),
   con hash de fuente en el SQL: 16 regiones, 346 comunas y 32 de La Araucanía.
4. `004_acceptance_operations.sql`: operaciones y reservas de incorporación.
5. `005_postulation_lifecycle.sql`: historial, reglas congeladas y estado de finalización.

Aplicar también `004_capacidad_y_estado_arriendo.up.sql` en Convivencia tras
sus migraciones anteriores. La prueba local con cuatro procesos HTTP y
PostgreSQL descartable se ejecuta con `python tests/integration/run_c03.py --c04`.

La primera migración aborta y muestra IDs con precios fraccionarios/fuera de rango;
no redondea. Los avisos heredados conservan IDs, URLs y datos; ubicación y ocupación
sin fuente quedan pendientes de conciliación. No deducirlas de texto o capacidad.
Las migraciones no se ejecutan al arrancar el servicio. Compose local solo las
aplica automáticamente al inicializar un volumen nuevo; los volúmenes existentes
requieren la migración controlada, sin borrarlos.

Configurar solo en Listado `ROOMIES_CURSOR_SECRET` (aleatorio, mínimo 32 caracteres,
estable entre réplicas y reinicios), `ROOMIES_SUPABASE_PROJECT_REF` y
`ROOMIES_SUPABASE_STORAGE_KEY`. Una clave privilegiada de Storage puede omitir RLS:
su alcance no queda limitado al bucket por usar este adaptador. Guardarla solo en
el servicio backend; el adaptador fija `publicaciones` y genera las rutas.
Admite claves `sb_secret_` mediante `apikey` y claves JWT `service_role` mediante
`apikey` y Bearer; consultar las [limitaciones de claves de Supabase](https://supabase.com/docs/guides/getting-started/api-keys).

Crear/verificar el bucket mediante la API administrativa de Supabase Storage:
POST `/storage/v1/bucket` con
`{"id":"publicaciones","name":"publicaciones","public":true,"file_size_limit":5000000,"allowed_mime_types":["image/jpeg","image/png","image/webp"]}`.
Si existe, PUT `/storage/v1/bucket/publicaciones` con la misma configuración.
Usar la clave backend mediante variables seguras, sin copiarla a logs o evidencias.
Comprobar con GET `/storage/v1/bucket/publicaciones` esos tres atributos.

No crear políticas INSERT/UPDATE/DELETE para `anon` o `authenticated` sobre ese
bucket. Revisar políticas existentes de `storage.objects` (incluidas `ALL` y las
permisivas globales) y probar que ambos roles no pueden escribir. La lectura pública
permite leer a quien conozca la URL. Las referencias viven en el esquema de Listado;
el backend elimina objetos por Storage API, sin borrar filas de `storage.objects`.

Gateway y BFF aceptan 26 000 000 bytes, suficientes para cinco archivos máximos
más campos/cabeceras multipart. El Gateway conserva boundary e Idempotency-Key.
Mantener ese límite en el ingress del despliegue. El BFF obtiene el token de sesión.

Referencias oficiales: [buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals),
[permisos](https://supabase.com/docs/guides/storage/security/access-control) y
[carga](https://supabase.com/docs/guides/storage/uploads/standard-uploads).

La validación local y los pendientes de integración se registran en
[`../S3R-C02.md`](../S3R-C02.md). La configuración actual de destinos PostgreSQL
todavía depende de B03 para Kubero; este cambio no acredita un despliegue remoto.
