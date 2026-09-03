import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError, PyMongoError

from api.lib.config import Settings
from api.lib.database import client, database, document, documents, mongo_id, new_id, now
from api.lib.eligibility import (
    QUOTA_STATUSES,
    lock_resources,
    validate_associate_eligibility,
    validate_equipment_available,
    validate_room_available,
)
from api.lib.errors import DomainError, Forbidden, Unauthorized
from api.lib.security import create_token, decode_token, hash_password, verify_password

PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="AC Reserva API", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(Settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.mount("/assets", StaticFiles(directory=PROJECT_ROOT / "assets"), name="assets")


class LoginPayload(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=512)
    identifier: str | None = Field(default=None, max_length=30)
    sector_id: str | None = Field(default=None, max_length=64)
    access_type: str = Field(default="associate", pattern="^(associate|acim)$")


class SetupAdminPayload(BaseModel):
    name: str = Field(min_length=3, max_length=150)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=512)


class ReservationPayload(BaseModel):
    associate_id: str | None = Field(default=None, max_length=64)
    requester_id: str | None = Field(default=None, max_length=64)
    room_id: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    title: str = Field(min_length=3, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    participant_count: int = Field(default=1, ge=1, le=5000)
    equipment_ids: list[str] = Field(default_factory=list, max_length=30)
    needs_it: bool = False
    needs_reception: bool = False
    needs_coffee: bool = False

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Envie os horários com fuso horário (ISO 8601).")
        return value.astimezone(UTC).replace(tzinfo=None)

    @field_validator("ends_at")
    @classmethod
    def validate_end(cls, ends_at, info):
        if info.data.get("starts_at") and ends_at <= info.data["starts_at"]:
            raise ValueError("O horário final deve ser posterior ao inicial.")
        return ends_at


def error_response(error: DomainError):
    return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code, "message": error.message}})


@app.exception_handler(DomainError)
async def handle_domain_error(_request: Request, error: DomainError):
    return error_response(error)


@app.exception_handler(PyMongoError)
async def handle_database_error(_request: Request, _error: PyMongoError):
    return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable", "message": "Não foi possível acessar o banco MongoDB. Verifique MONGODB_URI e a liberação de rede no Atlas."}})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, error: Exception):
    logger.exception("Unexpected error while handling %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Não foi possível concluir a operação."}})


def require_runtime_configuration():
    if not Settings.is_configured():
        raise DomainError(Settings.configuration_message(), 503, "configuration_required")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(PROJECT_ROOT / "index.html")


def normalized_identifier(value: str | None) -> str | None:
    return "".join(char for char in value if char.isalnum()) if value else None


def serialize_user(user: dict):
    return {"id": str(user["_id"]), "name": user["name"], "email": user["email"], "roles": user.get("roles", []), "associate_id": user.get("associate_id")}


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized()
    try:
        user_id = decode_token(authorization[7:])["sub"]
    except Exception as exc:
        raise Unauthorized("Sessão expirada ou inválida.") from exc
    user = database().users.find_one({"_id": mongo_id(user_id), "active": True})
    if not user:
        raise Unauthorized("Usuário inativo ou inexistente.")
    return user


def require_roles(user: dict, *roles: str):
    if not set(user.get("roles", [])).intersection(roles):
        raise Forbidden()


def is_staff(user: dict) -> bool:
    return bool(set(user.get("roles", [])).intersection({"admin", "reception", "it", "operational"}))


def audit(db, user_id: str, action: str, entity: str, entity_id: str, request: Request, session=None):
    db.audit_logs.insert_one({"user_id": user_id, "action": action, "entity": entity, "entity_id": entity_id, "ip_address": request.client.host if request.client else None, "created_at": now()}, session=session)


def reservation_view(db, reservation: dict) -> dict:
    result = document(reservation)
    room = db.rooms.find_one({"_id": mongo_id(result["room_id"])}) if result.get("room_id") else None
    associate = db.associates.find_one({"_id": mongo_id(result["associate_id"])}) if result.get("associate_id") else None
    requester = db.requesters.find_one({"_id": mongo_id(result["requester_id"])}) if result.get("requester_id") else None
    result["room_name"] = room.get("name") if room else "Sala removida"
    result["associate_name"] = (associate.get("trade_name") or associate.get("legal_name")) if associate else "Associado removido"
    result["requester_name"] = requester.get("name") if requester else None
    return result


