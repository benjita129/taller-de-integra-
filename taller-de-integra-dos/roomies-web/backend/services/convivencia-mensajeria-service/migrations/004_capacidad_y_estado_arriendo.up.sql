BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE convivencia_mensajeria.arriendo ADD COLUMN estado TEXT NOT NULL DEFAULT 'Activo'
  CHECK (estado IN ('Activo','Finalizado'));

WITH historial AS (
  SELECT id_arriendo, count(*) FILTER (WHERE estado='Activa') AS activos,
    count(*) FILTER (WHERE estado='Inactiva') AS inactivos
  FROM convivencia_mensajeria.pertenencia GROUP BY id_arriendo
)
UPDATE convivencia_mensajeria.arriendo a
SET estado=CASE WHEN h.activos=0 THEN 'Finalizado' ELSE a.estado END,
    version_ocupacion=a.version_ocupacion+h.inactivos
FROM historial h WHERE a.id_arriendo=h.id_arriendo AND h.inactivos>0;

-- El runtime puede incorporar un snapshot más reciente, pero no editar la capacidad directamente.
CREATE FUNCTION convivencia_mensajeria.sincronizar_capacidad(p_arriendo BIGINT, p_cupos BIGINT, p_version BIGINT)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,convivencia_mensajeria AS $$
BEGIN
  PERFORM 1 FROM convivencia_mensajeria.arriendo WHERE id_arriendo=p_arriendo FOR UPDATE;
  UPDATE convivencia_mensajeria.arriendo a
  SET cupos_totales=p_cupos, version_capacidad=p_version
  WHERE a.id_arriendo=p_arriendo AND a.estado='Activo' AND a.version_capacidad<p_version
    AND p_cupos>0 AND p_cupos >= (
      SELECT count(*) FROM convivencia_mensajeria.pertenencia p
      WHERE p.id_arriendo=a.id_arriendo AND p.estado='Activa'
    );
  RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION convivencia_mensajeria.sincronizar_capacidad(BIGINT,BIGINT,BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION convivencia_mensajeria.sincronizar_capacidad(BIGINT,BIGINT,BIGINT) TO sql_convivencia_mensajeria;
COMMIT;
