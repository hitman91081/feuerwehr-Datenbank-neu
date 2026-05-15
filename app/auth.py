import bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, UserRole
import os

SECRET_KEY = os.getenv("SECRET_KEY", "feuerwehr-super-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

security = HTTPBearer(auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht authentifiziert")
    
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Token")
    
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Token")
    
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzer nicht gefunden")
    
    return user

def require_role(allowed_roles: list[UserRole]):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Berechtigung")
        return current_user
    return role_checker

require_admin = require_role([UserRole.ADMIN])
require_verwaltung = require_role([UserRole.ADMIN, UserRole.VERWALTUNG])
require_erweitert = require_role([UserRole.ADMIN, UserRole.VERWALTUNG, UserRole.ERWEITERT])
require_any_user = require_role([UserRole.ADMIN, UserRole.VERWALTUNG, UserRole.ERWEITERT, UserRole.STANDARD])

def create_default_admin(db: Session):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if not admin:
        admin_user = User(
            username="admin",
            full_name="Administrator",
            email="admin@feuerwehr.local",
            hashed_password=get_password_hash("admin"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print("✅ Default-Admin erstellt: admin / admin")

def create_default_standard_user(db: Session):
    standard = db.query(User).filter(User.username == "standard").first()
    if not standard:
        standard_user = User(
            username="standard",
            full_name="Standardnutzer",
            email="standard@feuerwehr.local",
            hashed_password=get_password_hash("standard"),
            role=UserRole.STANDARD,
            is_active=True
        )
        db.add(standard_user)
        db.commit()
        print("✅ Default-Standardnutzer erstellt: standard / standard")
