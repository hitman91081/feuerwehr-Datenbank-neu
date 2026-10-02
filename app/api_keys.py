import hashlib
import json
import secrets
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiAuditLog, ApiClient


SUPPORTED_API_SCOPES = {"objects:read", "objects:write"}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> Tuple[str, str, str]:
    raw_key = "fwi_" + secrets.token_urlsafe(32)
    return raw_key, raw_key[:12], hash_api_key(raw_key)


def normalize_api_scopes(scopes: List[str]) -> List[str]:
    normalized = sorted({scope.strip() for scope in scopes if scope and scope.strip()})
    invalid = [scope for scope in normalized if scope not in SUPPORTED_API_SCOPES]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail="Unbekannte API-Berechtigung: " + ", ".join(invalid)
        )
    if not normalized:
        raise HTTPException(status_code=422, detail="Mindestens eine API-Berechtigung ist erforderlich.")
    return normalized


def client_scope_list(client: ApiClient) -> List[str]:
    return [scope for scope in (client.scopes or "").split(",") if scope]


def get_api_client(
    api_key: Optional[str] = Depends(api_key_header),
    db: Session = Depends(get_db)
) -> ApiClient:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API-Schlüssel fehlt.")
    client = db.query(ApiClient).filter(ApiClient.key_hash == hash_api_key(api_key)).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API-Schlüssel ist ungültig oder widerrufen.")
    client.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(client)
    return client


def require_api_scope(required_scope: str):
    def scope_dependency(client: ApiClient = Depends(get_api_client)) -> ApiClient:
        if required_scope not in client_scope_list(client):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Dem API-Schlüssel fehlt die Berechtigung {required_scope}."
            )
        return client
    return scope_dependency


def add_api_audit(
    db: Session,
    client: ApiClient,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None
) -> None:
    db.add(ApiAuditLog(
        client_id=client.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=json.dumps(details, ensure_ascii=False) if details else None
    ))
    db.commit()
