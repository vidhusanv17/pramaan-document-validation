import hashlib
import os
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException

from .db import get_db
from .models import User

SECRET = os.getenv("PRAMAAN_JWT_SECRET", "pramaan-demo-secret-change-me-before-deploying-0123456789")
ALGO = "HS256"


def hash_pw(p: str) -> str:
    return hashlib.sha256(("pramaan::" + p).encode()).hexdigest()


def create_token(user: User) -> str:
    return jwt.encode({"sub": user.username, "uid": user.id, "role": user.role, "exp": datetime.utcnow() + timedelta(hours=12)}, SECRET, algorithm=ALGO)


def get_current_user(authorization: str = Header(None), db=Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        data = jwt.decode(authorization.split(" ", 1)[1], SECRET, algorithms=[ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")
    user = db.get(User, data.get("uid"))
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


def require_roles(*roles):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role != "ADMIN" and user.role not in roles:
            raise HTTPException(403, f"Role {user.role} is not authorised (needs {', '.join(roles)})")
        return user
    return dep
