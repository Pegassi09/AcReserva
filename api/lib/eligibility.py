"""Centralized MongoDB validation for reservation writes."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pymongo import ReturnDocument

from .database import mongo_id, now
from .errors import DomainError

QUOTA_STATUSES = ("pending", "approved", "confirmed")
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def local_month_range(value: datetime):
    local = as_local(value)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.astimezone(UTC).replace(tzinfo=None), next_month.astimezone(UTC).replace(tzinfo=None)


def local_day_range(value: datetime):
    local = as_local(value)
    start = datetime.combine(local.date(), time.min, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


def as_local(value: datetime):
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(LOCAL_TZ)


def lock_resources(db, associate_id: str, room_id: str, equipment_ids: list[str], session):
    for key in sorted({f"associate:{associate_id}", f"room:{room_id}", *[f"equipment:{item}" for item in equipment_ids]}):
        db.reservation_locks.find_one_and_update(
            {"key": key},
            {"$set": {"touched_at": now()}, "$setOnInsert": {"created_at": now()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )


def validate_associate_eligibility(db, associate_id: str, starts_at: datetime, session, excluding_id=None):
    associate = db.associates.find_one({"_id": mongo_id(associate_id)}, session=session)
    if not associate or associate.get("status") != "active":
        raise DomainError("Associado não está apto a realizar reservas.", 422, "associate_ineligible")
    month_start, month_end = local_month_range(starts_at)
    base = {"associate_id": associate_id, "status": {"$in": QUOTA_STATUSES}, "starts_at": {"$gte": month_start, "$lt": month_end}}
    if excluding_id:
        base["_id"] = {"$ne": mongo_id(excluding_id)}
    used = db.reservations.count_documents(base, session=session)
    if used >= 4:
        raise DomainError("Limite máximo de 4 reservas mensais atingido.", 422, "monthly_quota")

    target_local = as_local(starts_at)
    day_filters = []
    for offset in (-7, 7):
        start, end = local_day_range(target_local + timedelta(days=offset))
        day_filters.append({"starts_at": {"$gte": start, "$lt": end}})
    week_query = {"associate_id": associate_id, "status": {"$in": QUOTA_STATUSES}, "$or": day_filters}
    if excluding_id:
        week_query["_id"] = {"$ne": mongo_id(excluding_id)}
    if db.reservations.find_one(week_query, session=session):
        raise DomainError("Data bloqueada: não é permitido reservar o mesmo dia da semana em semanas consecutivas.", 422, "consecutive_weekday")
    return {"used": used, "remaining": max(0, 4 - used)}


def validate_room_available(db, room_id: str, starts_at: datetime, ends_at: datetime, session, excluding_id=None):
    room = db.rooms.find_one({"_id": mongo_id(room_id), "status": "active"}, session=session)
    if not room:
        raise DomainError("Sala indisponível para reserva.", 422, "room_unavailable")
    overlap = {"room_id": room_id, "starts_at": {"$lt": ends_at}, "ends_at": {"$gt": starts_at}}
    if db.room_blocks.find_one(overlap, session=session):
        raise DomainError("Esta sala está bloqueada neste horário.", 422, "room_blocked")
    overlap["status"] = {"$in": QUOTA_STATUSES}
    if excluding_id:
        overlap["_id"] = {"$ne": mongo_id(excluding_id)}
    if db.reservations.find_one(overlap, session=session):
        raise DomainError("Esta sala já está reservada neste horário.", 409, "room_conflict")
    return room


def validate_equipment_available(db, equipment_ids: list[str], starts_at: datetime, ends_at: datetime, session, excluding_id=None):
    if not equipment_ids:
        return
    valid_equipment = list(db.equipment.find({"_id": {"$in": [mongo_id(item) for item in equipment_ids]}, "active": True}, session=session))
    if len(valid_equipment) != len(set(equipment_ids)):
        raise DomainError("Um ou mais equipamentos selecionados não estão disponíveis.", 422, "equipment_unavailable")
    overlap = {"equipment_ids": {"$in": equipment_ids}, "starts_at": {"$lt": ends_at}, "ends_at": {"$gt": starts_at}, "status": {"$in": QUOTA_STATUSES}}
    if excluding_id:
        overlap["_id"] = {"$ne": mongo_id(excluding_id)}
    conflict = db.reservations.find_one(overlap, session=session)
    if conflict:
        raise DomainError("Equipamento indisponível para este horário.", 409, "equipment_conflict")
