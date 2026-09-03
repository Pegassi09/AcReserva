"""MongoDB Atlas connection, document helpers, and indexes for AC Reserva."""
from datetime import datetime
from functools import lru_cache
from threading import Lock

from bson import ObjectId
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
from pymongo.server_api import ServerApi

from .config import Settings
from .errors import DomainError

_index_lock = Lock()
_indexes_ready = False


def new_id() -> str:
    return str(ObjectId())


def valid_id(value: str | None) -> bool:
    return bool(value and ObjectId.is_valid(value))


@lru_cache(maxsize=1)
def client() -> MongoClient:
    if not Settings.mongodb_uri:
        raise DomainError(
            "O banco MongoDB ainda não foi configurado. Defina MONGODB_URI e MONGODB_DB antes do primeiro acesso.",
            503,
            "database_not_configured",
        )
    return MongoClient(
        Settings.mongodb_uri,
        server_api=ServerApi("1"),
        connectTimeoutMS=8000,
        serverSelectionTimeoutMS=8000,
    )


def database():
    global _indexes_ready
    db = client()[Settings.mongodb_db]
    if not _indexes_ready:
        with _index_lock:
            if not _indexes_ready:
                ensure_indexes(db)
                _indexes_ready = True
    return db


def ensure_indexes(db):
    db.users.create_index("email", unique=True)
    db.sectors.create_index("name", unique=True)
    db.associates.create_index("cnpj", unique=True)
    db.rooms.create_index("name", unique=True)
    db.equipment.create_index("name", unique=True)
    db.reservations.create_index("protocol", unique=True)
    db.reservations.create_index([("associate_id", ASCENDING), ("starts_at", ASCENDING)])
    db.reservations.create_index([("room_id", ASCENDING), ("starts_at", ASCENDING), ("ends_at", ASCENDING)])
    db.reservations.create_index([("equipment_ids", ASCENDING), ("starts_at", ASCENDING), ("ends_at", ASCENDING)])
    db.room_blocks.create_index([("room_id", ASCENDING), ("starts_at", ASCENDING), ("ends_at", ASCENDING)])
    db.reservation_locks.create_index("key", unique=True)
    db.audit_logs.create_index([("entity", ASCENDING), ("entity_id", ASCENDING), ("created_at", -1)])


def document(value: dict | None) -> dict | None:
    if value is None:
        return None
    result = dict(value)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    return result


def documents(values) -> list[dict]:
    return [document(value) for value in values]


def now() -> datetime:
    return datetime.utcnow()


def mongo_id(value: str) -> ObjectId:
    if not valid_id(value):
        raise DomainError("Identificador inválido.", 422, "invalid_id")
    return ObjectId(value)


def duplicate_as_domain_error(error: DuplicateKeyError):
    raise DomainError("Já existe um registro com estes dados.", 409, "duplicate_record") from error
