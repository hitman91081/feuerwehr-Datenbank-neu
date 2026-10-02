import os
import shutil
import uuid
import json
import zipfile
import tempfile
import io
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, inspect as sqlalchemy_inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import get_db, engine, Base
from app.models import (
    User, UserRole, ObjectType, Manufacturer, Supplier, Location, InventoryObject,
    ObjectImage, Maintenance, Repair, Document, DocumentLabel, QRCode, ObjectStatus,
    InspectionTemplate, Inspection, InspectionImage,
    Message, MessageImage, MessageHistory, MessageType, MessageAction, MessagePriority, MessageStatus,
    ApiClient, ApiAuditLog
)
from app.schemas import (
    Token, UserLogin, UserCreate, UserResponse, UserUpdate,
    ObjectTypeCreate, ObjectTypeResponse, ManufacturerCreate, ManufacturerResponse,
    SupplierCreate, SupplierResponse,
    LocationCreate, LocationResponse, InventoryObjectCreate, InventoryObjectUpdate,
    InventoryObjectPublicResponse, InventoryObjectFullResponse,
    MaintenanceCreate, MaintenanceResponse, RepairCreate, RepairResponse,
    DocumentResponse, DocumentLabelCreate, DocumentLabelResponse, DocumentUpdate,
    SearchResult, QRCodeResponse, ObjectImageResponse,
    InspectionTemplateCreate, InspectionTemplateResponse, InspectionCreate, InspectionResponse,
    InspectionImageResponse,
    InspectionCenterResponse, InspectionDueItem,
    MessageCreate, MessageStatusUpdate, MessageVisibilityUpdate, MessageCommentCreate, MessageArchiveCreate,
    MessageResponse, MessageImageResponse, MessageHistoryResponse,
    ApiClientCreate, ApiClientResponse, ApiClientCreatedResponse,
    ExternalObjectCreate, ExternalObjectResponse, ExternalObjectListResponse,
    BulkObjectCreateRequest, BulkObjectPreviewItem, BulkObjectPreviewResponse, BulkObjectCreateResponse
)
from app.auth import (
    verify_password, create_access_token, get_current_user,
    require_admin, require_verwaltung, require_erweitert, require_any_user,
    get_password_hash, create_default_admin, create_default_standard_user
)
from app.api_keys import (
    add_api_audit, client_scope_list, generate_api_key, normalize_api_scopes,
    require_api_scope
)

# QR Code
import qrcode
from PIL import Image, ImageDraw, ImageFont

# --- FastAPI App ---
app = FastAPI(title="Feuerwehr Inventar", version="2.0.0")

# Statische Dateien
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Datenbanktabellen erstellen
Base.metadata.create_all(bind=engine)

# Kleine, abwärtskompatible Migration für bestehende Installationen ohne Alembic.
# Die neue Bildtabelle wird bereits durch create_all angelegt; bestehende Tabellen
# benötigen nur die zusätzliche Spalte für den tatsächlich eingetragenen Prüfer.
inspection_columns = {column["name"] for column in sqlalchemy_inspect(engine).get_columns("inspections")}
if "inspector_name" not in inspection_columns:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE inspections ADD COLUMN inspector_name VARCHAR"))
        connection.execute(text(
            "UPDATE inspections SET inspector_name = "
            "(SELECT full_name FROM users WHERE users.id = inspections.inspected_by_id) "
            "WHERE inspector_name IS NULL"
        ))
if "maintenance_id" not in inspection_columns:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE inspections ADD COLUMN maintenance_id INTEGER"))

inventory_object_columns = {column["name"] for column in sqlalchemy_inspect(engine).get_columns("inventory_objects")}
with engine.begin() as connection:
    if "inspection_required" not in inventory_object_columns:
        connection.execute(text(
            "ALTER TABLE inventory_objects ADD COLUMN inspection_required BOOLEAN NOT NULL DEFAULT 1"
        ))
    if "standard_inspection_enabled" not in inventory_object_columns:
        connection.execute(text(
            "ALTER TABLE inventory_objects ADD COLUMN standard_inspection_enabled BOOLEAN NOT NULL DEFAULT 0"
        ))
    if "standard_inspection_template_id" not in inventory_object_columns:
        connection.execute(text(
            "ALTER TABLE inventory_objects ADD COLUMN standard_inspection_template_id INTEGER"
        ))
    if "supplier_id" not in inventory_object_columns:
        connection.execute(text(
            "ALTER TABLE inventory_objects ADD COLUMN supplier_id INTEGER"
        ))

maintenance_columns = {column["name"] for column in sqlalchemy_inspect(engine).get_columns("maintenances")}
if "description" not in maintenance_columns:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE maintenances ADD COLUMN description VARCHAR"))
        connection.execute(text(
            "UPDATE maintenances SET description = "
            "CASE WHEN notes IS NOT NULL AND TRIM(notes) <> '' THEN notes "
            "ELSE 'Allgemeine Prüfung / Wartung' END "
            "WHERE description IS NULL OR TRIM(description) = ''"
        ))

inspection_template_columns = {column["name"] for column in sqlalchemy_inspect(engine).get_columns("inspection_templates")}
if "default_interval_days" not in inspection_template_columns:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE inspection_templates ADD COLUMN default_interval_days INTEGER"))
        connection.execute(text(
            "UPDATE inspection_templates SET default_interval_days = CASE "
            "WHEN LOWER(name) LIKE '%täglich%' THEN 1 "
            "WHEN LOWER(name) LIKE '%monatlich%' THEN 30 "
            "WHEN LOWER(name) LIKE '%halbjährlich%' THEN 180 "
            "WHEN LOWER(name) LIKE '%jährlich%' THEN 365 "
            "ELSE NULL END WHERE default_interval_days IS NULL"
        ))

message_columns = {column["name"] for column in sqlalchemy_inspect(engine).get_columns("messages")}
with engine.begin() as connection:
    if "action_comment" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN action_comment TEXT"))
    if "is_visible_to_standard" not in message_columns:
        connection.execute(text(
            "ALTER TABLE messages ADD COLUMN is_visible_to_standard BOOLEAN NOT NULL DEFAULT 1"
        ))
    if "inventory_object_id" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN inventory_object_id INTEGER"))
    if "is_archived" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
    if "archive_reason" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN archive_reason VARCHAR"))
    if "archived_at" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN archived_at DATETIME"))
    if "archived_by_name" not in message_columns:
        connection.execute(text("ALTER TABLE messages ADD COLUMN archived_by_name VARCHAR"))
    connection.execute(text(
        "UPDATE messages SET inventory_object_id = "
        "(SELECT inventory_objects.id FROM inventory_objects "
        " WHERE UPPER(TRIM(inventory_objects.object_number)) = UPPER(TRIM(messages.device_id)) LIMIT 1) "
        "WHERE inventory_object_id IS NULL AND device_id IS NOT NULL"
    ))
    connection.execute(text(
        "UPDATE messages SET inventory_object_id = "
        "(SELECT inventory_objects.id FROM inventory_objects "
        " WHERE REPLACE(REPLACE(UPPER(TRIM(inventory_objects.object_number)), 'FFW-', ''), 'FW-', '') = "
        "       REPLACE(REPLACE(UPPER(TRIM(messages.device_id)), 'FFW-', ''), 'FW-', '') LIMIT 1) "
        "WHERE inventory_object_id IS NULL AND UPPER(TRIM(device_id)) LIKE '%W-%'"
    ))

# Dokumente können ab Version 41 auch ohne Inventarobjekt in der zentralen
# Sammlung liegen und erhalten optional ein frei verwaltbares Label.
document_column_info = {column["name"]: column for column in sqlalchemy_inspect(engine).get_columns("documents")}
if engine.dialect.name == "sqlite" and (
    "label_id" not in document_column_info or not document_column_info["object_id"].get("nullable", True)
):
    has_label_id = "label_id" in document_column_info
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS documents_migration_v41"))
        connection.execute(text(
            "CREATE TABLE documents_migration_v41 ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "object_id INTEGER NULL, "
            "label_id INTEGER NULL, "
            "filename VARCHAR NOT NULL, "
            "original_name VARCHAR NOT NULL, "
            "file_type VARCHAR, "
            "is_public BOOLEAN DEFAULT 1, "
            "uploaded_at DATETIME, "
            "uploaded_by_id INTEGER, "
            "FOREIGN KEY(object_id) REFERENCES inventory_objects (id), "
            "FOREIGN KEY(label_id) REFERENCES document_labels (id), "
            "FOREIGN KEY(uploaded_by_id) REFERENCES users (id))"
        ))
        label_select = "label_id" if has_label_id else "NULL"
        connection.execute(text(
            "INSERT INTO documents_migration_v41 "
            "(id, object_id, label_id, filename, original_name, file_type, is_public, uploaded_at, uploaded_by_id) "
            f"SELECT id, object_id, {label_select}, filename, original_name, file_type, is_public, uploaded_at, uploaded_by_id FROM documents"
        ))
        connection.execute(text("DROP TABLE documents"))
        connection.execute(text("ALTER TABLE documents_migration_v41 RENAME TO documents"))
elif "label_id" not in document_column_info:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE documents ADD COLUMN label_id INTEGER"))

# Upload-Verzeichnisse sicherstellen
for d in ["uploads/images", "uploads/documents", "uploads/qrcodes", "uploads/inspection_images", "uploads/message_images"]:
    os.makedirs(d, exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Default-Admin erstellen (beim ersten Start)
@app.on_event("startup")
def startup():
    db = next(get_db())
    create_default_admin(db)
    create_default_standard_user(db)
    # Für bestehende Meldungen einen nachvollziehbaren Startpunkt im Verlauf anlegen.
    messages_without_history = db.query(Message).filter(~Message.history.any()).all()
    for message in messages_without_history:
        db.add(MessageHistory(
            message_id=message.id,
            entry_type="status",
            status=message.status.value if message.status else MessageStatus.OFFEN.value,
            details="Bestehender Vorgang übernommen; frühere Statusänderungen wurden noch nicht protokolliert",
            author_name=message.reported_by_name or message.created_by_name,
            created_at=message.created_at or datetime.utcnow()
        ))
    if messages_without_history:
        db.commit()
    # Standard-Stammdaten anlegen (fehlende Typen nachlegen)
    default_types = [
        "Fahrzeug",
        "Schutzkleidung und Schutzgeräte",
        "Löschgeräte",
        "Schläuche, Armaturen und Zubehör",
        "Rettungsgeräte",
        "Sanitäts- und Wiederbelebungsgeräte",
        "Beleuchtungs-, Signal- und Fernmeldegeräte",
        "Arbeitsgeräte",
        "Handwerkzeuge und Messgeräte",
        "Sondergeräte",
        "Sonstiges",
        "Zeitschriften",
        "Dokumente",
        "Inventar Fest",
        "Inventar Küche"
    ]
    existing_types = {t.name for t in db.query(ObjectType).all()}
    for name in default_types:
        if name not in existing_types:
            db.add(ObjectType(name=name))
    if not db.query(Location).first():
        db.add(Location(name="Gerätehaus", location_type="Gerätehaus"))

    default_document_labels = [
        "Bedienungsanleitung", "Datenblatt", "Lieferschein", "Angebot",
        "Reparaturbericht", "Sicherheitshinweis", "Bedienerhinweis",
        "Zeitschrift", "Prüfanweisung", "Normenwerk"
    ]
    existing_document_labels = {label.name.casefold() for label in db.query(DocumentLabel).all()}
    for label_name in default_document_labels:
        if label_name.casefold() not in existing_document_labels:
            db.add(DocumentLabel(name=label_name, is_default=True))
    
    # Standard-Prüfkarten anlegen
    if not db.query(InspectionTemplate).first():
        import json
        templates = [
            {
                "name": "Feuerlöscher – jährliche Prüfung",
                "description": "Jährliche Prüfung von Feuerlöschern nach DIN 14406",
                "default_interval_days": 365,
                "fields": [
                    {"label": "Visueller Zustand (Rost, Beschädigungen)", "type": "checkbox", "required": True},
                    {"label": "Manometer im grünen Bereich", "type": "checkbox", "required": True},
                    {"label": "Sicherheitsnadel vorhanden", "type": "checkbox", "required": True},
                    {"label": "Bedienungsanleitung lesbar", "type": "checkbox", "required": True},
                    {"label": "Standort erkennbar", "type": "checkbox", "required": True},
                    {"label": "Gewicht (kg)", "type": "number", "required": False},
                    {"label": "Druck (bar)", "type": "number", "required": False},
                    {"label": "Bemerkungen", "type": "textarea", "required": False}
                ]
            },
            {
                "name": "Druckschlauch – halbjährliche Prüfung",
                "description": "Prüfung von Druckschläuchen nach DIN 14811",
                "default_interval_days": 180,
                "fields": [
                    {"label": "Visueller Zustand (Risse, Abrieb)", "type": "checkbox", "required": True},
                    {"label": "Kupplungen beschädigt", "type": "checkbox", "required": True},
                    {"label": "Dichtigkeitstest bestanden", "type": "checkbox", "required": True},
                    {"label": "Länge (m)", "type": "number", "required": False},
                    {"label": "Bemerkungen", "type": "textarea", "required": False}
                ]
            },
            {
                "name": "Atemschutzgerät – monatliche Prüfung",
                "description": "Monatliche Funktionsprüfung des Atemschutzgeräts",
                "default_interval_days": 30,
                "fields": [
                    {"label": "Flaschendruck > 180 bar", "type": "checkbox", "required": True},
                    {"label": "Warnsignal funktioniert", "type": "checkbox", "required": True},
                    {"label": "Maske undichtigkeitsfrei", "type": "checkbox", "required": True},
                    {"label": "Tragegurt beschädigt", "type": "checkbox", "required": True},
                    {"label": "Flaschendruck (bar)", "type": "number", "required": False},
                    {"label": "Bemerkungen", "type": "textarea", "required": False}
                ]
            },
            {
                "name": "Fahrzeug – tägliche Kontrolle",
                "description": "Tägliche Fahrzeugkontrolle vor Dienstbeginn",
                "default_interval_days": 1,
                "allow_standard_users": True,
                "fields": [
                    {"label": "Kraftstoffstand ausreichend", "type": "checkbox", "required": True},
                    {"label": "Motorölstand OK", "type": "checkbox", "required": True},
                    {"label": "Kühlmittelstand OK", "type": "checkbox", "required": True},
                    {"label": "Beleuchtung funktionsfähig", "type": "checkbox", "required": True},
                    {"label": "Reifendruck OK", "type": "checkbox", "required": True},
                    {"label": "Warnblinkanlage funktioniert", "type": "checkbox", "required": True},
                    {"label": "Kilometerstand", "type": "number", "required": False},
                    {"label": "Bemerkungen", "type": "textarea", "required": False}
                ]
            },
            {
                "name": "Tauchpumpe – jährliche Prüfung",
                "description": "Jährliche Prüfung der Tauchpumpe",
                "default_interval_days": 365,
                "fields": [
                    {"label": "Visueller Zustand", "type": "checkbox", "required": True},
                    {"label": "Motor läuft an", "type": "checkbox", "required": True},
                    {"label": "Förderleistung OK", "type": "checkbox", "required": True},
                    {"label": "Dichtungen intakt", "type": "checkbox", "required": True},
                    {"label": "Bemerkungen", "type": "textarea", "required": False}
                ]
            }
        ]
        for t in templates:
            db.add(InspectionTemplate(
                name=t["name"],
                description=t["description"],
                fields=json.dumps(t["fields"]),
                default_interval_days=t.get("default_interval_days"),
                allow_standard_users=t.get("allow_standard_users", False)
            ))
    db.commit()

# --- Hilfsfunktionen ---

def generate_object_number(db: Session) -> str:
    # Finde die höchste ID und generiere daraus eine Nummer
    last = db.query(InventoryObject).order_by(InventoryObject.id.desc()).first()
    next_id = (last.id + 1) if last else 1
    return f"FFW-{next_id:05d}"

def generate_qr_code(object_number: str) -> str:
    url = f"{BASE_URL}/?q={object_number}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filename = f"qr_{object_number}.png"
    filepath = f"uploads/qrcodes/{filename}"
    img.save(filepath)
    return filename

def generate_sticker(object_number: str, designation: str) -> str:
    # Erstelle ein druckbares Bild (Aufkleber 50x25mm bei 300dpi ~ 590x295px)
    width, height = 590, 295
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    # Versuche eine Schrift zu laden
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        font_medium = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large
    
    # QR-Code laden und einfügen
    qr_path = f"uploads/qrcodes/qr_{object_number}.png"
    if os.path.exists(qr_path):
        qr_img = Image.open(qr_path)
        qr_img = qr_img.resize((240, 240))
        img.paste(qr_img, (20, 20))
    
    # Text
    draw.text((280, 40), designation, fill="black", font=font_large)
    draw.text((280, 100), f"ID: {object_number}", fill="black", font=font_medium)
    draw.text((280, 150), "Scannen für Details", fill="gray", font=font_small)
    
    # Rahmen
    draw.rectangle([0, 0, width-1, height-1], outline="black", width=3)
    
    filename = f"sticker_{object_number}.png"
    filepath = f"uploads/qrcodes/{filename}"
    img.save(filepath)
    return filename

def save_upload(file: UploadFile, directory: str) -> str:
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(directory, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return filename

def determine_file_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        return "image"
    elif ext == ".pdf":
        return "pdf"
    elif ext in [".txt", ".md"]:
        return "text"
    return "other"


def build_document_response(document: Document) -> DocumentResponse:
    obj = document.inventory_object
    return DocumentResponse(
        id=document.id,
        object_id=document.object_id,
        object_number=obj.object_number if obj else None,
        object_designation=obj.designation if obj else None,
        label_id=document.label_id,
        label_name=document.label.name if document.label else None,
        filename=document.filename,
        original_name=document.original_name,
        file_type=document.file_type,
        is_public=bool(document.is_public),
        uploaded_at=document.uploaded_at,
        uploaded_by_name=document.uploaded_by.full_name if document.uploaded_by else None,
    )

def save_validated_image(file: UploadFile, upload_directory: str) -> str:
    """Validiert und speichert ein Bild mit einer sicheren Dateiendung."""
    data = file.file.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Das Bild darf höchstens 12 MB groß sein")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = (image.format or "").upper()
    except Exception:
        raise HTTPException(status_code=400, detail="Die Datei ist kein gültiges Bild")
    extension = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif"
    }.get(image_format)
    if not extension:
        raise HTTPException(status_code=400, detail="Unterstützt werden JPG, PNG, WebP und GIF")
    filename = f"{uuid.uuid4().hex}{extension}"
    with open(os.path.join(upload_directory, filename), "wb") as destination:
        destination.write(data)
    return filename

def save_inspection_image(file: UploadFile) -> str:
    return save_validated_image(file, "uploads/inspection_images")

def save_message_image(file: UploadFile) -> str:
    return save_validated_image(file, "uploads/message_images")

def build_inspection_response(inspection: Inspection) -> InspectionResponse:
    registered_name = inspection.inspected_by.full_name if inspection.inspected_by else None
    return InspectionResponse(
        id=inspection.id,
        object_id=inspection.object_id,
        template_id=inspection.template_id,
        template_name=inspection.template.name if inspection.template else None,
        maintenance_id=inspection.maintenance_id,
        maintenance_description=inspection.maintenance.description if inspection.maintenance else None,
        inspected_by_name=registered_name,
        inspector_name=inspection.inspector_name or registered_name,
        inspected_at=inspection.inspected_at,
        results=inspection.results,
        next_inspection_date=inspection.next_inspection_date,
        notes=inspection.notes,
        images=[InspectionImageResponse.model_validate(image) for image in inspection.images]
    )

def validate_standard_inspection_assignment(
    db: Session,
    enabled: bool,
    template_id: Optional[int]
) -> Optional[int]:
    """Validiert die ausschließlich für Standardnutzer bestimmte Objekt-Prüfkarte."""
    if not enabled:
        return None
    if not template_id:
        raise HTTPException(
            status_code=422,
            detail="Wenn Standardnutzer Prüfungen durchführen dürfen, muss eine Prüfkarte ausgewählt werden."
        )
    template = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=422, detail="Die ausgewählte Prüfkarte existiert nicht mehr.")
    return template.id

