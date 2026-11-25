"""Persistencia propia; no hay joins, claves foráneas ni SQL de otros dominios."""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.service_runtime.settings import database_url
from app.models import ServiceError


TASK_FIELDS = "id_tarea,id_arriendo,titulo,descripcion,id_asignado,estado,id_creador,creada_en"


class PostgresRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory

    def connect(self):
        if self.connection_factory:
            return self.connection_factory()
        return psycopg.connect(database_url("CONVIVENCIA_DATABASE_URL", "sql_convivencia_mensajeria"), row_factory=dict_row, connect_timeout=3, prepare_threshold=None)

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            yield connection

    def begin(self, key, payload):
        with self.transaction() as c:
            c.execute("INSERT INTO convivencia_mensajeria.incorporacion(id_operacion,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, Jsonb(payload)))

    def pending(self):
        with self.transaction() as c:
            return c.execute("""WITH picked AS (
                SELECT id_operacion FROM convivencia_mensajeria.incorporacion WHERE estado='Pendiente'
                ORDER BY ultimo_intento NULLS FIRST,creada_en LIMIT 20 FOR UPDATE SKIP LOCKED)
                UPDATE convivencia_mensajeria.incorporacion i SET ultimo_intento=clock_timestamp()
                FROM picked p WHERE i.id_operacion=p.id_operacion RETURNING i.id_operacion,i.payload""").fetchall()

    def get(self, rental_id, user_id):
        with self.transaction() as c:
            row = c.execute("""SELECT a.id_arriendo,a.id_publicacion,a.cupos_totales,a.version_capacidad,
                (SELECT count(*) FROM convivencia_mensajeria.pertenencia p WHERE p.id_arriendo=a.id_arriendo AND p.estado='Activa') AS ocupacion
                FROM convivencia_mensajeria.arriendo a
                WHERE a.id_arriendo=%s AND EXISTS (SELECT 1 FROM convivencia_mensajeria.pertenencia p
                  WHERE p.id_arriendo=a.id_arriendo AND p.id_usuario=%s AND p.estado='Activa')""", (rental_id, user_id)).fetchone()
            if row is None:
                raise ServiceError("RENTAL_NOT_FOUND", "Arriendo no encontrado.", 404)
            return row

    def mine(self, user_id):
        with self.transaction() as c:
            row = c.execute("SELECT id_arriendo FROM convivencia_mensajeria.pertenencia WHERE id_usuario=%s AND estado='Activa'", (user_id,)).fetchone()
            if row is None:
                raise ServiceError("RENTAL_NOT_FOUND", "Arriendo no encontrado.", 404)
        return self.get(row["id_arriendo"], user_id)

    def lock_rental(self, connection, rental_id, *, write):
        # La baja de pertenencia usa el mismo bloqueo antes de desasignar.
        lock = "FOR UPDATE" if write else "FOR SHARE"
        return connection.execute(
            f"SELECT estado FROM convivencia_mensajeria.arriendo WHERE id_arriendo=%s {lock}",
            (rental_id,),
        ).fetchone()

    def active_member(self, connection, rental_id, user_id):
        return connection.execute(
            """SELECT 1 FROM convivencia_mensajeria.pertenencia
            WHERE id_arriendo=%s AND id_usuario=%s AND estado='Activa'""",
            (rental_id, user_id),
        ).fetchone() is not None

    def task_page(self, connection, rental_id, status, assignee, limit, before):
        date, task_id = before or (None, None)
        return connection.execute(
            f"""SELECT {TASK_FIELDS} FROM convivencia_mensajeria.tarea
            WHERE id_arriendo=%s
              AND (%s::text IS NULL OR estado=%s)
              AND (%s::bigint IS NULL OR id_asignado=%s)
              AND (%s::timestamptz IS NULL OR (creada_en,id_tarea)<(%s,%s))
            ORDER BY creada_en DESC,id_tarea DESC LIMIT %s""",
            (rental_id, status, status, assignee, assignee, date, date, task_id, limit),
        ).fetchall()

    def insert_task(self, connection, rental_id, actor_id, data):
        return connection.execute(
            f"""INSERT INTO convivencia_mensajeria.tarea(id_arriendo,id_creador,titulo,descripcion,id_asignado)
            VALUES(%s,%s,%s,%s,%s) RETURNING {TASK_FIELDS}""",
            (rental_id, actor_id, data.titulo, data.descripcion, data.id_asignado),
        ).fetchone()

    def task_rental(self, connection, task_id):
        row = connection.execute(
            "SELECT id_arriendo FROM convivencia_mensajeria.tarea WHERE id_tarea=%s",
            (task_id,),
        ).fetchone()
        return row["id_arriendo"] if row else None

    def task(self, connection, task_id):
        return connection.execute(
            f"SELECT {TASK_FIELDS} FROM convivencia_mensajeria.tarea WHERE id_tarea=%s",
            (task_id,),
        ).fetchone()

    def assign_task(self, connection, task_id, assignee):
        return connection.execute(
            f"UPDATE convivencia_mensajeria.tarea SET id_asignado=%s WHERE id_tarea=%s RETURNING {TASK_FIELDS}",
            (assignee, task_id),
        ).fetchone()

    def complete_task(self, connection, task_id):
        return connection.execute(
            f"UPDATE convivencia_mensajeria.tarea SET estado='Completada' WHERE id_tarea=%s RETURNING {TASK_FIELDS}",
            (task_id,),
        ).fetchone()

    def occupancy(self, publication_id):
        with self.transaction() as c:
            row = c.execute("""SELECT a.version_ocupacion, a.estado='Finalizado' AS finalizada,
                (SELECT count(*) FROM convivencia_mensajeria.pertenencia p
                 WHERE p.id_arriendo=a.id_arriendo AND p.estado='Activa') AS ocupacion
                FROM convivencia_mensajeria.arriendo a WHERE a.id_publicacion=%s""", (publication_id,)).fetchone()
            return row or {"ocupacion": 0, "version_ocupacion": 0, "finalizada": False}

    def overlapped(self, a, b):
        with self.transaction() as c:
            return c.execute("""SELECT EXISTS (
                SELECT FROM convivencia_mensajeria.pertenencia a
                JOIN convivencia_mensajeria.pertenencia b USING(id_arriendo)
                WHERE a.id_usuario=%s AND b.id_usuario=%s AND a.id_usuario<>b.id_usuario
                  AND (a.estado='Activa' OR a.terminada_en>a.creada_en)
                  AND (b.estado='Activa' OR b.terminada_en>b.creada_en)
                  AND a.creada_en<COALESCE(b.terminada_en,'infinity'::timestamptz)
                  AND b.creada_en<COALESCE(a.terminada_en,'infinity'::timestamptz)
            ) AS coincidio""", (a, b)).fetchone()["coincidio"]
