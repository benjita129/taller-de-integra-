-- C04: estado de activación, proyección final e historial local de postulaciones.
BEGIN;
DO $$
DECLARE target regclass;
BEGIN
 target := COALESCE(to_regclass('listado_applications.publicacion'),to_regclass('haycupo.publicacion'));
 EXECUTE format('ALTER TABLE %s
  ADD COLUMN reglas_bloqueadas boolean NOT NULL DEFAULT false,
  ADD COLUMN ocupacion_finalizada boolean NOT NULL DEFAULT false',target);
 EXECUTE format('GRANT UPDATE(reglas_bloqueadas,ocupacion_finalizada,ocupacion_confirmada,
  version_ocupacion,version_capacidad,id_region,id_comuna,reglas) ON %s TO sql_listado_applications',target);
 EXECUTE format('GRANT INSERT(ocupacion_confirmada,version_ocupacion,id_region,id_comuna,reglas)
  ON %s TO sql_listado_applications',target);
 EXECUTE format('UPDATE %s p SET reglas_bloqueadas=true
  WHERE estado=''Activa'' OR ocupacion_confirmada>0 OR EXISTS (
   SELECT FROM listado_applications.postulacion a
   WHERE a.id_publicacion=p.id_publicacion AND a.estado=''Aceptada'')',target);
 EXECUTE format('CREATE TABLE listado_applications.expulsion_publicacion (
  id_publicacion bigint NOT NULL REFERENCES %s(id_publicacion),
  id_usuario bigint NOT NULL CHECK(id_usuario>0),
  version_ocupacion bigint NOT NULL CHECK(version_ocupacion>0),
  PRIMARY KEY(id_publicacion,id_usuario),
  UNIQUE(id_publicacion,version_ocupacion)
 )',target);
END $$;

CREATE INDEX postulacion_rechazada_por_aviso
 ON listado_applications.postulacion(id_publicacion,id_usuario) WHERE estado='Rechazada';
CREATE INDEX postulacion_abierta_por_aviso
 ON listado_applications.postulacion(id_publicacion,id_postulacion)
 WHERE estado IN ('Pendiente','Preseleccionada');

CREATE TABLE listado_applications.postulacion_historial (
 id_historial bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 id_postulacion bigint NOT NULL REFERENCES listado_applications.postulacion(id_postulacion),
 estado varchar(20) NOT NULL,
 motivo varchar(1000),
 fecha timestamptz NOT NULL
);
CREATE INDEX postulacion_historial_por_postulacion
 ON listado_applications.postulacion_historial(id_postulacion,id_historial);

-- Solo se importa el último estado conocido de registros anteriores.
INSERT INTO listado_applications.postulacion_historial(id_postulacion,estado,motivo,fecha)
 SELECT id_postulacion,estado,motivo,
  CASE WHEN estado='Pendiente' THEN fecha_postulacion ELSE actualizada_en END
 FROM listado_applications.postulacion;

CREATE FUNCTION listado_applications.registrar_historial_postulacion() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' OR NEW.estado IS DISTINCT FROM OLD.estado THEN
  INSERT INTO listado_applications.postulacion_historial(id_postulacion,estado,motivo,fecha)
   VALUES(NEW.id_postulacion,NEW.estado,NEW.motivo,
    CASE WHEN NEW.estado='Pendiente' THEN NEW.fecha_postulacion ELSE NEW.actualizada_en END);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER postulacion_registrar_historial
 AFTER INSERT OR UPDATE OF estado ON listado_applications.postulacion
 FOR EACH ROW EXECUTE FUNCTION listado_applications.registrar_historial_postulacion();

REVOKE ALL ON listado_applications.postulacion_historial,listado_applications.expulsion_publicacion FROM PUBLIC;
REVOKE ALL ON FUNCTION listado_applications.registrar_historial_postulacion() FROM PUBLIC;
GRANT SELECT,INSERT ON listado_applications.postulacion_historial,listado_applications.expulsion_publicacion TO sql_listado_applications;
GRANT USAGE ON SEQUENCE listado_applications.postulacion_historial_id_historial_seq TO sql_listado_applications;
ALTER TABLE listado_applications.postulacion_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE listado_applications.expulsion_publicacion ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_role_access ON listado_applications.postulacion_historial TO sql_listado_applications USING(true) WITH CHECK(true);
CREATE POLICY runtime_role_access ON listado_applications.expulsion_publicacion TO sql_listado_applications USING(true) WITH CHECK(true);
COMMIT;
