BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE convivencia_mensajeria.tarea (
  id_tarea BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_arriendo BIGINT NOT NULL REFERENCES convivencia_mensajeria.arriendo(id_arriendo),
  titulo TEXT NOT NULL CHECK (length(btrim(titulo)) > 0),
  descripcion TEXT,
  id_asignado BIGINT CHECK (id_asignado > 0),
  estado TEXT NOT NULL DEFAULT 'Pendiente' CHECK (estado IN ('Pendiente','Completada')),
  id_creador BIGINT NOT NULL CHECK (id_creador > 0),
  creada_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (estado <> 'Completada' OR id_asignado IS NOT NULL)
);

CREATE INDEX tarea_pagina ON convivencia_mensajeria.tarea(id_arriendo, creada_en DESC, id_tarea DESC);
CREATE INDEX tarea_asignada ON convivencia_mensajeria.tarea(id_arriendo, id_asignado, estado);

CREATE FUNCTION convivencia_mensajeria.desasignar_tareas_al_retirar() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
  -- Serializa la baja con la autorización y las escrituras de la API de tareas.
  PERFORM 1 FROM convivencia_mensajeria.arriendo WHERE id_arriendo=OLD.id_arriendo FOR UPDATE;
  UPDATE convivencia_mensajeria.tarea SET id_asignado=NULL
  WHERE id_arriendo=OLD.id_arriendo AND id_asignado=OLD.id_usuario AND estado='Pendiente';
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION convivencia_mensajeria.desasignar_tareas_al_retirar() FROM PUBLIC;
CREATE TRIGGER desasignar_tareas_al_retirar AFTER UPDATE OF estado ON convivencia_mensajeria.pertenencia
FOR EACH ROW WHEN (OLD.estado='Activa' AND NEW.estado='Inactiva')
EXECUTE FUNCTION convivencia_mensajeria.desasignar_tareas_al_retirar();

REVOKE ALL ON convivencia_mensajeria.tarea FROM PUBLIC;
REVOKE ALL ON SEQUENCE convivencia_mensajeria.tarea_id_tarea_seq FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE(id_asignado,estado) ON convivencia_mensajeria.tarea TO sql_convivencia_mensajeria;
GRANT USAGE ON SEQUENCE convivencia_mensajeria.tarea_id_tarea_seq TO sql_convivencia_mensajeria;
COMMIT;
