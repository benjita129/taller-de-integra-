from datetime import datetime

import jwt

from backend.service_runtime.reporting_security import service_key
from app.models import ServiceError


class Tasks:
    def __init__(self, repository):
        self.repository = repository

    def list(self, rental_id, actor_id, status, assignee, limit, cursor):
        with self.repository.transaction() as connection:
            self._require_member(connection, rental_id, actor_id, write=False)
            scope = [rental_id, status, assignee]
            before = self._decode_cursor(cursor, actor_id, scope) if cursor is not None else None
            rows = self.repository.task_page(connection, rental_id, status, assignee, limit + 1, before)

        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = jwt.encode(
                {"aud": "tareas", "sub": str(actor_id), "filtros": scope,
                 "fecha": last["creada_en"].isoformat(), "id": last["id_tarea"]},
                service_key("CONVIVENCIA_CURSOR_SECRET"),
                algorithm="HS256",
            )
        return {"items": items, "siguiente_cursor": next_cursor}

    def create(self, rental_id, actor_id, data):
        with self.repository.transaction() as connection:
            self._require_member(connection, rental_id, actor_id)
            if data.id_asignado is not None:
                self._require_assignee(connection, rental_id, data.id_asignado)
            return self.repository.insert_task(connection, rental_id, actor_id, data)

    def reassign(self, task_id, actor_id, assignee):
        with self.repository.transaction() as connection:
            task = self._task_for_member(connection, task_id, actor_id)
            if task["estado"] != "Pendiente":
                raise ServiceError("TASK_ALREADY_COMPLETED", "La tarea completada conserva su asignación.")
            self._require_assignee(connection, task["id_arriendo"], assignee)
            return self.repository.assign_task(connection, task_id, assignee)

    def complete(self, task_id, actor_id):
        with self.repository.transaction() as connection:
            task = self._task_for_member(connection, task_id, actor_id)
            if task["id_asignado"] != actor_id:
                raise ServiceError("FORBIDDEN", "Solo el integrante asignado puede completar la tarea.", 403)
            if task["estado"] == "Completada":
                return task
            return self.repository.complete_task(connection, task_id)

    def _task_for_member(self, connection, task_id, actor_id):
        rental_id = self.repository.task_rental(connection, task_id)
        if rental_id is None:
            raise ServiceError("TASK_NOT_FOUND", "Tarea no encontrada.", 404)
        self._require_member(connection, rental_id, actor_id)
        return self.repository.task(connection, task_id)

    def _require_member(self, connection, rental_id, actor_id, *, write=True):
        rental = self.repository.lock_rental(connection, rental_id, write=write)
        if rental is None:
            raise ServiceError("RENTAL_NOT_FOUND", "Arriendo no encontrado.", 404)
        if rental["estado"] != "Activo" or not self.repository.active_member(connection, rental_id, actor_id):
            raise ServiceError("FORBIDDEN", "Se requiere pertenencia activa al arriendo.", 403)

    def _require_assignee(self, connection, rental_id, assignee):
        if not self.repository.active_member(connection, rental_id, assignee):
            raise ServiceError("INVALID_ASSIGNEE", "El asignado debe ser integrante activo del arriendo.", 422)

    @staticmethod
    def _decode_cursor(cursor, actor_id, scope):
        key = service_key("CONVIVENCIA_CURSOR_SECRET")
        try:
            claims = jwt.decode(cursor, key, algorithms=["HS256"], audience="tareas", subject=str(actor_id))
            date = datetime.fromisoformat(claims["fecha"])
            task_id = claims["id"]
            if (claims["sub"] != str(actor_id) or claims["filtros"] != scope or date.tzinfo is None
                    or type(task_id) is not int or not 0 < task_id <= 9223372036854775807):
                raise ValueError()
            return date, task_id
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise ServiceError("INVALID_CURSOR", "Cursor inválido para estos filtros o esta cuenta.", 422) from None
