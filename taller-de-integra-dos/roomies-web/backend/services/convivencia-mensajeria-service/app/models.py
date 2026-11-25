from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PositiveId = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]
TaskStatus = Literal["Pendiente", "Completada"]


class Incorporation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_postulacion: PositiveId
    id_publicacion: PositiveId
    id_usuario: PositiveId
    version_capacidad: PositiveId


class Reservation(Incorporation):
    id_reserva: UUID
    cupos_totales: PositiveId


class OccupancyConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_arriendo: PositiveId
    ocupacion: Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
    version_ocupacion: PositiveId


class Occupancy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ocupacion: Annotated[int, Field(strict=True, ge=0, le=2147483647)]
    version_ocupacion: Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
    finalizada: Annotated[bool, Field(strict=True)]


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_incorporacion: UUID
    id_arriendo: PositiveId
    id_publicacion: PositiveId
    id_usuario: PositiveId
    estado: Literal["Activa"]
    confirmacion_publicacion: Literal["Pendiente"]


class Rental(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_arriendo: PositiveId
    id_publicacion: PositiveId
    cupos_totales: PositiveId
    version_capacidad: PositiveId
    ocupacion: Annotated[int, Field(strict=True, ge=0)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, pattern=r"^[^\x00]+$")]
    descripcion: Annotated[str, StringConstraints(strict=True, pattern=r"^[^\x00]*$")] | None = None
    id_asignado: PositiveId | None = None


class TaskAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_asignado: PositiveId


class TaskCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["Completada"]


class Task(BaseModel):
    id_tarea: PositiveId
    id_arriendo: PositiveId
    titulo: str
    descripcion: str | None
    id_asignado: PositiveId | None
    estado: TaskStatus
    id_creador: PositiveId
    creada_en: datetime


class TaskPage(BaseModel):
    items: list[Task]
    siguiente_cursor: str | None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: str
    code: str


class ServiceError(Exception):
    def __init__(self, code, detail, status=409):
        self.status = status
        self.body = {"detail": detail, "code": code}
        super().__init__(detail)


def unavailable():
    return ServiceError("DEPENDENCY_UNAVAILABLE", "Dependencia no disponible; reintenta con la misma clave.", 503)