@app.get("/api/health")
def health():
    return {
        "service": "ac-reserva",
        "status": "ok",
        "database": "mongodb",
        "database_configured": bool(Settings.mongodb_uri),
        "authentication_configured": bool(Settings.jwt_secret),
        "configuration_ready": Settings.is_configured(),
    }


@app.get("/api/public/sectors")
def public_sectors():
    return {"data": documents(database().sectors.find({"active": True}, {"name": 1}).sort("name", 1))}


@app.get("/api/setup/status")
def setup_status():
    if not Settings.is_configured():
        return {
            "data": {
                "needs_setup": False,
                "configuration_ready": False,
                "configuration_message": Settings.configuration_message(),
            }
        }
    return {"data": {"needs_setup": database().users.count_documents({}) == 0, "configuration_ready": True}}


@app.post("/api/setup/admin", status_code=201)
def setup_admin(payload: SetupAdminPayload, request: Request):
    require_runtime_configuration()
    db = database()

    def create_first(session):
        if db.users.count_documents({}, session=session):
            raise Forbidden("A configuração inicial já foi concluída. Use a tela de acesso.")
        try:
            db.settings.insert_one({"_id": "initial_setup", "created_at": now()}, session=session)
        except DuplicateKeyError as exc:
            raise Forbidden("A configuração inicial já foi concluída. Use a tela de acesso.") from exc
        user = {"_id": ObjectId(), "name": payload.name.strip(), "email": payload.email.strip().lower(), "password_hash": hash_password(payload.password), "roles": ["admin"], "sector_ids": [], "associate_id": None, "active": True, "created_at": now(), "updated_at": now()}
        db.users.insert_one(user, session=session)
        audit(db, str(user["_id"]), "initial_setup", "user", str(user["_id"]), request, session)
        return user

    with client().start_session() as session:
        user = session.with_transaction(create_first)
    token = create_token(str(user["_id"]), user["roles"])
    return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request):
    require_runtime_configuration()
    db = database()
    user = db.users.find_one({"email": payload.email.strip().lower(), "active": True})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise Unauthorized("Credenciais inválidas.")
    if payload.access_type == "associate":
        associate = db.associates.find_one({"_id": mongo_id(user["associate_id"])}) if user.get("associate_id") else None
        if not associate or normalized_identifier(payload.identifier) != normalized_identifier(associate.get("cnpj")):
            raise Unauthorized("Credenciais inválidas.")
    if payload.sector_id and payload.sector_id not in user.get("sector_ids", []):
        raise Forbidden("Você não está autorizado para o setor selecionado.")
    if payload.access_type == "acim" and not payload.sector_id and "admin" not in user.get("roles", []):
        raise Forbidden("Selecione um setor autorizado para continuar.")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now(), "updated_at": now()}})
    audit(db, str(user["_id"]), "login", "user", str(user["_id"]), request)
    return {"token": create_token(str(user["_id"]), user.get("roles", [])), "user": serialize_user(user)}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"data": serialize_user(user)}


@app.get("/api/rooms")
def rooms(_user: dict = Depends(current_user)):
    return {"data": documents(database().rooms.find({"status": "active"}).sort("name", 1))}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    db = database()
    if user.get("associate_id") and not is_staff(user):
        associate_id = user["associate_id"]
        current = now()
        local = current.replace(tzinfo=UTC).astimezone(ZoneInfo("America/Sao_Paulo")).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_start = local.astimezone(UTC).replace(tzinfo=None)
        month_end = next_month.astimezone(UTC).replace(tzinfo=None)
        quota = db.reservations.count_documents({"associate_id": associate_id, "status": {"$in": QUOTA_STATUSES}, "starts_at": {"$gte": month_start, "$lt": month_end}})
        upcoming = list(db.reservations.find({"associate_id": associate_id, "starts_at": {"$gte": current}, "status": {"$ne": "cancelled"}}).sort("starts_at", 1).limit(5))
        return {"data": {"quota": {"used": quota, "limit": 4, "remaining": max(0, 4 - quota)}, "upcoming": [reservation_view(db, item) for item in upcoming], "available_rooms": db.rooms.count_documents({"status": "active"})}}
    require_roles(user, "admin", "reception", "it", "operational")
    active = db.reservations.count_documents({"status": {"$in": QUOTA_STATUSES}})
    local_day = now().replace(tzinfo=UTC).astimezone(ZoneInfo("America/Sao_Paulo")).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_day.astimezone(UTC).replace(tzinfo=None)
    today_end = (local_day + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)
    return {"data": {"active_reservations": active, "today": db.reservations.count_documents({"starts_at": {"$gte": today_start, "$lt": today_end}})}}