def standard_user_can_access_inspection(obj: InventoryObject, template_id: Optional[int] = None) -> bool:
    if not obj.inspection_required or not obj.standard_inspection_enabled or not obj.standard_inspection_template_id:
        return False
    return template_id is None or obj.standard_inspection_template_id == template_id


def maintenance_due_date(
    acquisition_date: Optional[str],
    interval_days: int,
    explicit_due_date: Optional[str] = None
) -> Optional[str]:
    """Ermittelt den ersten Termin einer Prüffrist und validiert Datumsangaben."""
    if explicit_due_date:
        try:
            return date.fromisoformat(explicit_due_date).isoformat()
        except ValueError:
            raise HTTPException(status_code=422, detail="Ein nächster Prüftermin ist ungültig.")
    if not acquisition_date:
        return None
    try:
        return (date.fromisoformat(acquisition_date) + timedelta(days=interval_days)).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="Das Anschaffungsdatum ist ungültig.")


def create_maintenance_entries(
    db: Session,
    obj: InventoryObject,
    schedules: List[MaintenanceCreate],
    acquisition_date: Optional[str]
) -> None:
    for schedule in schedules:
        description = schedule.description.strip()
        db.add(Maintenance(
            object_id=obj.id,
            description=description,
            interval_days=schedule.interval_days,
            last_maintenance_date=schedule.last_maintenance_date or acquisition_date,
            next_maintenance_date=maintenance_due_date(
                acquisition_date,
                schedule.interval_days,
                schedule.next_maintenance_date
            ),
            notes=schedule.notes
        ))


def sync_maintenance_entries(
    db: Session,
    obj: InventoryObject,
    schedules: List[MaintenanceCreate]
) -> None:
    """Synchronisiert maximal drei Fristen, ohne fremde Datensätze übernehmen zu können."""
    existing = {entry.id: entry for entry in obj.maintenances}
    retained_ids = set()
    for schedule in schedules:
        entry = None
        if schedule.id is not None:
            entry = existing.get(schedule.id)
            if entry is None:
                raise HTTPException(status_code=422, detail="Eine Prüffrist gehört nicht zu diesem Artikel.")
            retained_ids.add(entry.id)
        if entry is None:
            entry = Maintenance(object_id=obj.id)
            db.add(entry)
        entry.description = schedule.description.strip()
        entry.interval_days = schedule.interval_days
        entry.last_maintenance_date = schedule.last_maintenance_date or obj.acquisition_date
        entry.next_maintenance_date = maintenance_due_date(
            obj.acquisition_date,
            schedule.interval_days,
            schedule.next_maintenance_date
        )
        entry.notes = schedule.notes

    for entry_id, entry in existing.items():
        if entry_id not in retained_ids:
            db.delete(entry)

# --- Auth Endpoints ---

@app.post("/api/auth/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültige Anmeldedaten")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/auth/qr-login", response_model=Token)
def qr_login(db: Session = Depends(get_db)):
    """Schneller Login für Standardnutzer per QR-Code (z.B. im Gerätehaus ausgedruckt)"""
    user = db.query(User).filter(User.username == "standard").first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Standardnutzer nicht verfügbar")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=UserResponse)
def me(current_user: User = Depends(require_any_user)):
    return current_user

# --- User Management (nur Admin) ---

