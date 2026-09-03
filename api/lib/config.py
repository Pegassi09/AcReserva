import os


class Settings:
    mongodb_uri = os.getenv("MONGODB_URI", "")
    mongodb_db = os.getenv("MONGODB_DB", "ac_reserva")
    jwt_secret = os.getenv("JWT_SECRET", "")
    allowed_origins = {
        value.strip().rstrip("/")
        for value in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    timezone = "America/Sao_Paulo"

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.mongodb_uri and cls.jwt_secret)

    @classmethod
    def missing_required_variables(cls) -> list[str]:
        missing = []
        if not cls.mongodb_uri:
            missing.append("MONGODB_URI")
        if not cls.jwt_secret:
            missing.append("JWT_SECRET")
        return missing

    @classmethod
    def configuration_message(cls) -> str:
        missing = cls.missing_required_variables()
        if not missing:
            return ""
        names = " e ".join(missing)
        return f"A API ainda não foi configurada. Defina {names} nas variáveis de ambiente da Vercel e faça um novo deploy."