@app.get("/api/reservations")
def reservations(user: dict = Depends(current_user)):
    db = database()
    query = {"associate_id": user["associate_id"]} if user.get("associate_id") and not is_staff(user) else {}
    if not query:
        require_roles(user, "admin", "reception", "it", "operational")
    return {"data": [reservation_view(db, item) for item in db.reservations.find(query).sort("starts_at", -1).limit(100)]}


@app.post("/api/reservations", status_code=201)
def create_reservation(payload: ReservationPayload, request: Request, user: dict = Depends(current_user)):
    db = database()
    associate_id = payload.associate_id if is_staff(user) else user.get("associate_id")
    if not associate_id:
        raise Forbidden("Um associado vinculado é necessário para criar a reserva.")
    requester_id = payload.requester_id

    def create(session):
        nonlocal requester_id
        if requester_id:
            requester = db.requesters.find_one({"_id": mongo_id(requester_id), "associate_id": associate_id, "active": True}, session=session)
            if not requester:
                raise DomainError("Solicitante não pertence ao associado informado.", 422, "requester_invalid")
        elif not is_staff(user):
            requester = db.requesters.find_one({"user_id": str(user["_id"]), "associate_id": associate_id, "active": True}, session=session)
            if not requester:
                raise DomainError("Cadastre um solicitante ativo vinculado ao usuário.", 422, "requester_required")
            requester_id = str(requester["_id"])
        lock_resources(db, associate_id, payload.room_id, payload.equipment_ids, session)
        quota = validate_associate_eligibility(db, associate_id, payload.starts_at, session)
        validate_room_available(db, payload.room_id, payload.starts_at, payload.ends_at, session)
        validate_equipment_available(db, payload.equipment_ids, payload.starts_at, payload.ends_at, session)
        reservation = {"_id": ObjectId(), "protocol": f"ACR-{payload.starts_at.year}-{new_id()[:8].upper()}", "associate_id": associate_id, "requester_id": requester_id, "room_id": payload.room_id, "starts_at": payload.starts_at, "ends_at": payload.ends_at, "title": payload.title.strip(), "description": payload.description, "participant_count": payload.participant_count, "equipment_ids": list(dict.fromkeys(payload.equipment_ids)), "status": "pending", "needs_it": payload.needs_it, "needs_reception": payload.needs_reception, "needs_coffee": payload.needs_coffee, "google_calendar_event_id": None, "created_at": now(), "updated_at": now()}
        db.reservations.insert_one(reservation, session=session)
        audit(db, str(user["_id"]), "create", "reservation", str(reservation["_id"]), request, session)
        return reservation, quota

    with client().start_session() as session:
        reservation, quota = session.with_transaction(create)
    return {"data": {"id": str(reservation["_id"]), "protocol": reservation["protocol"], "status": reservation["status"], "quota": quota}}


@app.post("/api/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: str, request: Request, user: dict = Depends(current_user)):
    db = database()

    def cancel(session):
        reservation = db.reservations.find_one({"_id": mongo_id(reservation_id)}, session=session)
        if not reservation:
            raise DomainError("Reserva não encontrada.", 404, "not_found")
        if not is_staff(user) and reservation.get("associate_id") != user.get("associate_id"):
            raise Forbidden()
        if reservation["status"] in ("cancelled", "rejected"):
            raise DomainError("Esta reserva já está encerrada.", 422, "reservation_closed")
        db.reservations.update_one({"_id": reservation["_id"]}, {"$set": {"status": "cancelled", "cancelled_at": now(), "updated_at": now()}}, session=session)
        audit(db, str(user["_id"]), "cancel", "reservation", reservation_id, request, session)

    with client().start_session() as session:
        session.with_transaction(cancel)
    return {"data": {"id": reservation_id, "status": "cancelled"}}
