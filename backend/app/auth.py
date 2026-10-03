import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

SECRET_KEY = os.environ.get("SECRET_KEY", "stroyka-dev-secret")
ALGORITHM = "HS256"
EXPIRE_DAYS = 30

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


class Me(BaseModel):
    id: int
    company_id: int
    login: str
    name: str
    role: str


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user.id), "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> Me:
    """Пользователь берётся из базы на каждый запрос, а не из токена:
    токен живёт 30 дней, а сотрудника за это время могут уволить."""
    if not creds:
        raise HTTPException(401, "Не авторизован")
    try:
        data = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(data["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Токен недействителен")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "Пользователь не найден или отключён")
    return Me(id=user.id, company_id=user.company_id, login=user.login,
              name=user.name, role=user.role)


# Какие роли могут менять данные в разделе. Смотреть могут все, кто вошёл:
# в строительной компании закрытых друг от друга разделов почти нет,
# а вот править деньги прораб не должен.
WRITE_ROLES = {
    "sites":     {"director", "pto"},
    "tasks":     {"director", "pto", "foreman", "surveyor", "mechanic", "hr", "camp", "accountant"},
    "employees": {"director", "hr"},
    "camp":      {"director", "hr", "camp"},
    "equipment": {"director", "mechanic", "pto"},
    "finance":   {"director", "accountant", "pto"},
    "documents": {"director", "pto", "accountant", "hr"},
    "settings":  {"director"},
}


def require_write(section: str):
    def dep(user: Me = Depends(get_current_user)) -> Me:
        if user.role not in WRITE_ROLES.get(section, {"director"}):
            raise HTTPException(403, "Ваша роль не может менять этот раздел")
        return user
    return dep