@app.get("/api/users", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(User).all()

@app.post("/api/users", response_model=UserResponse)
def create_user(data: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    username = data.username.strip()
    full_name = data.full_name.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Bitte einen Benutzernamen eingeben.")
    if not full_name:
        raise HTTPException(status_code=400, detail="Bitte einen Namen eingeben.")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Das Passwort muss mindestens 6 Zeichen lang sein.")
    if db.query(User).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(status_code=409, detail="Dieser Benutzername ist bereits vergeben.")
    user = User(
        username=username,
        full_name=full_name,
        email=data.email.strip() if data.email else None,
        hashed_password=get_password_hash(data.password),
        role=data.role,
        is_active=data.is_active
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dieser Benutzername ist bereits vergeben.")
    db.refresh(user)
    return user

@app.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    values = data.model_dump(exclude_unset=True)
    if "full_name" in values:
        values["full_name"] = (values["full_name"] or "").strip()
        if not values["full_name"]:
            raise HTTPException(status_code=400, detail="Bitte einen Namen eingeben.")
    if values.get("password") and len(values["password"]) < 6:
        raise HTTPException(status_code=400, detail="Das Passwort muss mindestens 6 Zeichen lang sein.")
    if "email" in values:
        values["email"] = values["email"].strip() if values["email"] else None
    for key, value in values.items():
        if key == "password" and value:
            setattr(user, "hashed_password", get_password_hash(value))
        else:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    db.delete(user)
    db.commit()
    return {"ok": True}


# --- API-Schlüssel (nur Administratoren) ---

def api_client_response(client: ApiClient, api_key: Optional[str] = None):
    response = {
        "id": client.id,
        "name": client.name,
        "key_prefix": client.key_prefix,
        "scopes": client_scope_list(client),
        "is_active": client.is_active,
        "created_at": client.created_at,
        "last_used_at": client.last_used_at,
    }
    if api_key is not None:
        response["api_key"] = api_key
    return response


@app.get("/api/admin/api-clients", response_model=List[ApiClientResponse])
def list_api_clients(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    clients = db.query(ApiClient).order_by(ApiClient.created_at.desc()).all()
    return [api_client_response(client) for client in clients]


@app.post("/api/admin/api-clients", response_model=ApiClientCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_client(
    data: ApiClientCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen für den API-Schlüssel eingeben.")
    scopes = normalize_api_scopes(data.scopes)
    raw_key, key_prefix, key_hash = generate_api_key()
    client = ApiClient(
        name=name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=",".join(scopes),
        created_by_id=admin.id,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return api_client_response(client, raw_key)


@app.delete("/api/admin/api-clients/{client_id}")
def revoke_api_client(
    client_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    client = db.query(ApiClient).filter(ApiClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="API-Schlüssel nicht gefunden.")
    client.is_active = False
    db.commit()
    return {"ok": True}

# --- Stammdaten ---

@app.get("/api/object-types", response_model=List[ObjectTypeResponse])
def list_object_types(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(ObjectType).all()

@app.post("/api/object-types", response_model=ObjectTypeResponse)
def create_object_type(data: ObjectTypeCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Bitte einen Namen für die Kategorie eingeben.")
    existing = db.query(ObjectType).filter(func.lower(ObjectType.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f'Die Kategorie „{existing.name}“ ist bereits vorhanden.')
    ot = ObjectType(name=name)
    db.add(ot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Die Kategorie „{name}“ ist bereits vorhanden.')
    db.refresh(ot)
    return ot

@app.get("/api/manufacturers", response_model=List[ManufacturerResponse])
def list_manufacturers(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(Manufacturer).all()

@app.post("/api/manufacturers", response_model=ManufacturerResponse)
def create_manufacturer(data: ManufacturerCreate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Bitte einen Herstellernamen eingeben.")
    existing = db.query(Manufacturer).filter(func.lower(Manufacturer.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f'Der Hersteller „{existing.name}“ ist bereits vorhanden.')
    m = Manufacturer(name=name)
    db.add(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Der Hersteller „{name}“ ist bereits vorhanden.')
    db.refresh(m)
    return m

@app.get("/api/suppliers", response_model=List[SupplierResponse])
def list_suppliers(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(Supplier).order_by(Supplier.name).all()

@app.post("/api/suppliers", response_model=SupplierResponse)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Bitte einen Lieferantennamen eingeben.")
    existing = db.query(Supplier).filter(func.lower(Supplier.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f'Der Lieferant „{existing.name}“ ist bereits vorhanden.')
    supplier = Supplier(name=name)
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Der Lieferant „{name}“ ist bereits vorhanden.')
    db.refresh(supplier)
    return supplier

@app.get("/api/locations", response_model=List[LocationResponse])
def list_locations(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    # Gibt alle Standorte zurück - Baumstruktur wird im Frontend aufgebaut
    all_locs = db.query(Location).order_by(Location.name).all()
    # Baumstruktur aufbauen: Nur Root-Elemente zurückgeben, Kinder sind über Relationship verfügbar
    root_locs = [loc for loc in all_locs if loc.parent_id is None]
    return root_locs

@app.get("/api/locations/all", response_model=List[LocationResponse])
def list_all_locations_flat(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    """Gibt ALLE Standorte als flache Liste zurück (für Dropdowns)"""
    return db.query(Location).order_by(Location.name).all()

@app.post("/api/locations", response_model=LocationResponse)
def create_location(data: LocationCreate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    name = data.name.strip()
    location_type = data.location_type.strip() or "Standort"
    if not name:
        raise HTTPException(status_code=400, detail="Bitte einen Namen für den Standort eingeben.")
    if data.parent_id is not None and not db.query(Location).filter(Location.id == data.parent_id).first():
        raise HTTPException(status_code=400, detail="Der ausgewählte übergeordnete Standort existiert nicht mehr.")

    duplicate_query = db.query(Location).filter(func.lower(Location.name) == name.lower())
    duplicate_query = duplicate_query.filter(
        Location.parent_id == data.parent_id if data.parent_id is not None else Location.parent_id.is_(None)
    )
    existing = duplicate_query.first()
    if existing:
        raise HTTPException(status_code=409, detail=f'Der Standort „{existing.name}“ ist an dieser Stelle bereits vorhanden.')

    loc = Location(name=name, location_type=location_type, parent_id=data.parent_id)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc

@app.delete("/api/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Standort nicht gefunden")

    location_ids = get_all_sub_location_ids(db, location_id)
    children_count = len(location_ids) - 1
    is_vehicle_location = bool(loc.linked_object_id) or loc.location_type.strip().lower() == "fahrzeug"
    objects_count = db.query(InventoryObject).filter(InventoryObject.location_id.in_(location_ids)).count()
    if objects_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f'Der Standort „{loc.name}“ kann nicht gelöscht werden: '
                f'Im Standort oder seinen Unterstandorten befinden sich noch {objects_count} Inventarartikel.'
            )
        )
    if children_count > 0 and not is_vehicle_location:
        raise HTTPException(
            status_code=409,
            detail="Standort hat untergeordnete Standorte und kann nicht gelöscht werden."
        )

    # Bei Fahrzeug-Standorten darf der nachweislich leere Teilbaum gemeinsam
    # entfernt werden. Das verknüpfte Inventar-Fahrzeug selbst bleibt bestehen.
    db.query(Location).filter(Location.id.in_(location_ids)).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted_locations": len(location_ids), "vehicle_location": is_vehicle_location}

# --- Standort-Objekte (rekursiv) ---

def get_all_sub_location_ids(db: Session, location_id: int) -> List[int]:
    """Gibt alle Location-IDs inkl. Unterlocations zurück"""
    ids = [location_id]
    children = db.query(Location).filter(Location.parent_id == location_id).all()
    for child in children:
        ids.extend(get_all_sub_location_ids(db, child.id))
    return ids


def get_location_path(location: Optional[Location]) -> Optional[str]:
    if not location:
        return None
    parts = []
    visited = set()
    current = location
    while current and current.id not in visited:
        visited.add(current.id)
        parts.insert(0, current.name)
        current = current.parent
    return " > ".join(parts)


def find_location_by_path(db: Session, path: str) -> Optional[Location]:
    normalized = " > ".join(part.strip() for part in path.split(">") if part.strip()).casefold()
    if not normalized:
        return None
    return next(
        (location for location in db.query(Location).all()
         if (get_location_path(location) or "").casefold() == normalized),
        None
    )

@app.get("/api/locations/{location_id}/objects", response_model=List[SearchResult])
def get_objects_by_location(location_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Standort nicht gefunden")
    all_loc_ids = get_all_sub_location_ids(db, location_id)
    objects = db.query(InventoryObject).filter(InventoryObject.location_id.in_(all_loc_ids)).order_by(InventoryObject.designation).all()
    result = []
    for obj in objects:
        result.append(SearchResult(
            id=obj.id,
            designation=obj.designation,
            object_number=obj.object_number,
            object_type=obj.object_type.name if obj.object_type else None,
            status=obj.status.value if obj.status else None,
            title_image=obj.title_image,
            location_name=obj.location.name if obj.location else None,
            location_id=obj.location_id
        ))
    return result

# --- Objekte ---

@app.get("/api/objects/search", response_model=List[SearchResult])
def search_objects(q: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    query = db.query(InventoryObject)
    if q:
        query = query.filter(
            or_(
                InventoryObject.designation.ilike(f"%{q}%"),
                InventoryObject.object_number.ilike(f"%{q}%"),
                InventoryObject.serial_number.ilike(f"%{q}%")
            )
        )
    objects = query.order_by(InventoryObject.designation).all()
    
    result = []
    for obj in objects:
        result.append(SearchResult(
            id=obj.id,
            designation=obj.designation,
            object_number=obj.object_number,
            object_type=obj.object_type.name if obj.object_type else None,
            status=obj.status.value if obj.status else None,
            title_image=obj.title_image,
            location_name=obj.location.name if obj.location else None,
            location_id=obj.location_id
        ))
    return result

@app.get("/api/objects", response_model=List[SearchResult])
def list_objects(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return search_objects(q=None, db=db, user=user)

@app.get("/api/objects/browse", response_model=List[SearchResult])
def browse_objects(
    object_type_id: Optional[int] = None,
    location_id: Optional[int] = None,
    manufacturer_id: Optional[int] = None,
    status: Optional[ObjectStatus] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    query = db.query(InventoryObject)
    if object_type_id:
        query = query.filter(InventoryObject.object_type_id == object_type_id)
    if manufacturer_id:
        query = query.filter(InventoryObject.manufacturer_id == manufacturer_id)
    if status:
        query = query.filter(InventoryObject.status == status)
    if location_id:
        loc_ids = get_all_sub_location_ids(db, location_id)
        query = query.filter(InventoryObject.location_id.in_(loc_ids))
    if q:
        query = query.filter(
            or_(
                InventoryObject.designation.ilike(f"%{q}%"),
                InventoryObject.object_number.ilike(f"%{q}%"),
                InventoryObject.serial_number.ilike(f"%{q}%")
            )
        )
    objects = query.order_by(InventoryObject.designation).all()
    result = []
    for obj in objects:
        result.append(SearchResult(
            id=obj.id,
            designation=obj.designation,
            object_number=obj.object_number,
            object_type=obj.object_type.name if obj.object_type else None,
            status=obj.status.value if obj.status else None,
            title_image=obj.title_image,
            location_name=obj.location.name if obj.location else None,
            location_id=obj.location_id
        ))
    return result

@app.get("/api/objects/resolve-code", response_model=SearchResult)
def resolve_object_code(
    q: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    """Resolve a scanned QR payload or serial number without fuzzy matches."""
    clean_value = "".join(char for char in q if ord(char) >= 32 and ord(char) != 127).strip()
    if not clean_value:
        raise HTTPException(status_code=404, detail="Kein Artikel zu diesem Code gefunden")

    object_number_match = re.search(r"FFW-\d+", clean_value, re.IGNORECASE)
    object_number = object_number_match.group(0).upper() if object_number_match else None
    obj = None
    if object_number:
        obj = db.query(InventoryObject).filter(
            func.lower(InventoryObject.object_number) == object_number.lower()
        ).first()
    if not obj:
        obj = db.query(InventoryObject).filter(
            func.lower(func.trim(InventoryObject.serial_number)) == clean_value.lower()
        ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Kein Artikel zu diesem Code gefunden")

    return SearchResult(
        id=obj.id,
        designation=obj.designation,
        object_number=obj.object_number,
        object_type=obj.object_type.name if obj.object_type else None,
        status=obj.status.value if obj.status else None,
        title_image=obj.title_image,
        location_name=obj.location.name if obj.location else None,
        location_id=obj.location_id
    )


def build_external_object_response(obj: InventoryObject) -> ExternalObjectResponse:
    return ExternalObjectResponse(
        id=obj.id,
        object_number=obj.object_number,
        designation=obj.designation,
        serial_number=obj.serial_number,
        object_type=obj.object_type.name if obj.object_type else None,
        manufacturer=obj.manufacturer.name if obj.manufacturer else None,
        supplier=obj.supplier.name if obj.supplier else None,
        location=get_location_path(obj.location),
        status=obj.status.value if obj.status else ObjectStatus.IN_BENUTZUNG.value,
        acquisition_date=obj.acquisition_date,
        info_text=obj.info_text,
        usage_hints=obj.usage_hints,
        inspection_required=bool(obj.inspection_required),
        maintenance_schedules=[MaintenanceResponse.model_validate(item) for item in obj.maintenances],
        inspection_count=len(obj.inspections),
        open_message_count=sum(1 for message in obj.messages if not message.is_archived),
    )


def resolve_external_object(db: Session, identifier: str) -> Optional[InventoryObject]:
    value = identifier.strip()
    obj = db.query(InventoryObject).filter(
        func.lower(InventoryObject.object_number) == value.lower()
    ).first()
    if obj:
        return obj
    obj = db.query(InventoryObject).filter(
        func.lower(func.trim(InventoryObject.serial_number)) == value.lower()
    ).first()
    if obj:
        return obj
    if value.isdigit():
        return db.query(InventoryObject).filter(InventoryObject.id == int(value)).first()
    return None


def resolve_named_master_data(
    db: Session,
    model,
    value: Optional[str],
    label: str,
    create_missing: bool
):
    if not value or not value.strip():
        return None
    name = value.strip()
    item = db.query(model).filter(func.lower(model.name) == name.lower()).first()
    if item:
        return item
    if not create_missing:
        raise HTTPException(
            status_code=422,
            detail=f'{label} „{name}“ ist nicht vorhanden. Alternativ create_missing_master_data aktivieren.'
        )
    item = model(name=name)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        item = db.query(model).filter(func.lower(model.name) == name.lower()).first()
        if item:
            return item
        raise
    db.refresh(item)
    return item


def ensure_serial_number_available(db: Session, serial_number: Optional[str]) -> Optional[str]:
    serial = serial_number.strip() if serial_number else None
    if not serial:
        return None
    existing = db.query(InventoryObject).filter(
        func.lower(func.trim(InventoryObject.serial_number)) == serial.lower()
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f'Seriennummer „{serial}“ ist bereits dem Objekt {existing.object_number} zugeordnet.'
        )
    return serial


def generated_bulk_serials(data: BulkObjectCreateRequest) -> List[Optional[str]]:
    if not data.generate_serial_numbers:
        return [None] * data.quantity
    return [
        f"{data.serial_prefix}{str(data.serial_start + index).zfill(data.serial_padding)}{data.serial_suffix}".strip()
        for index in range(data.quantity)
    ]


def validate_bulk_request(
    db: Session,
    data: BulkObjectCreateRequest,
    reject_existing_serials: bool = False
) -> tuple[List[Optional[str]], List[str]]:
    if not db.query(ObjectType).filter(ObjectType.id == data.object_type_id).first():
        raise HTTPException(status_code=422, detail="Die gewählte Kategorie existiert nicht mehr.")
    for model, item_id, label in (
        (Manufacturer, data.manufacturer_id, "Hersteller"),
        (Supplier, data.supplier_id, "Lieferant"),
        (Location, data.location_id, "Standort"),
    ):
        if item_id and not db.query(model).filter(model.id == item_id).first():
            raise HTTPException(status_code=422, detail=f"Der gewählte {label} existiert nicht mehr.")
    for schedule in data.maintenance_schedules:
        if not schedule.description.strip():
            raise HTTPException(status_code=422, detail="Jede Prüffrist benötigt eine Bezeichnung.")

    serials = generated_bulk_serials(data)
    nonempty_serials = [serial for serial in serials if serial]
    if len({serial.casefold() for serial in nonempty_serials}) != len(nonempty_serials):
        raise HTTPException(status_code=422, detail="Die erzeugten Seriennummern sind nicht eindeutig.")

    existing = []
    if nonempty_serials:
        normalized = [serial.lower() for serial in nonempty_serials]
        existing = db.query(InventoryObject).filter(
            func.lower(func.trim(InventoryObject.serial_number)).in_(normalized)
        ).all()
    if existing and reject_existing_serials:
        details = ", ".join(f"{item.serial_number} ({item.object_number})" for item in existing[:8])
        raise HTTPException(status_code=409, detail="Bereits vergebene Seriennummern: " + details)
    warnings = []
    if existing:
        warnings.append(
            f"{len(existing)} Seriennummer(n) sind bereits vergeben. Vor dem Anlegen muss der Nummernbereich geändert werden."
        )
    if not data.generate_serial_numbers:
        warnings.append("Die Objekte werden ohne Seriennummer angelegt.")
    return serials, warnings


@app.post("/api/objects/bulk/preview", response_model=BulkObjectPreviewResponse)
def preview_bulk_objects(
    data: BulkObjectCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    serials, warnings = validate_bulk_request(db, data)
    return BulkObjectPreviewResponse(
        count=data.quantity,
        items=[
            BulkObjectPreviewItem(
                position=index + 1,
                designation=data.designation.strip(),
                serial_number=serials[index],
            )
            for index in range(data.quantity)
        ],
        warnings=warnings,
    )


@app.post("/api/objects/bulk", response_model=BulkObjectCreateResponse, status_code=status.HTTP_201_CREATED)
def create_bulk_objects(
    data: BulkObjectCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    serials, _ = validate_bulk_request(db, data, reject_existing_serials=True)
    created = []
    for serial in serials:
        obj = create_object(
            InventoryObjectCreate(
                object_type_id=data.object_type_id,
                designation=data.designation.strip(),
                serial_number=serial,
                manufacturer_id=data.manufacturer_id,
                supplier_id=data.supplier_id,
                location_id=data.location_id,
                acquisition_date=data.acquisition_date,
                status=data.status,
                info_text=data.info_text,
                usage_hints=data.usage_hints,
                inspection_required=data.inspection_required,
                maintenance_schedules=data.maintenance_schedules if data.inspection_required else [],
            ),
            db=db,
            user=user,
        )
        created.append(SearchResult(
            id=obj.id,
            designation=obj.designation,
            object_number=obj.object_number,
            object_type=obj.object_type.name if obj.object_type else None,
            status=obj.status.value if obj.status else None,
            title_image=obj.title_image,
            location_name=obj.location.name if obj.location else None,
            location_id=obj.location_id,
        ))
    return BulkObjectCreateResponse(created_count=len(created), objects=created)


# --- Versionierte externe API (Authentifizierung über X-API-Key) ---

@app.get("/api/v1/meta")
def external_api_meta(
    db: Session = Depends(get_db),
    client: ApiClient = Depends(require_api_scope("objects:read"))
):
    locations = db.query(Location).order_by(Location.name).all()
    return {
        "api_version": "v1",
        "object_types": [item.name for item in db.query(ObjectType).order_by(ObjectType.name).all()],
        "manufacturers": [item.name for item in db.query(Manufacturer).order_by(Manufacturer.name).all()],
        "suppliers": [item.name for item in db.query(Supplier).order_by(Supplier.name).all()],
        "locations": [get_location_path(item) for item in locations],
        "statuses": [item.value for item in ObjectStatus],
        "limits": {"objects_per_page": 200, "maintenance_schedules_per_object": 3},
    }


@app.get("/api/v1/objects", response_model=ExternalObjectListResponse)
def external_api_list_objects(
    q: Optional[str] = None,
    object_type: Optional[str] = None,
    object_status: Optional[ObjectStatus] = None,
    location: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    client: ApiClient = Depends(require_api_scope("objects:read"))
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    query = db.query(InventoryObject)
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(or_(
            InventoryObject.designation.ilike(search),
            InventoryObject.object_number.ilike(search),
            InventoryObject.serial_number.ilike(search),
        ))
    if object_type and object_type.strip():
        query = query.join(InventoryObject.object_type).filter(
            func.lower(ObjectType.name) == object_type.strip().lower()
        )
    if object_status:
        query = query.filter(InventoryObject.status == object_status)
    if location and location.strip():
        selected_location = find_location_by_path(db, location)
        if not selected_location:
            raise HTTPException(status_code=422, detail=f'Standort „{location.strip()}“ wurde nicht gefunden.')
        query = query.filter(InventoryObject.location_id.in_(get_all_sub_location_ids(db, selected_location.id)))
    total = query.count()
    objects = query.order_by(InventoryObject.id).offset(offset).limit(limit).all()
    add_api_audit(db, client, "list", "object", details={"query": q, "count": len(objects)})
    return ExternalObjectListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[build_external_object_response(obj) for obj in objects],
    )


@app.get("/api/v1/objects/{identifier}", response_model=ExternalObjectResponse)
def external_api_get_object(
    identifier: str,
    db: Session = Depends(get_db),
    client: ApiClient = Depends(require_api_scope("objects:read"))
):
    obj = resolve_external_object(db, identifier)
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden.")
    add_api_audit(db, client, "read", "object", str(obj.id))
    return build_external_object_response(obj)


@app.post("/api/v1/objects", response_model=ExternalObjectResponse, status_code=status.HTTP_201_CREATED)
def external_api_create_object(
    data: ExternalObjectCreate,
    db: Session = Depends(get_db),
    client: ApiClient = Depends(require_api_scope("objects:write"))
):
    designation = data.designation.strip()
    object_type_name = data.object_type.strip()
    if not designation:
        raise HTTPException(status_code=422, detail="Bitte eine Bezeichnung eingeben.")
    if not object_type_name:
        raise HTTPException(status_code=422, detail="Bitte eine Kategorie angeben.")
    if any(not schedule.description.strip() for schedule in data.maintenance_schedules):
        raise HTTPException(status_code=422, detail="Jede Prüffrist benötigt eine Bezeichnung.")
    object_type = resolve_named_master_data(
        db, ObjectType, object_type_name, "Kategorie", data.create_missing_master_data
    )
    manufacturer = resolve_named_master_data(
        db, Manufacturer, data.manufacturer, "Hersteller", data.create_missing_master_data
    )
    supplier = resolve_named_master_data(
        db, Supplier, data.supplier, "Lieferant", data.create_missing_master_data
    )
    selected_location = None
    if data.location and data.location.strip():
        selected_location = find_location_by_path(db, data.location)
        if not selected_location:
            raise HTTPException(
                status_code=422,
                detail=f'Standortpfad „{data.location.strip()}“ wurde nicht gefunden. Gültige Pfade liefert GET /api/v1/meta.'
            )
    serial = ensure_serial_number_available(db, data.serial_number)
    obj = create_object(
        InventoryObjectCreate(
            object_type_id=object_type.id,
            designation=designation,
            serial_number=serial,
            manufacturer_id=manufacturer.id if manufacturer else None,
            supplier_id=supplier.id if supplier else None,
            location_id=selected_location.id if selected_location else None,
            info_text=data.info_text,
            usage_hints=data.usage_hints,
            acquisition_date=data.acquisition_date,
            status=data.status,
            inspection_required=data.inspection_required,
            maintenance_schedules=data.maintenance_schedules if data.inspection_required else [],
        ),
        db=db,
        user=client.created_by,
    )
    add_api_audit(
        db, client, "create", "object", str(obj.id),
        {"object_number": obj.object_number, "designation": obj.designation}
    )
    db.refresh(obj)
    return build_external_object_response(obj)

@app.post("/api/objects", response_model=InventoryObjectFullResponse)
def create_object(
    data: InventoryObjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    inspection_required = bool(data.inspection_required)
    standard_inspection_enabled = inspection_required and bool(data.standard_inspection_enabled)
    standard_template_id = validate_standard_inspection_assignment(
        db,
        standard_inspection_enabled,
        data.standard_inspection_template_id if standard_inspection_enabled else None
    )
    obj = InventoryObject(
        object_type_id=data.object_type_id,
        designation=data.designation,
        object_number=f"TEMP-{uuid.uuid4().hex}",  # Eindeutig auch bei parallelen API-Aufrufen
        serial_number=data.serial_number,
        manufacturer_id=data.manufacturer_id,
        supplier_id=data.supplier_id,
        location_id=data.location_id,
        info_text=data.info_text,
        usage_hints=data.usage_hints,
        acquisition_date=data.acquisition_date,
        status=data.status,
        inspection_required=inspection_required,
        standard_inspection_enabled=standard_inspection_enabled,
        standard_inspection_template_id=standard_template_id,
        created_by_id=user.id
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    
    # Eindeutige Nummer generieren
    obj.object_number = f"FFW-{obj.id:05d}"
    db.commit()
    
    # QR-Code generieren
    qr_filename = generate_qr_code(obj.object_number)
    qr = QRCode(object_id=obj.id, filename=qr_filename)
    db.add(qr)
    db.commit()

    # Wenn Objekt vom Typ "Fahrzeug" und Standort ausgewählt -> automatisch als Standort anlegen
    obj_type = db.query(ObjectType).filter(ObjectType.id == obj.object_type_id).first()
    if obj_type and obj_type.name == "Fahrzeug" and data.location_id:
        # Prüfe ob bereits ein Standort mit diesem Namen existiert
        existing_loc = db.query(Location).filter(
            Location.name == obj.designation,
            Location.parent_id == data.location_id
        ).first()
        if not existing_loc:
            vehicle_loc = Location(
                name=obj.designation,
                location_type="Fahrzeug",
                parent_id=data.location_id,
                linked_object_id=obj.id
            )
            db.add(vehicle_loc)
            db.commit()

    # Bis zu drei voneinander unabhängige Prüffristen anlegen. Alte Clients mit
    # maintenance_interval_days bleiben weiterhin kompatibel.
    schedules = data.maintenance_schedules
    if schedules is None and data.maintenance_interval_days:
        schedules = [MaintenanceCreate(
            description=data.maintenance_notes or "Allgemeine Prüfung / Wartung",
            interval_days=data.maintenance_interval_days,
            notes=data.maintenance_notes
        )]
    if inspection_required and schedules:
        create_maintenance_entries(db, obj, schedules, data.acquisition_date)
        db.commit()

    db.refresh(obj)
    return obj

@app.get("/api/objects/{object_id}")
def get_object(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    
    # Standardnutzer bekommt reduzierte Daten
    if user.role == UserRole.STANDARD:
        # Filtere Dokumente: nur öffentliche
        public_docs = [d for d in obj.documents if d.is_public]
        # Standardnutzer sehen nur Prüfungen der am Objekt festgelegten Prüfkarte.
        public_inspections = []
        for i in obj.inspections:
            if standard_user_can_access_inspection(obj, i.template_id):
                public_inspections.append(build_inspection_response(i))
        return InventoryObjectPublicResponse(
            id=obj.id,
            object_type=ObjectTypeResponse(id=obj.object_type.id, name=obj.object_type.name) if obj.object_type else None,
            designation=obj.designation,
            object_number=obj.object_number,
            manufacturer=ManufacturerResponse(id=obj.manufacturer.id, name=obj.manufacturer.name) if obj.manufacturer else None,
            supplier=SupplierResponse(id=obj.supplier.id, name=obj.supplier.name) if obj.supplier else None,
            location=LocationResponse(id=obj.location.id, name=obj.location.name, location_type=obj.location.location_type, parent_id=obj.location.parent_id) if obj.location else None,
            title_image=obj.title_image,
            info_text=obj.info_text,
            usage_hints=obj.usage_hints,
            acquisition_date=obj.acquisition_date,
            status=obj.status,
            inspection_required=obj.inspection_required,
            standard_inspection_enabled=obj.standard_inspection_enabled,
            standard_inspection_template_id=obj.standard_inspection_template_id,
            documents=[build_document_response(d) for d in public_docs],
            inspections=public_inspections,
            qr_code=QRCodeResponse(id=obj.qr_code.id, filename=obj.qr_code.filename, created_at=obj.qr_code.created_at) if obj.qr_code else None
        )
    
    # Vollständige Antwort mit aufgelösten Inspections
    inspections = [build_inspection_response(i) for i in obj.inspections]
    
    return InventoryObjectFullResponse(
        id=obj.id,
        object_type=ObjectTypeResponse(id=obj.object_type.id, name=obj.object_type.name) if obj.object_type else None,
        designation=obj.designation,
        object_number=obj.object_number,
        serial_number=obj.serial_number,
        manufacturer=ManufacturerResponse(id=obj.manufacturer.id, name=obj.manufacturer.name) if obj.manufacturer else None,
        supplier=SupplierResponse(id=obj.supplier.id, name=obj.supplier.name) if obj.supplier else None,
        location=LocationResponse(id=obj.location.id, name=obj.location.name, location_type=obj.location.location_type, parent_id=obj.location.parent_id) if obj.location else None,
        title_image=obj.title_image,
        info_text=obj.info_text,
        usage_hints=obj.usage_hints,
        acquisition_date=obj.acquisition_date,
        status=obj.status,
        inspection_required=obj.inspection_required,
        standard_inspection_enabled=obj.standard_inspection_enabled,
        standard_inspection_template_id=obj.standard_inspection_template_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        images=[ObjectImageResponse.model_validate(img) for img in obj.images],
        maintenances=[MaintenanceResponse.model_validate(m) for m in obj.maintenances],
        repairs=[RepairResponse.model_validate(r) for r in obj.repairs],
        documents=[build_document_response(d) for d in obj.documents],
        inspections=inspections,
        qr_code=QRCodeResponse(id=obj.qr_code.id, filename=obj.qr_code.filename, created_at=obj.qr_code.created_at) if obj.qr_code else None
    )

@app.put("/api/objects/{object_id}", response_model=InventoryObjectFullResponse)
def update_object(
    object_id: int,
    data: InventoryObjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    old_designation = obj.designation
    values = data.model_dump(exclude_unset=True)
    effective_inspection_required = bool(values.get("inspection_required", obj.inspection_required))
    values["inspection_required"] = effective_inspection_required
    if not effective_inspection_required:
        values["standard_inspection_enabled"] = False
        values["standard_inspection_template_id"] = None
    assignment_changed = (
        "inspection_required" in data.model_fields_set or
        "standard_inspection_enabled" in values or
        "standard_inspection_template_id" in values
    )
    if assignment_changed and effective_inspection_required:
        effective_enabled = bool(values.get("standard_inspection_enabled", obj.standard_inspection_enabled))
        effective_template_id = values.get("standard_inspection_template_id", obj.standard_inspection_template_id)
        values["standard_inspection_enabled"] = effective_enabled
        values["standard_inspection_template_id"] = validate_standard_inspection_assignment(
            db,
            effective_enabled,
            effective_template_id
        )
    object_values = {
        key: value for key, value in values.items()
        if key not in {"maintenance_schedules", "maintenance_interval_days", "maintenance_notes"}
    }
    for key, value in object_values.items():
        setattr(obj, key, value)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)

    # Prüffristen aktualisieren, entfernen oder neu anlegen.
    schedules_were_sent = "maintenance_schedules" in data.model_fields_set
    interval_was_sent = "maintenance_interval_days" in data.model_fields_set
    if not effective_inspection_required:
        for entry in list(obj.maintenances):
            db.delete(entry)
        db.commit()
    elif schedules_were_sent:
        sync_maintenance_entries(db, obj, data.maintenance_schedules or [])
        db.commit()
    elif interval_was_sent:
        # Abwärtskompatibilität für ältere Clients mit nur einer Prüffrist.
        existing_maint = db.query(Maintenance).filter(Maintenance.object_id == object_id).order_by(Maintenance.id).first()
        if data.maintenance_interval_days is None:
            if existing_maint:
                db.delete(existing_maint)
            db.commit()
        else:
            next_date = maintenance_due_date(obj.acquisition_date, data.maintenance_interval_days)
            if existing_maint:
                existing_maint.description = data.maintenance_notes or existing_maint.description or "Allgemeine Prüfung / Wartung"
                existing_maint.interval_days = data.maintenance_interval_days
                existing_maint.notes = data.maintenance_notes
                if data.acquisition_date:
                    existing_maint.last_maintenance_date = data.acquisition_date
                    existing_maint.next_maintenance_date = next_date
            else:
                db.add(Maintenance(
                    object_id=obj.id,
                    description=data.maintenance_notes or "Allgemeine Prüfung / Wartung",
                    interval_days=data.maintenance_interval_days,
                    last_maintenance_date=obj.acquisition_date,
                    next_maintenance_date=next_date,
                    notes=data.maintenance_notes
                ))
            db.commit()

    # Sticker neu generieren wenn Bezeichnung geändert wurde
    if data.designation and data.designation != old_designation:
        sticker_path = f"uploads/qrcodes/sticker_{obj.object_number}.png"
        if os.path.exists(sticker_path):
            os.remove(sticker_path)
        generate_sticker(obj.object_number, obj.designation)
    return obj

@app.delete("/api/objects/{object_id}")
def delete_object(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    
    # Lösche zugehörige Dateien
    for img in obj.images:
        path = f"uploads/images/{img.filename}"
        if os.path.exists(path):
            os.remove(path)
    for doc in obj.documents:
        path = f"uploads/documents/{doc.filename}"
        if os.path.exists(path):
            os.remove(path)
    if obj.title_image:
        path = f"uploads/images/{obj.title_image}"
        if os.path.exists(path):
            os.remove(path)
    if obj.qr_code:
        for f in [obj.qr_code.filename, f"sticker_{obj.object_number}.png"]:
            path = f"uploads/qrcodes/{f}"
            if os.path.exists(path):
                os.remove(path)
    for inspection in obj.inspections:
        for inspection_image in inspection.images:
            path = f"uploads/inspection_images/{inspection_image.filename}"
            if os.path.exists(path):
                os.remove(path)
    
    db.delete(obj)
    db.commit()
    return {"ok": True}

# --- Bilder ---

@app.post("/api/objects/{object_id}/images")
def upload_image(
    object_id: int,
    caption: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    filename = save_upload(file, "uploads/images")
    img = ObjectImage(object_id=object_id, filename=filename, caption=caption)
    db.add(img)
    db.commit()
    return {"ok": True, "filename": filename}

@app.post("/api/objects/bulk/title-image")
def upload_bulk_title_image(
    object_ids: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    try:
        parsed_ids = json.loads(object_ids)
        ids = list(dict.fromkeys(int(value) for value in parsed_ids))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Die Objektliste für das Sammelbild ist ungültig.")
    if not ids or len(ids) > 100:
        raise HTTPException(status_code=422, detail="Das Sammelbild kann auf 1 bis 100 Objekte angewendet werden.")
    objects = db.query(InventoryObject).filter(InventoryObject.id.in_(ids)).all()
    if len(objects) != len(ids):
        raise HTTPException(status_code=404, detail="Mindestens ein Objekt der Sammelanlage wurde nicht gefunden.")

    first_filename = save_upload(file, "uploads/images")
    source_path = os.path.join("uploads/images", first_filename)
    suffix = os.path.splitext(first_filename)[1]
    for index, obj in enumerate(objects):
        filename = first_filename if index == 0 else f"{uuid.uuid4().hex}{suffix}"
        if index > 0:
            shutil.copy2(source_path, os.path.join("uploads/images", filename))
        obj.title_image = filename
    db.commit()
    return {"ok": True, "updated_count": len(objects)}


@app.post("/api/objects/{object_id}/title-image")
def upload_title_image(
    object_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    filename = save_upload(file, "uploads/images")
    obj.title_image = filename
    db.commit()
    return {"ok": True, "filename": filename}

# --- Wartung ---

@app.post("/api/objects/{object_id}/maintenance", response_model=MaintenanceResponse)
def add_maintenance(
    object_id: int,
    data: MaintenanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_verwaltung)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    if not obj.inspection_required:
        raise HTTPException(status_code=409, detail="Für diesen Artikel sind Prüfungen deaktiviert.")
    if db.query(Maintenance).filter(Maintenance.object_id == object_id).count() >= 3:
        raise HTTPException(status_code=409, detail="Pro Artikel können höchstens drei Prüffristen angelegt werden.")
    maint = Maintenance(
        object_id=object_id,
        description=data.description.strip(),
        interval_days=data.interval_days,
        last_maintenance_date=data.last_maintenance_date or obj.acquisition_date,
        next_maintenance_date=maintenance_due_date(
            obj.acquisition_date,
            data.interval_days,
            data.next_maintenance_date
        ),
        notes=data.notes
    )
    db.add(maint)
    db.commit()
    db.refresh(maint)
    return maint

# --- Reparaturen ---

@app.post("/api/objects/{object_id}/repairs", response_model=RepairResponse)
def add_repair(
    object_id: int,
    data: RepairCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_verwaltung)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    repair = Repair(**data.model_dump(), object_id=object_id)
    db.add(repair)
    db.commit()
    db.refresh(repair)
    return repair

# --- Dokumente ---

def get_document_label_or_404(db: Session, label_id: int) -> DocumentLabel:
    label = db.query(DocumentLabel).filter(DocumentLabel.id == label_id).first()
    if not label:
        raise HTTPException(status_code=422, detail="Das ausgewählte Dokumentenlabel existiert nicht mehr.")
    return label


@app.get("/api/document-labels", response_model=List[DocumentLabelResponse])
def list_document_labels(
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    return db.query(DocumentLabel).order_by(DocumentLabel.name).all()


@app.post("/api/document-labels", response_model=DocumentLabelResponse, status_code=status.HTTP_201_CREATED)
def create_document_label(
    data: DocumentLabelCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen für das Label eingeben.")
    existing = db.query(DocumentLabel).filter(func.lower(DocumentLabel.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f'Das Label „{existing.name}“ ist bereits vorhanden.')
    label = DocumentLabel(name=name, is_default=False)
    db.add(label)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Das Label „{name}“ ist bereits vorhanden.')
    db.refresh(label)
    return label


@app.get("/api/documents", response_model=List[DocumentResponse])
def list_documents(
    q: Optional[str] = None,
    label_id: Optional[int] = None,
    assignment: str = "all",
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    query = db.query(Document).outerjoin(Document.label).outerjoin(Document.inventory_object)
    if user.role == UserRole.STANDARD:
        query = query.filter(Document.is_public.is_(True))
    if label_id:
        query = query.filter(Document.label_id == label_id)
    if assignment == "assigned":
        query = query.filter(Document.object_id.isnot(None))
    elif assignment == "unassigned":
        query = query.filter(Document.object_id.is_(None))
    elif assignment != "all":
        raise HTTPException(status_code=422, detail="Ungültiger Zuordnungsfilter.")
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(or_(
            Document.original_name.ilike(search),
            DocumentLabel.name.ilike(search),
            InventoryObject.designation.ilike(search),
            InventoryObject.object_number.ilike(search),
        ))
    documents = query.order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(1000).all()
    return [build_document_response(document) for document in documents]


@app.post("/api/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_unassigned_document(
    label_id: int = Form(...),
    is_public: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    get_document_label_or_404(db, label_id)
    filename = save_upload(file, "uploads/documents")
    document = Document(
        object_id=None,
        label_id=label_id,
        filename=filename,
        original_name=file.filename,
        file_type=determine_file_type(file.filename),
        is_public=is_public,
        uploaded_by_id=user.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return build_document_response(document)


@app.put("/api/documents/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    data: DocumentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden.")
    values = data.model_dump(exclude_unset=True)
    if "label_id" in values and values["label_id"] is not None:
        get_document_label_or_404(db, values["label_id"])
    for key, value in values.items():
        setattr(document, key, value)
    db.commit()
    db.refresh(document)
    return build_document_response(document)


@app.post("/api/objects/{object_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    object_id: int,
    label_id: int = Form(...),
    is_public: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    get_document_label_or_404(db, label_id)
    filename = save_upload(file, "uploads/documents")
    doc = Document(
        object_id=object_id,
        label_id=label_id,
        filename=filename,
        original_name=file.filename,
        file_type=determine_file_type(file.filename),
        is_public=is_public,
        uploaded_by_id=user.id
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return build_document_response(doc)

# --- QR Code für Standard-Login ---
def ensure_qr_login_code() -> str:
    """Stellt sicher, dass der QR-Login-Code existiert"""
    qr_path = "uploads/qrcodes/qr_standard_login.png"
    if not os.path.exists(qr_path):
        url = f"{BASE_URL}/?qrlogin=1"
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_path)
    return qr_path

@app.get("/api/auth/qr-login-code")
def get_qr_login_code():
    """QR-Code für schnellen Standardnutzer-Login"""
    return FileResponse(ensure_qr_login_code())

@app.get("/api/auth/qr-login-sticker", response_class=HTMLResponse)
def get_qr_login_sticker():
    """Druckbarer Aufkleber mit QR-Login-Code"""
    qr_path = ensure_qr_login_code()
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>QR-Login Aufkleber</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{ margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; text-align: center; background: #f1f3f5; color: #222; }}
            .toolbar {{ max-width: 520px; margin: 0 auto 20px; padding: 14px; border-radius: 12px; background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
            .toolbar-actions {{ display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }}
            .toolbar a, .toolbar button {{ min-height: 42px; padding: 9px 14px; border: 0; border-radius: 7px; background: #5d6268; color: #fff; font: inherit; font-weight: 700; cursor: pointer; text-decoration: none; }}
            .toolbar button {{ background: #b71c1c; }}
            .toolbar p {{ margin: 12px 0 0; color: #626b75; }}
            .sticker {{ border: 2px dashed #ccc; padding: 20px; display: inline-block; max-width: 400px; }}
            .sticker img {{ width: 200px; height: 200px; }}
            .sticker h3 {{ margin: 0.5rem 0; color: #333; }}
            .sticker p {{ color: #666; font-size: 0.9rem; margin: 0.3rem 0; }}
            .sticker .url {{ font-family: monospace; background: #f5f5f5; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; }}
            @media print {{
                @page {{ margin: 0; }}
                body {{ padding: 0; }}
                .no-print {{ display: none; }}
                .sticker {{ border: none; box-shadow: none; }}
            }}
            @media (max-width: 520px) {{
                body {{ padding: 10px; }}
                .toolbar-actions > * {{ flex: 1 1 45%; }}
                .sticker {{ max-width: 100%; padding: 12px; }}
                .sticker .url {{ display: block; overflow-wrap: anywhere; }}
            }}
        </style>
    </head>
    <body>
        <div class="toolbar no-print">
            <div class="toolbar-actions">
                <a href="/?v=46#admin">← Zurück zur Verwaltung</a>
                <button onclick="window.print()">🖨️ Drucken</button>
            </div>
            <p>Empfohlene Aufkleber-Größe: 50 x 50 mm oder größer</p>
        </div>
        <div class="sticker">
            <h3>🚒 Feuerwehr Inventar</h3>
            <p><strong>Schneller Zugriff</strong></p>
            <img src="/api/auth/qr-login-code" alt="QR-Login">
            <p>Scannen für Standardnutzer-Login</p>
            <p class="url">{BASE_URL}/?qrlogin=1</p>
        </div>
    </body>
    </html>
    """
    return html

# --- QR Code & Sticker ---

@app.get("/api/objects/{object_id}/qr")
def get_qr_code(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj or not obj.qr_code:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    return FileResponse(f"uploads/qrcodes/{obj.qr_code.filename}")

@app.get("/api/objects/{object_id}/sticker")
def get_sticker(object_id: int, db: Session = Depends(get_db)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    sticker_path = f"uploads/qrcodes/sticker_{obj.object_number}.png"
    # Sticker immer neu generieren, damit Bezeichnung aktuell ist
    generate_sticker(obj.object_number, obj.designation)
    return FileResponse(sticker_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

@app.get("/api/objects/{object_id}/barcode.svg")
def get_object_barcode(object_id: int, db: Session = Depends(get_db)):
    """Schmaler Code-128-Strichcode mit derselben Geräte-ID wie der QR-Code."""
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.graphics import renderSVG

    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    drawing = createBarcodeDrawing(
        "Code128",
        value=obj.object_number,
        barHeight=42,
        barWidth=0.9,
        humanReadable=False
    )
    return Response(
        content=renderSVG.drawToString(drawing),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
    )


@app.get("/api/objects/{object_id}/sticker/pdf")
def get_sticker_pdf(object_id: int, layout: str = "qr-id", db: Session = Depends(get_db)):
    """Maßgenaues Etiketten-PDF ohne Browser-Kopf- und Fußzeilen."""
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import code128

    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    if not obj.qr_code:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")

    layouts = {
        "qr-small": (25, 25),
        "qr-id": (50, 25),
        "qr-full": (70, 35),
        "barcode": (55, 18),
    }
    if layout not in layouts:
        raise HTTPException(status_code=422, detail="Unbekannte Aufklebergröße")

    width_mm, height_mm = layouts[layout]
    width, height = width_mm * mm, height_mm * mm
    qr_path = os.path.join("uploads/qrcodes", obj.qr_code.filename)
    if not os.path.exists(qr_path):
        generate_qr_code(obj.object_number)

    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setTitle(f"Aufkleber {obj.object_number}")

    def draw_fitted_text(value: str, x: float, y: float, max_width: float, preferred_size: float, minimum_size: float = 5.5):
        font_size = preferred_size
        while font_size > minimum_size and stringWidth(value, "Helvetica-Bold", font_size) > max_width:
            font_size -= 0.5
        pdf.setFont("Helvetica-Bold", font_size)
        pdf.drawString(x, y, value)

    if layout == "qr-small":
        pdf.drawImage(qr_path, 1.5 * mm, 1.5 * mm, 22 * mm, 22 * mm, preserveAspectRatio=True, mask="auto")
    elif layout == "qr-id":
        pdf.drawImage(qr_path, 1.2 * mm, 1.75 * mm, 21.5 * mm, 21.5 * mm, preserveAspectRatio=True, mask="auto")
        text_x = 25 * mm
        draw_fitted_text(obj.object_number, text_x, 14.2 * mm, 23 * mm, 10)
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillColorRGB(.27, .27, .27)
        pdf.drawString(text_x, 8.5 * mm, "Scannen fuer")
        pdf.drawString(text_x, 5.8 * mm, "Geraetedetails")
    elif layout == "qr-full":
        pdf.drawImage(qr_path, 1.5 * mm, 2.25 * mm, 30.5 * mm, 30.5 * mm, preserveAspectRatio=True, mask="auto")
        text_x = 34.5 * mm
        draw_fitted_text(obj.designation, text_x, 23.5 * mm, 33.5 * mm, 11)
        draw_fitted_text(obj.object_number, text_x, 16.5 * mm, 33.5 * mm, 9)
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillColorRGB(.27, .27, .27)
        pdf.drawString(text_x, 9.5 * mm, "Feuerwehr Inventar")
    else:
        barcode = code128.Code128(obj.object_number, barHeight=10 * mm, barWidth=.25 * mm, humanReadable=False)
        scale = min(1, (51 * mm) / barcode.width)
        barcode_width = barcode.width * scale
        pdf.saveState()
        pdf.translate((width - barcode_width) / 2, 5 * mm)
        pdf.scale(scale, 1)
        barcode.drawOn(pdf, 0, 0)
        pdf.restoreState()
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawCentredString(width / 2, 2.2 * mm, obj.object_number)

    pdf.showPage()
    pdf.save()
    output.seek(0)
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", obj.object_number).strip("_") or "aufkleber"
    return Response(
        content=output.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}_{layout}.pdf"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


@app.get("/api/objects/{object_id}/sticker/print", response_class=HTMLResponse)
def print_sticker(object_id: int, db: Session = Depends(get_db)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    from html import escape as html_escape
    safe_number = html_escape(obj.object_number)
    safe_designation = html_escape(obj.designation)
    if not obj.qr_code:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    qr_url = f"/uploads/qrcodes/{html_escape(obj.qr_code.filename)}"
    barcode_url = f"/api/objects/{obj.id}/barcode.svg"
    return_url = f"/?v=46#object/{obj.id}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Aufkleber {safe_number}</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{ margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #222; background: #f1f3f5; }}
            .toolbar {{ max-width: 760px; margin: 0 auto 18px; padding: 16px; border-radius: 12px; background: white; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
            .toolbar-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
            button, .back, .pdf-action {{ min-height: 42px; padding: 9px 13px; border: 0; border-radius: 7px; background: #5d6268; color: white; font: inherit; font-weight: 650; cursor: pointer; text-decoration: none; }}
            .pdf-action {{ display: inline-flex; align-items: center; background: #b71c1c; }}
            button.layout.active {{ outline: 3px solid #ffd1d1; background: #8f1515; }}
            .toolbar h1 {{ margin: 12px 0 6px; font-size: 1.3rem; }}
            .toolbar p {{ margin: 0 0 12px; color: #626b75; }}
            #size-note {{ margin-top: 10px; font-weight: 650; color: #334155; }}
            .preview {{ display: flex; justify-content: center; align-items: flex-start; min-height: 290px; padding: 42px 12px; overflow: auto; }}
            .sticker {{ display: none; overflow: hidden; border: .35mm solid #111; background: white; color: black; }}
            .sticker.active {{ display: flex; }}
            .sticker img {{ display: block; object-fit: contain; }}
            .qr-only {{ width: 25mm; height: 25mm; padding: 1mm; align-items: center; justify-content: center; }}
            .qr-only img {{ width: 22mm; height: 22mm; }}
            .qr-id {{ width: 50mm; height: 25mm; padding: 1.2mm; align-items: center; gap: 2mm; }}
            .qr-id img {{ width: 21.5mm; height: 21.5mm; flex: none; }}
            .label-text {{ min-width: 0; text-align: left; line-height: 1.12; }}
            .label-text .number {{ display: block; font-size: 10pt; font-weight: 800; overflow-wrap: anywhere; }}
            .label-text .hint {{ display: block; margin-top: 2mm; font-size: 6.5pt; color: #444; }}
            .qr-full {{ width: 70mm; height: 35mm; padding: 1.5mm; align-items: center; gap: 2.5mm; }}
            .qr-full img {{ width: 30.5mm; height: 30.5mm; flex: none; }}
            .qr-full .designation {{ display: block; margin-bottom: 2mm; font-size: 11pt; font-weight: 800; overflow-wrap: anywhere; }}
            .barcode-label {{ width: 55mm; height: 18mm; padding: 1.2mm 1.8mm; flex-direction: column; align-items: center; justify-content: center; gap: .5mm; }}
            .barcode-label img {{ width: 50mm; height: 11mm; }}
            .barcode-label strong {{ font-size: 7pt; letter-spacing: .5pt; }}
            @media print {{
                @page {{ margin: 0; }}
                body {{ padding: 0; background: white; }}
                .no-print {{ display: none !important; }}
                .preview {{ min-height: 0; padding: 0; display: block; }}
                .sticker {{ border-color: transparent; page-break-inside: avoid; }}
                .sticker.active {{ display: flex; }}
            }}
            @media (max-width: 600px) {{
                body {{ padding: 10px; }}
                .toolbar-row button, .toolbar-row .back, .toolbar-row .pdf-action {{ flex: 1 1 45%; justify-content: center; }}
                .preview {{ justify-content: flex-start; }}
            }}
        </style>
    </head>
    <body>
        <div class="toolbar no-print">
            <div class="toolbar-row">
                <a class="back" href="{return_url}">← Zurück zum Gerät</a>
                <a id="pdf-action" class="pdf-action" href="/api/objects/{obj.id}/sticker/pdf?layout=qr-id" target="_blank">🖨️ Etikett drucken / PDF</a>
            </div>
            <h1>Aufkleber für {safe_designation}</h1>
            <p>Vor dem Drucken die passende Etikettengröße auswählen. Das maßgenaue PDF enthält keine Browser-Kopf- oder Fußzeile.</p>
            <div class="toolbar-row" role="group" aria-label="Aufklebergröße">
                <button class="layout" data-layout="qr-small" onclick="selectLayout('qr-small')">Nur QR · 25×25</button>
                <button class="layout active" data-layout="qr-id" onclick="selectLayout('qr-id')">QR + ID · 50×25</button>
                <button class="layout" data-layout="qr-full" onclick="selectLayout('qr-full')">QR + Text · 70×35</button>
                <button class="layout" data-layout="barcode" onclick="selectLayout('barcode')">Strichcode · 55×18</button>
            </div>
            <div id="size-note">Ausgewählt: QR-Code mit Geräte-ID, 50 × 25 mm</div>
        </div>
        <div class="preview">
            <div class="sticker qr-only" data-sticker="qr-small"><img src="{qr_url}" alt="QR-Code {safe_number}"></div>
            <div class="sticker qr-id active" data-sticker="qr-id">
                <img src="{qr_url}" alt="QR-Code {safe_number}">
                <div class="label-text"><span class="number">{safe_number}</span><span class="hint">Scannen für Gerätedetails</span></div>
            </div>
            <div class="sticker qr-full" data-sticker="qr-full">
                <img src="{qr_url}" alt="QR-Code {safe_number}">
                <div class="label-text"><span class="designation">{safe_designation}</span><span class="number">{safe_number}</span><span class="hint">Feuerwehr Inventar</span></div>
            </div>
            <div class="sticker barcode-label" data-sticker="barcode">
                <img src="{barcode_url}" alt="Code-128-Strichcode {safe_number}">
                <strong>{safe_number}</strong>
            </div>
        </div>
        <script>
            const notes = {{
                'qr-small': 'Ausgewählt: nur QR-Code, 25 × 25 mm',
                'qr-id': 'Ausgewählt: QR-Code mit Geräte-ID, 50 × 25 mm',
                'qr-full': 'Ausgewählt: QR-Code mit Bezeichnung und Geräte-ID, 70 × 35 mm',
                'barcode': 'Ausgewählt: schmaler Code-128-Strichcode, 55 × 18 mm'
            }};
            function selectLayout(layout) {{
                document.querySelectorAll('[data-sticker]').forEach(item => item.classList.toggle('active', item.dataset.sticker === layout));
                document.querySelectorAll('button.layout').forEach(item => item.classList.toggle('active', item.dataset.layout === layout));
                document.getElementById('size-note').textContent = notes[layout];
                document.getElementById('pdf-action').href = '/api/objects/{obj.id}/sticker/pdf?layout=' + encodeURIComponent(layout);
            }}
        </script>
    </body>
    </html>
    """
    return html

# --- Prüfkarten & Prüfungen ---

@app.get("/api/inspection-templates", response_model=List[InspectionTemplateResponse])
def list_templates(
    object_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    query = db.query(InspectionTemplate)
    # Standardnutzer erhalten ausschließlich die am konkreten Objekt festgelegte Karte.
    if user.role == UserRole.STANDARD:
        if object_id is None:
            return []
        obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
        if not standard_user_can_access_inspection(obj):
            return []
        query = query.filter(InspectionTemplate.id == obj.standard_inspection_template_id)
    return query.all()

@app.post("/api/inspection-templates", response_model=InspectionTemplateResponse)
def create_template(data: InspectionTemplateCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    import json
    template = InspectionTemplate(
        name=data.name,
        description=data.description,
        fields=json.dumps([f.model_dump() for f in data.fields]),
        object_type_id=data.object_type_id,
        default_interval_days=data.default_interval_days,
        allow_standard_users=data.allow_standard_users
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template

@app.get("/api/inspection-templates/{template_id}", response_model=InspectionTemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    t = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
    if user.role == UserRole.STANDARD:
        raise HTTPException(status_code=403, detail="Prüfkarten werden für Standardnutzer nur über das zugeordnete Objekt bereitgestellt.")
    return t


@app.get("/api/inspection-templates/{template_id}/pdf")
def get_inspection_template_pdf(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_verwaltung),
):
    """Leere Prüfkartenvorlage als druckbares A4-PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as xml_escape

    template = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")

    try:
        fields = json.loads(template.fields or "[]")
    except (TypeError, ValueError):
        fields = []

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Prüfkarte {template.name}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TemplateTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#b71c1c"),
        spaceAfter=8,
    )
    small_style = ParagraphStyle(
        "TemplateSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#5f6873"),
    )
    field_style = ParagraphStyle(
        "TemplateField",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )

    story = [
        Paragraph("Feuerwehr Inventar – Prüfkartenvorlage", small_style),
        Paragraph(xml_escape(template.name), title_style),
    ]
    if template.description:
        story.extend([
            Paragraph(xml_escape(template.description).replace("\n", "<br/>") , styles["Normal"]),
            Spacer(1, .25 * cm),
        ])

    category_name = template.object_type.name if template.object_type else "Alle Kategorien"
    interval_text = f"{template.default_interval_days} Tage" if template.default_interval_days else "Kein Standardintervall"
    meta_data = [
        ["Kategorie", xml_escape(category_name), "Standardintervall", interval_text],
        ["Inventarnummer", "", "Bezeichnung", ""],
        ["Prüfdatum", "", "Name Prüfer *", ""],
    ]
    meta_table = Table(meta_data, colWidths=[3.1 * cm, 5.2 * cm, 3.5 * cm, 5.2 * cm], rowHeights=[.8 * cm, 1 * cm, 1 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f3f5")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f3f5")),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#8d949c")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([meta_table, Spacer(1, .45 * cm)])

    field_rows = [["Prüfpunkt", "Eintrag / Ergebnis"]]
    row_heights = [.8 * cm]
    for field in fields:
        label = str(field.get("label") or "Prüfpunkt")
        if field.get("required"):
            label += " *"
        field_type = field.get("type")
        if field_type == "checkbox":
            entry = "[  ] Ja      [  ] Nein"
            row_height = 1.05 * cm
        elif field_type == "select":
            options = [str(option) for option in (field.get("options") or [])]
            entry = "     ".join(f"[  ] {xml_escape(option)}" for option in options) or ""
            row_height = max(1.05, .65 + .32 * max(1, len(options) // 3 + 1)) * cm
        elif field_type == "textarea":
            entry = "<br/><br/><br/>"
            row_height = 2.25 * cm
        else:
            entry = "<br/>"
            row_height = 1.15 * cm
        field_rows.append([
            Paragraph(xml_escape(label), field_style),
            Paragraph(entry, field_style),
        ])
        row_heights.append(row_height)

    if not fields:
        field_rows.append([Paragraph("Keine weiteren Prüfpunkte", field_style), ""])
        row_heights.append(1.1 * cm)

    fields_table = Table(field_rows, colWidths=[7.2 * cm, 9.8 * cm], rowHeights=row_heights, repeatRows=1)
    fields_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#b71c1c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#8d949c")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
    ]))
    story.extend([fields_table, Spacer(1, .45 * cm)])

    notes_table = Table(
        [[Paragraph("Bemerkungen / festgestellte Mängel", field_style)], [""]],
        colWidths=[17 * cm],
        rowHeights=[.7 * cm, 2.1 * cm],
    )
    notes_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f3f5")),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#8d949c")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([
        notes_table,
        Spacer(1, .55 * cm),
        Paragraph("Unterschrift Prüfer: _________________________________________", styles["Normal"]),
        Spacer(1, .3 * cm),
        Paragraph("* Pflichtfeld", small_style),
    ])
    document.build(story)
    output.seek(0)
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", template.name).strip("_") or f"pruefkarte_{template.id}"
    return Response(
        content=output.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="Pruefkarte_{safe_filename}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@app.put("/api/inspection-templates/{template_id}", response_model=InspectionTemplateResponse)
def update_template(template_id: int, data: InspectionTemplateCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    t = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
    import json
    t.name = data.name
    t.description = data.description
    t.fields = json.dumps([f.model_dump() for f in data.fields])
    t.object_type_id = data.object_type_id
    t.default_interval_days = data.default_interval_days
    t.allow_standard_users = data.allow_standard_users
    db.commit()
    db.refresh(t)
    return t

@app.get("/api/inspection-center", response_model=InspectionCenterResponse)
def get_inspection_center(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_overdue: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_verwaltung)
):
    """Anstehende Prüftermine für Verwaltung und Admin."""
    today = date.today()
    range_start = start_date or today
    range_end = end_date or (range_start + timedelta(days=90))
    if range_end < range_start:
        raise HTTPException(status_code=400, detail="Das Enddatum muss nach dem Startdatum liegen.")
    if (range_end - range_start).days > 1095:
        raise HTTPException(status_code=400, detail="Der gewählte Zeitraum darf höchstens drei Jahre umfassen.")

    def parse_due_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def is_in_requested_range(due: date) -> bool:
        if due > range_end:
            return False
        return include_overdue or due >= range_start

    def location_path(location: Optional[Location]) -> Optional[str]:
        if not location:
            return None
        parts = []
        current = location
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            parts.insert(0, current.name)
            current = current.parent
        return " > ".join(parts)

    items: List[InspectionDueItem] = []

    # Nur der jeweils neueste Eintrag je Objekt und Prüfkarte bestimmt den Folgetermin.
    latest_inspections = {}
    inspections = db.query(Inspection).order_by(Inspection.inspected_at.desc(), Inspection.id.desc()).all()
    for inspection in inspections:
        key = (inspection.object_id, inspection.template_id)
        if key not in latest_inspections:
            latest_inspections[key] = inspection

    for inspection in latest_inspections.values():
        obj = inspection.inventory_object
        # Bei einer verknüpften Prüffrist ist die Frist selbst die einzige
        # Terminquelle. So entsteht nach dem Zurücksetzen kein Doppeleintrag.
        if inspection.maintenance_id:
            continue
        due = parse_due_date(inspection.next_inspection_date)
        if not obj or not due or not is_in_requested_range(due):
            continue
        if not obj.inspection_required:
            continue
        if obj.status == ObjectStatus.AUSGEMUSTERT:
            continue
        items.append(InspectionDueItem(
            object_id=obj.id,
            object_number=obj.object_number,
            designation=obj.designation,
            serial_number=obj.serial_number,
            object_type=obj.object_type.name if obj.object_type else None,
            location_id=obj.location_id,
            location_name=location_path(obj.location),
            object_status=obj.status.value,
            source="inspection",
            template_id=inspection.template_id,
            inspection_name=inspection.template.name if inspection.template else "Prüfung",
            due_date=due.isoformat(),
            days_until=(due - today).days,
            last_inspection_date=inspection.inspected_at,
            last_inspected_by=inspection.inspector_name or (inspection.inspected_by.full_name if inspection.inspected_by else None),
            notes=inspection.notes
        ))

    # Alle am Artikel hinterlegten Prüffristen berücksichtigen (maximal drei).
    maintenances = db.query(Maintenance).order_by(Maintenance.object_id, Maintenance.id).all()
    for maintenance in maintenances:
        obj = maintenance.inventory_object
        due = parse_due_date(maintenance.next_maintenance_date)
        if not obj or not due or not is_in_requested_range(due):
            continue
        if not obj.inspection_required:
            continue
        if obj.status == ObjectStatus.AUSGEMUSTERT:
            continue
        last_linked_inspection = max(
            maintenance.inspections,
            key=lambda entry: (entry.inspected_at, entry.id),
            default=None
        )
        items.append(InspectionDueItem(
            object_id=obj.id,
            object_number=obj.object_number,
            designation=obj.designation,
            serial_number=obj.serial_number,
            object_type=obj.object_type.name if obj.object_type else None,
            location_id=obj.location_id,
            location_name=location_path(obj.location),
            object_status=obj.status.value,
            source="maintenance",
            maintenance_id=maintenance.id,
            inspection_name=maintenance.description or "Allgemeine Prüfung / Wartung",
            due_date=due.isoformat(),
            days_until=(due - today).days,
            last_inspection_date=last_linked_inspection.inspected_at if last_linked_inspection else None,
            last_inspected_by=(
                last_linked_inspection.inspector_name or
                (last_linked_inspection.inspected_by.full_name if last_linked_inspection and last_linked_inspection.inspected_by else None)
            ) if last_linked_inspection else None,
            notes=maintenance.notes
        ))

    items.sort(key=lambda item: (item.due_date, item.designation.lower(), item.inspection_name.lower()))
    summary = {
        "total": len(items),
        "overdue": sum(1 for item in items if item.days_until < 0),
        "today": sum(1 for item in items if item.days_until == 0),
        "next_7_days": sum(1 for item in items if 0 <= item.days_until <= 7),
        "next_30_days": sum(1 for item in items if 0 <= item.days_until <= 30)
    }
    return InspectionCenterResponse(
        start_date=range_start.isoformat(),
        end_date=range_end.isoformat(),
        include_overdue=include_overdue,
        summary=summary,
        items=items
    )

@app.get("/api/objects/{object_id}/inspections", response_model=List[InspectionResponse])
def get_inspections(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    query = db.query(Inspection).filter(Inspection.object_id == object_id)
    # Standardnutzer sehen nur Prüfungen der für dieses Objekt festgelegten Karte.
    if user.role == UserRole.STANDARD:
        if not standard_user_can_access_inspection(obj):
            return []
        query = query.filter(Inspection.template_id == obj.standard_inspection_template_id)
    inspections = query.order_by(Inspection.inspected_at.desc()).all()
    return [build_inspection_response(i) for i in inspections]

@app.post("/api/objects/{object_id}/inspections", response_model=InspectionResponse)
def create_inspection(
    object_id: int,
    data: InspectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    if not obj.inspection_required:
        raise HTTPException(status_code=409, detail="Für diesen Artikel sind Prüfungen deaktiviert.")

    template = db.query(InspectionTemplate).filter(InspectionTemplate.id == data.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
    if user.role == UserRole.STANDARD and not standard_user_can_access_inspection(obj, template.id):
        raise HTTPException(status_code=403, detail="Für dieses Objekt ist keine Prüfung mit dieser Prüfkarte freigegeben.")

    maintenance = None
    if data.maintenance_id is not None:
        if user.role == UserRole.STANDARD:
            raise HTTPException(status_code=403, detail="Standardnutzer dürfen keine Prüffrist zurücksetzen.")
        maintenance = db.query(Maintenance).filter(
            Maintenance.id == data.maintenance_id,
            Maintenance.object_id == object_id
        ).first()
        if not maintenance:
            raise HTTPException(status_code=422, detail="Die ausgewählte Prüffrist gehört nicht zu diesem Artikel.")

    inspector_name = data.inspector_name.strip()
    if not inspector_name:
        raise HTTPException(status_code=422, detail="Name Prüfer muss ausgefüllt werden")

    today_value = date.today().isoformat()
    if maintenance:
        next_inspection_date = maintenance_due_date(
            today_value,
            maintenance.interval_days,
            data.next_inspection_date
        )
    elif template.default_interval_days:
        next_inspection_date = maintenance_due_date(
            today_value,
            template.default_interval_days,
            data.next_inspection_date
        )
    elif data.next_inspection_date:
        next_inspection_date = maintenance_due_date(today_value, 1, data.next_inspection_date)
    else:
        next_inspection_date = None

    import json
    inspection = Inspection(
        object_id=object_id,
        template_id=data.template_id,
        maintenance_id=maintenance.id if maintenance else None,
        inspected_by_id=user.id,
        inspector_name=inspector_name,
        results=json.dumps(data.results),
        next_inspection_date=next_inspection_date,
        notes=data.notes
    )
    db.add(inspection)
    if maintenance:
        maintenance.last_maintenance_date = today_value
        maintenance.next_maintenance_date = next_inspection_date
    db.commit()
    db.refresh(inspection)
    return build_inspection_response(inspection)

@app.get("/api/inspections/{inspection_id}", response_model=InspectionResponse)
def get_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    i = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")
    # Standardnutzer dürfen nur Prüfungen der am Objekt festgelegten Karte sehen.
    if user.role == UserRole.STANDARD and not standard_user_can_access_inspection(i.inventory_object, i.template_id):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    requested_maintenance_id = (
        data.maintenance_id if "maintenance_id" in data.model_fields_set else i.maintenance_id
    )
    if requested_maintenance_id != i.maintenance_id:
        raise HTTPException(
            status_code=409,
            detail="Die zugeordnete Prüffrist kann nach dem Speichern nicht mehr geändert werden."
        )
    return build_inspection_response(i)

@app.put("/api/inspections/{inspection_id}", response_model=InspectionResponse)
def update_inspection(
    inspection_id: int,
    data: InspectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    i = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")

    # Prüfe ob Prüfung noch innerhalb von 2 Stunden bearbeitbar ist
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    if i.inspected_at < two_hours_ago:
        raise HTTPException(status_code=403, detail="Prüfung kann nur innerhalb von 2 Stunden nach Erstellung bearbeitet werden")

    # Standardnutzer dürfen nur die am Objekt festgelegte Prüfkarte bearbeiten.
    if user.role == UserRole.STANDARD and not standard_user_can_access_inspection(i.inventory_object, i.template_id):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    import json
    inspector_name = data.inspector_name.strip()
    if not inspector_name:
        raise HTTPException(status_code=422, detail="Name Prüfer muss ausgefüllt werden")
    inspection_day = i.inspected_at.date().isoformat()
    if i.maintenance:
        next_inspection_date = maintenance_due_date(
            inspection_day,
            i.maintenance.interval_days,
            data.next_inspection_date
        )
    elif i.template and i.template.default_interval_days:
        next_inspection_date = maintenance_due_date(
            inspection_day,
            i.template.default_interval_days,
            data.next_inspection_date
        )
    elif data.next_inspection_date:
        next_inspection_date = maintenance_due_date(inspection_day, 1, data.next_inspection_date)
    else:
        next_inspection_date = None
    i.results = json.dumps(data.results)
    i.inspector_name = inspector_name
    i.next_inspection_date = next_inspection_date
    i.notes = data.notes
    if i.maintenance:
        i.maintenance.last_maintenance_date = inspection_day
        i.maintenance.next_maintenance_date = next_inspection_date
    db.commit()
    db.refresh(i)
    return build_inspection_response(i)

@app.post("/api/inspections/{inspection_id}/images", response_model=InspectionImageResponse)
def upload_inspection_image(
    inspection_id: int,
    comment: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")
    if inspection.inspected_at < datetime.utcnow() - timedelta(hours=2):
        raise HTTPException(status_code=403, detail="Bilder können nur innerhalb von 2 Stunden ergänzt werden")
    if user.role == UserRole.STANDARD and not standard_user_can_access_inspection(inspection.inventory_object, inspection.template_id):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    clean_comment = comment.strip()
    if not clean_comment:
        raise HTTPException(status_code=422, detail="Zu jedem Bild muss ein Kommentar angegeben werden")

    filename = save_inspection_image(file)
    image = InspectionImage(
        inspection_id=inspection.id,
        filename=filename,
        original_name=(file.filename or "Prüfungsbild")[:255],
        comment=clean_comment
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image

@app.delete("/api/inspection-images/{image_id}")
def delete_inspection_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    image = db.query(InspectionImage).filter(InspectionImage.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    inspection = image.inspection
    if inspection.inspected_at < datetime.utcnow() - timedelta(hours=2):
        raise HTTPException(status_code=403, detail="Bilder können nur innerhalb von 2 Stunden entfernt werden")
    if user.role == UserRole.STANDARD and not standard_user_can_access_inspection(inspection.inventory_object, inspection.template_id):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    path = f"uploads/inspection_images/{image.filename}"
    if os.path.exists(path):
        os.remove(path)
    db.delete(image)
    db.commit()
    return {"ok": True}

@app.delete("/api/inspections/{inspection_id}")
def delete_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    i = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")
    for image in i.images:
        path = f"uploads/inspection_images/{image.filename}"
        if os.path.exists(path):
            os.remove(path)
    db.delete(i)
    db.commit()
    return {"ok": True}

@app.delete("/api/inspection-templates/{template_id}")
def delete_inspection_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    t = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
    assigned_objects = db.query(InventoryObject).filter(
        InventoryObject.standard_inspection_template_id == template_id
    ).count()
    if assigned_objects:
        raise HTTPException(
            status_code=409,
            detail=f"Die Prüfkarte ist noch {assigned_objects} Objekt(en) für Standardnutzer zugeordnet."
        )
    db.delete(t)
    db.commit()
    return {"ok": True}

# --- Import / Export ---
import csv
import io

@app.get("/api/export/csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    """Exportiert alle Objekte als CSV-Datei"""
    objects = db.query(InventoryObject).order_by(InventoryObject.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')

    # Header
    writer.writerow([
        'Bezeichnung', 'Typ', 'Seriennummer', 'Hersteller', 'Lieferant',
        'Standort', 'Infotext', 'Hinweise', 'Anschaffungsdatum',
        'Status', 'Prüfung_erforderlich', 'Prüfintervall_Tage', 'Prüfnotizen',
        'Prüffrist_1_Bezeichnung', 'Prüffrist_1_Intervall_Tage', 'Prüffrist_1_Nächster_Termin', 'Prüffrist_1_Hinweise',
        'Prüffrist_2_Bezeichnung', 'Prüffrist_2_Intervall_Tage', 'Prüffrist_2_Nächster_Termin', 'Prüffrist_2_Hinweise',
        'Prüffrist_3_Bezeichnung', 'Prüffrist_3_Intervall_Tage', 'Prüffrist_3_Nächster_Termin', 'Prüffrist_3_Hinweise'
    ])

    # Hilfsfunktion: Standort-Pfad zusammenbauen (z.B. "Gerätehaus > Halle 1")
    def get_location_path(loc):
        if not loc:
            return ''
        parts = [loc.name]
        current = loc
        while current.parent_id:
            parent = db.query(Location).filter(Location.id == current.parent_id).first()
            if not parent:
                break
            parts.insert(0, parent.name)
            current = parent
        return ' > '.join(parts)

    for obj in objects:
        schedules = sorted(obj.maintenances, key=lambda entry: entry.id)[:3]
        first_schedule = schedules[0] if schedules else None
        row = [
            obj.designation,
            obj.object_type.name if obj.object_type else '',
            obj.serial_number or '',
            obj.manufacturer.name if obj.manufacturer else '',
            obj.supplier.name if obj.supplier else '',
            get_location_path(obj.location),
            obj.info_text or '',
            obj.usage_hints or '',
            obj.acquisition_date or '',
            obj.status.value if obj.status else '',
            'Ja' if obj.inspection_required else 'Nein',
            first_schedule.interval_days if first_schedule else '',
            first_schedule.notes if first_schedule else ''
        ]
        for index in range(3):
            schedule = schedules[index] if index < len(schedules) else None
            row.extend([
                schedule.description if schedule else '',
                schedule.interval_days if schedule else '',
                schedule.next_maintenance_date if schedule else '',
                schedule.notes if schedule else ''
            ])
        writer.writerow(row)

    content = output.getvalue()
    output.close()

    # UTF-8 BOM für Excel-Kompatibilität
    content_with_bom = '\ufeff' + content

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        io.BytesIO(content_with_bom.encode('utf-8')),
        media_type='text/csv; charset=utf-8-sig',
        headers={
            'Content-Disposition': f'attachment; filename="feuerwehr_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        }
    )

@app.post("/api/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_verwaltung)
):
    """Importiert Objekte aus einer CSV-Datei. Nur neue Objekte werden hinzugefügt."""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Nur CSV-Dateien sind erlaubt")

    content = await file.read()
    text = content.decode('utf-8')
    reader = csv.reader(io.StringIO(text), delimiter=';')

    # Header überspringen
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(status_code=400, detail="CSV-Datei ist leer")
    normalized_header = [column.strip().lower().lstrip('\ufeff') for column in header]
    column_indexes = {name: index for index, name in enumerate(normalized_header)}

    def cell(row, column_name, fallback_index=None):
        index = column_indexes.get(column_name, fallback_index)
        if index is None or len(row) <= index:
            return ''
        return row[index].strip()

    # Stammdaten laden (für Lookup)
    types = {t.name: t.id for t in db.query(ObjectType).all()}
    manufacturers = {m.name: m.id for m in db.query(Manufacturer).all()}
    suppliers = {s.name: s.id for s in db.query(Supplier).all()}
    locations = {l.name: l.id for l in db.query(Location).all()}

    created_count = 0
    skipped_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=2):
        if not row or not row[0].strip():
            continue

        try:
            designation = cell(row, 'bezeichnung', 0)
            type_name = cell(row, 'typ', 1)
            serial_number = cell(row, 'seriennummer', 2) or None
            manufacturer_name = cell(row, 'hersteller', 3)
            supplier_name = cell(row, 'lieferant')
            location_name = cell(row, 'standort', 4)
            info_text = cell(row, 'infotext', 5) or None
            usage_hints = cell(row, 'hinweise', 6) or None
            acquisition_date = cell(row, 'anschaffungsdatum', 7) or None
            status_str = cell(row, 'status', 8) or 'in_benutzung'
            inspection_value = cell(row, 'prüfung_erforderlich').lower()
            inspection_required = inspection_value not in {'nein', 'no', 'false', '0', 'aus'} if inspection_value else True
            interval_value = cell(row, 'prüfintervall_tage', 9)
            interval_days = int(interval_value) if interval_value else None
            maint_notes = cell(row, 'prüfnotizen', 10) or None
            maintenance_schedules = []
            for schedule_index in range(1, 4):
                schedule_interval_value = cell(row, f'prüffrist_{schedule_index}_intervall_tage')
                if not schedule_interval_value:
                    continue
                schedule_interval = int(schedule_interval_value)
                schedule_description = cell(row, f'prüffrist_{schedule_index}_bezeichnung') or f'Prüffrist {schedule_index}'
                maintenance_schedules.append(MaintenanceCreate(
                    description=schedule_description,
                    interval_days=schedule_interval,
                    next_maintenance_date=cell(row, f'prüffrist_{schedule_index}_nächster_termin') or None,
                    notes=cell(row, f'prüffrist_{schedule_index}_hinweise') or None
                ))
            if not maintenance_schedules and interval_days:
                maintenance_schedules.append(MaintenanceCreate(
                    description=maint_notes or 'Allgemeine Prüfung / Wartung',
                    interval_days=interval_days,
                    notes=maint_notes
                ))

            # Prüfe ob Objekt bereits existiert (anhand Bezeichnung + Seriennummer)
            existing = db.query(InventoryObject).filter(
                InventoryObject.designation == designation,
                InventoryObject.serial_number == serial_number
            ).first()

            if existing:
                skipped_count += 1
                continue

            # Typ-ID auflösen
            type_id = types.get(type_name)
            if not type_id and type_name:
                # Neuen Typ anlegen
                new_type = ObjectType(name=type_name)
                db.add(new_type)
                db.commit()
                db.refresh(new_type)
                type_id = new_type.id
                types[type_name] = type_id

            # Hersteller-ID auflösen
            manufacturer_id = None
            if manufacturer_name:
                manufacturer_id = manufacturers.get(manufacturer_name)
                if not manufacturer_id:
                    new_manu = Manufacturer(name=manufacturer_name)
                    db.add(new_manu)
                    db.commit()
                    db.refresh(new_manu)
                    manufacturer_id = new_manu.id
                    manufacturers[manufacturer_name] = manufacturer_id

            # Lieferanten-ID auflösen
            supplier_id = None
            if supplier_name:
                supplier_id = suppliers.get(supplier_name)
                if not supplier_id:
                    new_supplier = Supplier(name=supplier_name)
                    db.add(new_supplier)
                    db.commit()
                    db.refresh(new_supplier)
                    supplier_id = new_supplier.id
                    suppliers[supplier_name] = supplier_id

            # Standort-ID auflösen (unterstützt Hierarchie mit ">" als Trennzeichen)
            # Default: "Gerätehaus" wenn kein Standort angegeben
            if not location_name:
                location_name = "Gerätehaus"
            
            location_id = None
            if location_name:
                # Untergeordnete Standorte: "Gerätehaus > Halle 1"
                loc_parts = [p.strip() for p in location_name.split('>') if p.strip()]
                parent_id = None
                for idx, part in enumerate(loc_parts):
                    # Ist es der letzte Teil? Dann ist es der eigentliche Standort
                    # Zwischenstände werden automatisch als "Standort" angelegt
                    loc_type = 'Standort'
                    
                    loc_key = f"{part}|{parent_id}"
                    location_id = locations.get(loc_key)
                    
                    if not location_id:
                        # Prüfe ob Standort bereits existiert
                        query = db.query(Location).filter(
                            Location.name == part,
                            Location.parent_id == parent_id
                        )
                        existing = query.first()
                        if existing:
                            location_id = existing.id
                        else:
                            new_loc = Location(name=part, location_type=loc_type, parent_id=parent_id)
                            db.add(new_loc)
                            db.commit()
                            db.refresh(new_loc)
                            location_id = new_loc.id
                        
                        locations[loc_key] = location_id
                    
                    parent_id = location_id

            # Status auflösen
            try:
                obj_status = ObjectStatus(status_str)
            except ValueError:
                obj_status = ObjectStatus.IN_BENUTZUNG

            # Objekt erstellen (mit TEMP-Nummer, wird gleich aktualisiert)
            obj = InventoryObject(
                object_type_id=type_id,
                designation=designation,
                object_number="TEMP",
                serial_number=serial_number,
                manufacturer_id=manufacturer_id,
                supplier_id=supplier_id,
                location_id=location_id,
                info_text=info_text,
                usage_hints=usage_hints,
                acquisition_date=acquisition_date,
                status=obj_status,
                inspection_required=inspection_required,
                created_by_id=user.id
            )
            db.add(obj)
            db.commit()
            db.refresh(obj)

            # Eindeutige Nummer generieren
            obj.object_number = f"FFW-{obj.id:05d}"
            db.commit()

            # QR-Code generieren
            qr_filename = generate_qr_code(obj.object_number)
            qr = QRCode(object_id=obj.id, filename=qr_filename)
            db.add(qr)
            db.commit()

            # Bis zu drei Prüffristen anlegen (alte CSV-Spalten bleiben kompatibel).
            if inspection_required and maintenance_schedules:
                create_maintenance_entries(db, obj, maintenance_schedules, acquisition_date)
                db.commit()

            # Wenn Fahrzeug -> automatisch als Standort anlegen
            # Case-insensitive Prüfung + Strip für Robustheit
            if type_name and type_name.strip().lower() == 'fahrzeug' and location_id:
                existing_loc = db.query(Location).filter(
                    Location.name == obj.designation,
                    Location.parent_id == location_id
                ).first()
                if not existing_loc:
                    vehicle_loc = Location(
                        name=obj.designation,
                        location_type='Fahrzeug',
                        parent_id=location_id,
                        linked_object_id=obj.id
                    )
                    db.add(vehicle_loc)
                    db.commit()
                    print(f"DEBUG: Fahrzeug-Standort angelegt: {obj.designation} (Parent: {location_id})")

            created_count += 1

        except Exception as e:
            errors.append(f"Zeile {row_idx}: {str(e)}")

    return {
        "created": created_count,
        "skipped": skipped_count,
        "errors": errors
    }

# --- Full Backup (ZIP with DB + Uploads) ---

@app.get("/api/export/full-backup")
def export_full_backup(user: User = Depends(require_verwaltung)):
    """Erstellt ein vollständiges ZIP-Backup mit SQLite-DB + Uploads-Ordner"""
    # Temporäres Verzeichnis
    temp_dir = tempfile.mkdtemp(prefix="feuerwehr_backup_")
    zip_path = os.path.join(temp_dir, "backup.zip")

    try:
        # Manifest erstellen
        manifest = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "exported_by": user.full_name,
            "db_file": "db/feuerwehr.db"
        }
        with open(os.path.join(temp_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # DB kopieren
        db_dir = os.path.join(temp_dir, "db")
        os.makedirs(db_dir, exist_ok=True)
        db_src = os.path.join(os.path.dirname(__file__), "..", "data", "feuerwehr.db")
        shutil.copy2(db_src, os.path.join(db_dir, "feuerwehr.db"))

        # Uploads kopieren
        uploads_src = os.path.join(os.path.dirname(__file__), "..", "uploads")
        uploads_dst = os.path.join(temp_dir, "uploads")
        if os.path.exists(uploads_src):
            shutil.copytree(uploads_src, uploads_dst)

        # ZIP erstellen
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file == "backup.zip":
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

        # ZIP zurückgeben
        return FileResponse(
            zip_path,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="feuerwehr_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip"'
            }
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Fehler beim Erstellen des Backups: {str(e)}")

@app.post("/api/import/full-backup")
async def import_full_backup(
    file: UploadFile = File(...),
    user: User = Depends(require_verwaltung)
):
    """Stellt ein vollständiges ZIP-Backup wieder her (DB + Uploads)"""
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Nur ZIP-Dateien sind erlaubt")

    # Temporäres Verzeichnis
    temp_dir = tempfile.mkdtemp(prefix="feuerwehr_restore_")

    try:
        # ZIP speichern
        zip_path = os.path.join(temp_dir, "backup.zip")
        content = await file.read()
        with open(zip_path, "wb") as f:
            f.write(content)

        # ZIP entpacken
        extract_dir = os.path.join(temp_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(extract_dir)

        # Manifest prüfen
        manifest_path = os.path.join(extract_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise HTTPException(status_code=400, detail="Ungültiges Backup: manifest.json nicht gefunden")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # DB-Datei finden
        db_src = os.path.join(extract_dir, "db", "feuerwehr.db")
        if not os.path.exists(db_src):
            # Fallback: suche nach .db Datei
            for root, dirs, files in os.walk(extract_dir):
                for file_name in files:
                    if file_name.endswith('.db'):
                        db_src = os.path.join(root, file_name)
                        break

        if not os.path.exists(db_src):
            raise HTTPException(status_code=400, detail="Keine Datenbank-Datei im Backup gefunden")

        # Pfade zur aktuellen Installation
        db_dst = os.path.join(os.path.dirname(__file__), "..", "data", "feuerwehr.db")
        uploads_dst = os.path.join(os.path.dirname(__file__), "..", "uploads")

        # Aktuelle DB sichern
        backup_db = db_dst + ".bak"
        if os.path.exists(db_dst):
            shutil.copy2(db_dst, backup_db)

        # Uploads sichern
        backup_uploads = uploads_dst + ".bak"
        if os.path.exists(uploads_dst):
            if os.path.exists(backup_uploads):
                shutil.rmtree(backup_uploads)
            shutil.copytree(uploads_dst, backup_uploads)

        # Neue DB kopieren
        shutil.copy2(db_src, db_dst)

        # Uploads kopieren
        uploads_src = os.path.join(extract_dir, "uploads")
        if os.path.exists(uploads_src):
            if os.path.exists(uploads_dst):
                shutil.rmtree(uploads_dst)
            shutil.copytree(uploads_src, uploads_dst)

        return {
            "success": True,
            "message": "Backup erfolgreich wiederhergestellt. Die Seite wird in 3 Sekunden neu geladen.",
            "manifest": manifest
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Wiederherstellen: {str(e)}")
    finally:
        # Aufräumen
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- Frontend ---

@app.get("/impressum", response_class=HTMLResponse)
async def imprint():
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Impressum – Feuerwehr Inventar</title>
            <style>
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    min-height: 100vh;
                    padding: 24px;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    color: #30343a;
                    background: #f0f2f5;
                }
                main {
                    width: min(100%, 680px);
                    margin: 6vh auto 0;
                    padding: 28px;
                    border-top: 6px solid #b71c1c;
                    border-radius: 12px;
                    background: #fff;
                    box-shadow: 0 8px 28px rgba(0,0,0,.1);
                }
                h1 { margin: 0 0 20px; color: #b71c1c; }
                h2 { margin: 24px 0 8px; font-size: 1.05rem; }
                address { font-style: normal; line-height: 1.7; }
                .back {
                    display: inline-flex;
                    margin-top: 28px;
                    padding: 10px 14px;
                    border-radius: 7px;
                    color: #fff;
                    background: #b71c1c;
                    text-decoration: none;
                    font-weight: 700;
                }
                @media (max-width: 520px) {
                    body { padding: 12px; }
                    main { margin-top: 2vh; padding: 22px 18px; }
                    .back { width: 100%; justify-content: center; }
                }
            </style>
        </head>
        <body>
            <main>
                <h1>Impressum</h1>
                <h2>Kontakt und Anschrift</h2>
                <address>
                    Julian Guckert<br>
                    Burgstr. 17A<br>
                    66459 Kirkel
                </address>
                <h2>E-Mail</h2>
                <p>jgtech.ki(at)gmail.com</p>
                <a class="back" href="/">← Zurück zur Anwendung</a>
            </main>
        </body>
        </html>
        """,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

@app.get("/api/export/inspections/{year}")
def export_inspections_by_year(year: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    """Exportiert alle Prüfungen eines Jahres als CSV-Archiv"""
    from sqlalchemy import extract

    inspections = db.query(Inspection).filter(
        extract('year', Inspection.inspected_at) == year
    ).order_by(Inspection.inspected_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')

    # Header
    writer.writerow([
        'Prüfdatum', 'Uhrzeit', 'Objekt-ID', 'Objekt-Bezeichnung', 'Objekt-Typ',
        'Prüfkarte', 'Prüfer', 'Ergebnisse', 'Nächste Prüfung', 'Bemerkungen', 'Bildkommentare'
    ])

    for i in inspections:
        obj = i.inventory_object
        # Ergebnisse als lesbaren Text formatieren
        results_str = ''
        try:
            results = json.loads(i.results)
            results_str = '; '.join([f"{k}: {'Ja' if v is True else ('Nein' if v is False else v)}" for k, v in results.items()])
        except:
            results_str = i.results or ''

        writer.writerow([
            i.inspected_at.strftime('%d.%m.%Y') if i.inspected_at else '',
            i.inspected_at.strftime('%H:%M') if i.inspected_at else '',
            obj.object_number if obj else '',
            obj.designation if obj else '',
            obj.object_type.name if obj and obj.object_type else '',
            i.template.name if i.template else '',
            i.inspector_name or (i.inspected_by.full_name if i.inspected_by else ''),
            results_str,
            i.next_inspection_date or '',
            i.notes or '',
            ' | '.join(image.comment for image in i.images)
        ])

    content = output.getvalue()
    output.close()

    content_with_bom = '\ufeff' + content
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        io.BytesIO(content_with_bom.encode('utf-8')),
        media_type='text/csv; charset=utf-8-sig',
        headers={
            'Content-Disposition': f'attachment; filename="pruefarchiv_{year}.csv"'
        }
    )

# --- PDF Prüfarchiv ---
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import zipfile

def generate_inspection_pdf(inspection, filepath):
    """Erstellt eine einzelne PDF-Prüfkarte"""
    doc = SimpleDocTemplate(filepath, pagesize=A4,
                           rightMargin=2*cm, leftMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1976d2'),
        spaceAfter=20,
        alignment=1  # Center
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#333333'),
        spaceAfter=10
    )
    
    normal_style = styles["Normal"]
    normal_style.fontSize = 10
    
    story = []
    
    # Header
    story.append(Paragraph("🚒 Feuerwehr Inventar – Prüfprotokoll", title_style))
    story.append(Spacer(1, 0.5*cm))
    
    obj = inspection.inventory_object
    template = inspection.template
    
    # Objekt-Informationen
    story.append(Paragraph("Objekt-Informationen", subtitle_style))
    
    info_data = [
        ['Objekt-ID:', obj.object_number if obj else '-'],
        ['Bezeichnung:', obj.designation if obj else '-'],
        ['Typ:', obj.object_type.name if obj and obj.object_type else '-'],
        ['Standort:', obj.location.name if obj and obj.location else '-'],
        ['Seriennummer:', obj.serial_number if obj and obj.serial_number else '-'],
    ]
    
    info_table = Table(info_data, colWidths=[4*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.5*cm))
    
    # Prüfungs-Informationen
    story.append(Paragraph("Prüfungs-Informationen", subtitle_style))
    
    check_data = [
        ['Prüfkarte:', template.name if template else '-'],
        ['Prüfdatum:', inspection.inspected_at.strftime('%d.%m.%Y %H:%M') if inspection.inspected_at else '-'],
        ['Prüfer:', inspection.inspector_name or (inspection.inspected_by.full_name if inspection.inspected_by else '-')],
        ['Nächste Prüfung:', inspection.next_inspection_date or '-'],
    ]
    
    check_table = Table(check_data, colWidths=[4*cm, 12*cm])
    check_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e3f2fd')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(check_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Prüfergebnisse
    story.append(Paragraph("Prüfergebnisse", subtitle_style))
    
    try:
        fields = json.loads(template.fields) if template else []
        results = json.loads(inspection.results) if inspection.results else {}
    except:
        fields = []
        results = {}
    
    if fields:
        result_data = [['Prüfpunkt', 'Ergebnis', 'Status']]
        for field in fields:
            label = field.get('label', '')
            value = results.get(label, '')
            
            if isinstance(value, bool):
                display = 'Ja' if value else 'Nein'
                status = '✓ OK' if value else '✗ Mangel'
                status_color = colors.HexColor('#2e7d32') if value else colors.HexColor('#c62828')
            else:
                display = str(value) if value else '-'
                status = '-'
                status_color = colors.black
            
            result_data.append([label, display, status])
        
        result_table = Table(result_data, colWidths=[8*cm, 4*cm, 4*cm])
        result_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976d2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        story.append(result_table)
    else:
        story.append(Paragraph("Keine Prüffelder vorhanden.", normal_style))
    
    story.append(Spacer(1, 0.8*cm))
    
    # Bemerkungen
    if inspection.notes:
        story.append(Paragraph("Bemerkungen", subtitle_style))
        story.append(Paragraph(inspection.notes.replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.5*cm))

    if inspection.images:
        from xml.sax.saxutils import escape as xml_escape
        story.append(Paragraph("Bilddokumentation", subtitle_style))
        for number, image in enumerate(inspection.images, 1):
            image_path = os.path.join("uploads/inspection_images", image.filename)
            if os.path.exists(image_path):
                try:
                    with Image.open(image_path) as source_image:
                        pixel_width, pixel_height = source_image.size
                    max_width = 16 * cm
                    max_height = 11 * cm
                    scale = min(max_width / pixel_width, max_height / pixel_height, 1)
                    story.append(RLImage(image_path, width=pixel_width * scale, height=pixel_height * scale))
                except Exception:
                    story.append(Paragraph(f"Bild {number} konnte nicht eingebettet werden.", normal_style))
            story.append(Paragraph(
                f"<b>Bild {number}:</b> {xml_escape(image.comment).replace(chr(10), '<br/>')}",
                normal_style
            ))
            story.append(Spacer(1, 0.5*cm))
    
    # Footer
    story.append(Spacer(1, 1*cm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1
    )
    story.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} | Feuerwehr Inventar System",
        footer_style
    ))
    
    doc.build(story)

@app.get("/api/export/inspections/{year}/pdf")
def export_inspections_pdf_by_year(year: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    """Exportiert alle Prüfungen eines Jahres als ZIP mit PDF-Dateien"""
    from sqlalchemy import extract

    inspections = db.query(Inspection).filter(
        extract('year', Inspection.inspected_at) == year
    ).order_by(Inspection.inspected_at.desc()).all()

    if not inspections:
        raise HTTPException(status_code=404, detail=f"Keine Prüfungen für das Jahr {year} gefunden")

    # Temporäres Verzeichnis erstellen
    temp_dir = f"/tmp/pruefarchiv_{year}_{uuid.uuid4().hex[:8]}"
    os.makedirs(temp_dir, exist_ok=True)

    # PDFs generieren
    for idx, inspection in enumerate(inspections, 1):
        obj = inspection.inventory_object
        obj_id = obj.object_number if obj else f"UNKNOWN_{idx}"
        date_str = inspection.inspected_at.strftime('%Y%m%d') if inspection.inspected_at else 'nodate'
        pdf_filename = f"{date_str}_{obj_id}_Pruefung_{idx:03d}.pdf"
        pdf_path = os.path.join(temp_dir, pdf_filename)
        generate_inspection_pdf(inspection, pdf_path)

    # ZIP erstellen
    zip_path = f"/tmp/pruefarchiv_{year}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join(str(year), file)
                zipf.write(file_path, arcname)

    # Aufräumen
    import shutil
    shutil.rmtree(temp_dir)

    # ZIP zurückgeben
    return FileResponse(
        zip_path,
        media_type='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="pruefarchiv_{year}.zip"'
        }
    )

# --- Messages / Dashboard ---

@app.get("/api/messages", response_model=List[MessageResponse])
def list_messages(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    """Alle Meldungen abrufen (nicht-abgeschlossene zuerst, dann nach Priorität und Datum)"""
    query = db.query(Message).filter(
        Message.status != MessageStatus.GELOESCHT,
        Message.is_archived.is_(False)
    )
    if user.role == UserRole.STANDARD:
        query = query.filter(Message.is_visible_to_standard.is_(True))
    messages = query.order_by(
        Message.is_closed.asc(),  # Nicht-abgeschlossene zuerst
        Message.priority == MessagePriority.HOCH,
        Message.priority == MessagePriority.MITTEL,
        Message.created_at.desc()
    ).all()
    return messages

@app.get("/api/messages/archive", response_model=List[MessageResponse])
def list_archived_messages(db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    """Zentrales, unveränderliches Meldungsarchiv für nicht eindeutig verknüpfte Altvorgänge."""
    return db.query(Message).filter(
        or_(Message.is_archived.is_(True), Message.status == MessageStatus.GELOESCHT)
    ).order_by(
        Message.archived_at.desc(),
        Message.updated_at.desc(),
        Message.created_at.desc()
    ).all()

@app.post("/api/messages", response_model=MessageResponse)
def create_message(data: MessageCreate, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    """Neue Meldung anlegen (alle Benutzergruppen)"""
    priority = data.priority or MessagePriority.MITTEL
    if data.message_type in [MessageType.BESCHAEDIGUNG.value, MessageType.DEFEKT.value]:
        priority = MessagePriority.HOCH

    subject = data.subject.strip()
    if not subject:
        raise HTTPException(status_code=422, detail="Bitte ein Thema für die Meldung eingeben.")
    try:
        action = MessageAction(data.action) if data.action else MessageAction.KEINE
    except ValueError:
        raise HTTPException(status_code=422, detail="Die ausgewählte Maßnahme ist ungültig.")
    action_comment = (data.action_comment or "").strip() or None
    if action == MessageAction.SONSTIGES and not action_comment:
        raise HTTPException(status_code=422, detail="Bitte die sonstige Maßnahme beschreiben.")
    if action != MessageAction.SONSTIGES:
        action_comment = None

    linked_object = None
    if data.inventory_object_id is not None:
        linked_object = db.query(InventoryObject).filter(InventoryObject.id == data.inventory_object_id).first()
        if not linked_object:
            raise HTTPException(status_code=422, detail="Der ausgewählte Inventarartikel existiert nicht mehr.")
    elif data.device_id:
        clean_device_id = data.device_id.strip().upper()
        linked_object = db.query(InventoryObject).filter(
            func.upper(InventoryObject.object_number) == clean_device_id
        ).first()
        if not linked_object and clean_device_id.startswith(("FW-", "FFW-")):
            number_part = clean_device_id.split("-", 1)[1]
            linked_object = db.query(InventoryObject).filter(
                or_(
                    func.upper(InventoryObject.object_number) == f"FFW-{number_part}",
                    func.upper(InventoryObject.object_number) == f"FW-{number_part}"
                )
            ).first()

    msg = Message(
        inventory_object_id=linked_object.id if linked_object else None,
        message_type=MessageType(data.message_type),
        subject=subject,
        device_name=data.device_name,
        device_id=data.device_id,
        description=data.description,
        action=action,
        action_comment=action_comment,
        priority=MessagePriority(priority),
        status=MessageStatus.OFFEN,
        is_closed=False,
        is_visible_to_standard=True,
        reported_by_name=data.reported_by_name,
        created_by_name=user.full_name
    )
    db.add(msg)
    db.flush()
    db.add(MessageHistory(
        message_id=msg.id,
        entry_type="status",
        status=MessageStatus.OFFEN.value,
        details="Meldung erstellt",
        author_name=(data.reported_by_name or "").strip() or user.full_name
    ))
    db.commit()
    db.refresh(msg)
    return msg

@app.get("/api/objects/{object_id}/message-history", response_model=List[MessageResponse])
def get_object_message_history(
    object_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    """Vollständige Meldungs- und Reparaturhistorie eines Inventarartikels."""
    if not db.query(InventoryObject).filter(InventoryObject.id == object_id).first():
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    return db.query(Message).filter(Message.inventory_object_id == object_id).order_by(
        Message.created_at.desc()
    ).all()

@app.post("/api/messages/{message_id}/images", response_model=MessageImageResponse)
def upload_message_image(
    message_id: int,
    comment: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_user)
):
    """Fügt einer gerade angelegten Meldung ein kommentiertes Beweisbild hinzu."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.status == MessageStatus.GELOESCHT:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    if message.created_by_name != user.full_name:
        raise HTTPException(status_code=403, detail="Bilder dürfen nur zur eigenen Meldung ergänzt werden.")
    if message.created_at < datetime.utcnow() - timedelta(hours=2):
        raise HTTPException(status_code=403, detail="Bilder können nur innerhalb von 2 Stunden ergänzt werden.")
    if db.query(MessageImage).filter(MessageImage.message_id == message_id).count() >= 8:
        raise HTTPException(status_code=400, detail="Pro Meldung können höchstens 8 Bilder hinterlegt werden.")
    clean_comment = comment.strip()
    if not clean_comment:
        raise HTTPException(status_code=422, detail="Zu jedem Bild muss ein Kommentar angegeben werden.")

    filename = save_message_image(file)
    image = MessageImage(
        message_id=message.id,
        filename=filename,
        original_name=(file.filename or "Schadensbild")[:255],
        comment=clean_comment
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image

@app.put("/api/messages/{message_id}/status", response_model=MessageResponse)
def update_message_status(message_id: int, data: MessageStatusUpdate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    """Status einer Meldung aktualisieren (erweitert, verwaltung, admin)"""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    author_name = (data.author_name or user.full_name).strip()
    if not author_name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen oder ein Kürzel angeben.")
    details = (data.details or "").strip() or None
    expected_end = datetime.combine(data.expected_end_date, datetime.min.time()) if data.expected_end_date else None
    changed = False

    if data.status:
        try:
            new_status = MessageStatus(data.status)
        except ValueError:
            raise HTTPException(status_code=422, detail="Der ausgewählte Status ist ungültig.")
        msg.status = new_status
        db.add(MessageHistory(
            message_id=msg.id,
            entry_type="status",
            status=new_status.value,
            details=details,
            expected_end_date=expected_end,
            author_name=author_name
        ))
        changed = True
    if data.is_closed is not None and data.is_closed != msg.is_closed:
        msg.is_closed = data.is_closed
        db.add(MessageHistory(
            message_id=msg.id,
            entry_type="status",
            status="abgeschlossen" if data.is_closed else "wieder_geoeffnet",
            details=details,
            expected_end_date=expected_end,
            author_name=author_name
        ))
        changed = True
    if not changed:
        raise HTTPException(status_code=422, detail="Es wurde keine Statusänderung ausgewählt.")
    msg.updated_by_name = author_name
    msg.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return msg

@app.put("/api/messages/{message_id}/visibility", response_model=MessageResponse)
def update_message_visibility(
    message_id: int,
    data: MessageVisibilityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    """Blendet eine Meldung für Standardnutzer ein oder aus."""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg or msg.status == MessageStatus.GELOESCHT:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    if msg.is_visible_to_standard != data.is_visible_to_standard:
        msg.is_visible_to_standard = data.is_visible_to_standard
        msg.updated_by_name = user.full_name
        msg.updated_at = datetime.utcnow()
        db.add(MessageHistory(
            message_id=msg.id,
            entry_type="visibility",
            details=(
                "Für Standardnutzer sichtbar gemacht"
                if data.is_visible_to_standard
                else "Für Standardnutzer ausgeblendet"
            ),
            author_name=user.full_name
        ))
        db.commit()
        db.refresh(msg)
    return msg

@app.post("/api/messages/{message_id}/comments", response_model=MessageHistoryResponse)
def add_message_comment(
    message_id: int,
    data: MessageCommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    """Fügt dem dauerhaft gespeicherten Meldungsverlauf eine datierte Anmerkung hinzu."""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg or msg.status == MessageStatus.GELOESCHT:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    comment = data.comment.strip()
    if not comment:
        raise HTTPException(status_code=422, detail="Bitte einen Kommentar eingeben.")
    author_name = (data.author_name or user.full_name).strip()
    if not author_name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen oder ein Kürzel angeben.")
    entry = MessageHistory(
        message_id=msg.id,
        entry_type="comment",
        details=comment,
        author_name=author_name
    )
    msg.updated_by_name = author_name
    msg.updated_at = datetime.utcnow()
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

@app.post("/api/messages/{message_id}/archive", response_model=MessageResponse)
def archive_message(
    message_id: int,
    data: MessageArchiveCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    """Entfernt eine Meldung aus der aktuellen Liste, ohne Verlauf oder Bilder zu löschen."""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    resolution_map = {
        "abgeschlossen": MessageStatus.ABGESCHLOSSEN,
        "entsorgt": MessageStatus.ENTSORGT,
        "weiter_in_klaerung": MessageStatus.IN_KLAERUNG
    }
    if data.resolution not in resolution_map:
        raise HTTPException(status_code=422, detail="Bitte ein gültiges Ergebnis auswählen.")
    author_name = data.author_name.strip()
    if not author_name:
        raise HTTPException(status_code=422, detail="Bitte den Namen oder das Kürzel des Abschließenden angeben.")
    comment = (data.comment or "").strip() or None
    archive_labels = {
        "abgeschlossen": "Abgeschlossen",
        "entsorgt": "Entsorgt",
        "weiter_in_klaerung": "Weiter in Klärung"
    }
    msg.status = resolution_map[data.resolution]
    msg.is_closed = data.resolution in {"abgeschlossen", "entsorgt"}
    msg.is_archived = True
    msg.archive_reason = data.resolution
    msg.archived_at = datetime.utcnow()
    msg.archived_by_name = author_name
    msg.updated_at = datetime.utcnow()
    msg.updated_by_name = author_name
    db.add(MessageHistory(
        message_id=msg.id,
        entry_type="archive",
        status=msg.status.value,
        details=(
            f"Aus den aktuellen Meldungen entfernt: {archive_labels[data.resolution]}"
            + (f" · {comment}" if comment else "")
        ),
        author_name=author_name
    ))
    db.commit()
    db.refresh(msg)
    return msg

@app.delete("/api/messages/{message_id}")
def delete_message(message_id: int, user: User = Depends(require_erweitert)):
    """Schützt Verlauf und Bilder vor dem alten Löschaufruf aus zwischengespeicherten Seiten."""
    raise HTTPException(
        status_code=409,
        detail="Meldungen werden nicht mehr gelöscht. Bitte die aktualisierte Archivierungsfunktion verwenden."
    )

@app.get("/api/export/messages-log")
def export_messages_log(db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    """Exportiert alle Meldungen als CSV-Logdatei"""
    messages = db.query(Message).order_by(Message.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')

    writer.writerow([
        'Datum', 'Uhrzeit', 'Typ', 'Thema', 'Gerät', 'Geräte-ID',
        'Beschreibung', 'Maßnahme', 'Maßnahmenkommentar', 'Bildkommentare', 'Priorität', 'Status', 'Abgeschlossen',
        'Für Standardnutzer sichtbar', 'Archiviert', 'Archivergebnis', 'Archiviert von', 'Verlauf',
        'Meldender', 'Erstellt von (Account)', 'Aktualisiert von'
    ])

    for m in messages:
        writer.writerow([
            m.created_at.strftime('%d.%m.%Y') if m.created_at else '',
            m.created_at.strftime('%H:%M') if m.created_at else '',
            m.message_type.value if m.message_type else '',
            m.subject,
            m.device_name or '',
            m.device_id or '',
            m.description or '',
            m.action.value if m.action else '',
            m.action_comment or '',
            ' | '.join(image.comment for image in m.images),
            m.priority.value if m.priority else '',
            m.status.value if m.status else '',
            'Ja' if m.is_closed else 'Nein',
            'Ja' if m.is_visible_to_standard else 'Nein',
            'Ja' if m.is_archived else 'Nein',
            m.archive_reason or '',
            m.archived_by_name or '',
            ' | '.join(
                f"{entry.created_at.strftime('%d.%m.%Y %H:%M')} - "
                f"{entry.status or 'Kommentar'}"
                f"{(' - ' + entry.details) if entry.details else ''}"
                f"{(' - vsl. ' + entry.expected_end_date.strftime('%d.%m.%Y')) if entry.expected_end_date else ''}"
                f" - {entry.author_name}"
                for entry in m.history
            ),
            m.reported_by_name or '',
            m.created_by_name,
            m.updated_by_name or ''
        ])

    content = output.getvalue()
    output.close()

    content_with_bom = '\ufeff' + content
    return StreamingResponse(
        io.BytesIO(content_with_bom.encode('utf-8')),
        media_type='text/csv; charset=utf-8-sig',
        headers={
            'Content-Disposition': f'attachment; filename="meldungslog_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        }
    )

@app.get("/health")
async def health():
    return {"status": "ok"}
