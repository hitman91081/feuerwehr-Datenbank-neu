import os
import shutil
import uuid
import json
import zipfile
import tempfile
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db, engine, Base
from app.models import (
    User, UserRole, ObjectType, Manufacturer, Location, InventoryObject,
    ObjectImage, Maintenance, Repair, Document, QRCode, ObjectStatus,
    InspectionTemplate, Inspection,
    Message, MessageType, MessageAction, MessagePriority, MessageStatus
)
from app.schemas import (
    Token, UserLogin, UserCreate, UserResponse, UserUpdate,
    ObjectTypeCreate, ObjectTypeResponse, ManufacturerCreate, ManufacturerResponse,
    LocationCreate, LocationResponse, InventoryObjectCreate, InventoryObjectUpdate,
    InventoryObjectPublicResponse, InventoryObjectFullResponse,
    MaintenanceCreate, MaintenanceResponse, RepairCreate, RepairResponse,
    DocumentResponse, SearchResult, QRCodeResponse, ObjectImageResponse,
    InspectionTemplateCreate, InspectionTemplateResponse, InspectionCreate, InspectionResponse,
    MessageCreate, MessageStatusUpdate, MessageResponse
)
from app.auth import (
    verify_password, create_access_token, get_current_user,
    require_admin, require_verwaltung, require_erweitert, require_any_user,
    get_password_hash, create_default_admin, create_default_standard_user
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

# Upload-Verzeichnisse sicherstellen
for d in ["uploads/images", "uploads/documents", "uploads/qrcodes"]:
    os.makedirs(d, exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Default-Admin erstellen (beim ersten Start)
@app.on_event("startup")
def startup():
    db = next(get_db())
    create_default_admin(db)
    create_default_standard_user(db)
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
    
    # Standard-Prüfkarten anlegen
    if not db.query(InspectionTemplate).first():
        import json
        templates = [
            {
                "name": "Feuerlöscher – jährliche Prüfung",
                "description": "Jährliche Prüfung von Feuerlöschern nach DIN 14406",
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
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Benutzername bereits vergeben")
    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        hashed_password=get_password_hash(data.password),
        role=data.role,
        is_active=data.is_active
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    for key, value in data.model_dump(exclude_unset=True).items():
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

# --- Stammdaten ---

@app.get("/api/object-types", response_model=List[ObjectTypeResponse])
def list_object_types(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(ObjectType).all()

@app.post("/api/object-types", response_model=ObjectTypeResponse)
def create_object_type(data: ObjectTypeCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    ot = ObjectType(name=data.name)
    db.add(ot)
    db.commit()
    db.refresh(ot)
    return ot

@app.get("/api/manufacturers", response_model=List[ManufacturerResponse])
def list_manufacturers(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(Manufacturer).all()

@app.post("/api/manufacturers", response_model=ManufacturerResponse)
def create_manufacturer(data: ManufacturerCreate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    m = Manufacturer(name=data.name)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m

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
    loc = Location(name=data.name, location_type=data.location_type, parent_id=data.parent_id)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc

@app.delete("/api/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Standort nicht gefunden")
    # Prüfe ob Standorte untergeordnet sind
    children = db.query(Location).filter(Location.parent_id == location_id).count()
    if children > 0:
        raise HTTPException(status_code=400, detail="Standort hat untergeordnete Standorte und kann nicht gelöscht werden")
    # Prüfe ob Objekte diesem Standort zugeordnet sind
    objects_count = db.query(InventoryObject).filter(InventoryObject.location_id == location_id).count()
    if objects_count > 0:
        raise HTTPException(status_code=400, detail=f"Standort ist {objects_count} Objekt(en) zugeordnet und kann nicht gelöscht werden")
    db.delete(loc)
    db.commit()
    return {"ok": True}

# --- Standort-Objekte (rekursiv) ---

def get_all_sub_location_ids(db: Session, location_id: int) -> List[int]:
    """Gibt alle Location-IDs inkl. Unterlocations zurück"""
    ids = [location_id]
    children = db.query(Location).filter(Location.parent_id == location_id).all()
    for child in children:
        ids.extend(get_all_sub_location_ids(db, child.id))
    return ids

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

@app.post("/api/objects", response_model=InventoryObjectFullResponse)
def create_object(
    data: InventoryObjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = InventoryObject(
        object_type_id=data.object_type_id,
        designation=data.designation,
        object_number="TEMP",  # Wird gleich aktualisiert
        serial_number=data.serial_number,
        manufacturer_id=data.manufacturer_id,
        location_id=data.location_id,
        info_text=data.info_text,
        usage_hints=data.usage_hints,
        acquisition_date=data.acquisition_date,
        status=data.status,
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

    # Wartung anlegen falls angegeben
    if data.maintenance_interval_days:
        next_date = None
        if data.acquisition_date:
            d = datetime.strptime(data.acquisition_date, "%Y-%m-%d") + timedelta(days=data.maintenance_interval_days)
            next_date = d.strftime("%Y-%m-%d")
        maint = Maintenance(
            object_id=obj.id,
            interval_days=data.maintenance_interval_days,
            last_maintenance_date=data.acquisition_date,
            next_maintenance_date=next_date,
            notes=data.maintenance_notes
        )
        db.add(maint)
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
        # Filtere Prüfungen: nur von für Standardnutzer freigegebenen Templates
        public_inspections = []
        for i in obj.inspections:
            if i.template and i.template.allow_standard_users:
                public_inspections.append(InspectionResponse(
                    id=i.id,
                    object_id=i.object_id,
                    template_id=i.template_id,
                    template_name=i.template.name if i.template else None,
                    inspected_by_name=i.inspected_by.full_name if i.inspected_by else None,
                    inspected_at=i.inspected_at,
                    results=i.results,
                    next_inspection_date=i.next_inspection_date,
                    notes=i.notes
                ))
        return InventoryObjectPublicResponse(
            id=obj.id,
            object_type=ObjectTypeResponse(id=obj.object_type.id, name=obj.object_type.name) if obj.object_type else None,
            designation=obj.designation,
            object_number=obj.object_number,
            manufacturer=ManufacturerResponse(id=obj.manufacturer.id, name=obj.manufacturer.name) if obj.manufacturer else None,
            location=LocationResponse(id=obj.location.id, name=obj.location.name, location_type=obj.location.location_type, parent_id=obj.location.parent_id) if obj.location else None,
            title_image=obj.title_image,
            info_text=obj.info_text,
            usage_hints=obj.usage_hints,
            documents=[DocumentResponse.model_validate(d) for d in public_docs],
            inspections=public_inspections,
            qr_code=QRCodeResponse(id=obj.qr_code.id, filename=obj.qr_code.filename, created_at=obj.qr_code.created_at) if obj.qr_code else None
        )
    
    # Vollständige Antwort mit aufgelösten Inspections
    inspections = []
    for i in obj.inspections:
        inspections.append(InspectionResponse(
            id=i.id,
            object_id=i.object_id,
            template_id=i.template_id,
            template_name=i.template.name if i.template else None,
            inspected_by_name=i.inspected_by.full_name if i.inspected_by else None,
            inspected_at=i.inspected_at,
            results=i.results,
            next_inspection_date=i.next_inspection_date,
            notes=i.notes
        ))
    
    return InventoryObjectFullResponse(
        id=obj.id,
        object_type=ObjectTypeResponse(id=obj.object_type.id, name=obj.object_type.name) if obj.object_type else None,
        designation=obj.designation,
        object_number=obj.object_number,
        serial_number=obj.serial_number,
        manufacturer=ManufacturerResponse(id=obj.manufacturer.id, name=obj.manufacturer.name) if obj.manufacturer else None,
        location=LocationResponse(id=obj.location.id, name=obj.location.name, location_type=obj.location.location_type, parent_id=obj.location.parent_id) if obj.location else None,
        title_image=obj.title_image,
        info_text=obj.info_text,
        usage_hints=obj.usage_hints,
        acquisition_date=obj.acquisition_date,
        status=obj.status,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        images=[ObjectImageResponse.model_validate(img) for img in obj.images],
        maintenances=[MaintenanceResponse.model_validate(m) for m in obj.maintenances],
        repairs=[RepairResponse.model_validate(r) for r in obj.repairs],
        documents=[DocumentResponse.model_validate(d) for d in obj.documents],
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
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)

    # Wartung aktualisieren oder neu anlegen
    if data.maintenance_interval_days is not None:
        existing_maint = db.query(Maintenance).filter(Maintenance.object_id == object_id).first()
        next_date = None
        if data.acquisition_date:
            d = datetime.strptime(data.acquisition_date, "%Y-%m-%d") + timedelta(days=data.maintenance_interval_days)
            next_date = d.strftime("%Y-%m-%d")
        if existing_maint:
            existing_maint.interval_days = data.maintenance_interval_days
            existing_maint.notes = data.maintenance_notes
            if data.acquisition_date:
                existing_maint.last_maintenance_date = data.acquisition_date
                existing_maint.next_maintenance_date = next_date
        else:
            maint = Maintenance(
                object_id=obj.id,
                interval_days=data.maintenance_interval_days,
                last_maintenance_date=data.acquisition_date,
                next_maintenance_date=next_date,
                notes=data.maintenance_notes
            )
            db.add(maint)
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
    maint = Maintenance(**data.model_dump(), object_id=object_id)
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

@app.post("/api/objects/{object_id}/documents")
def upload_document(
    object_id: int,
    is_public: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    filename = save_upload(file, "uploads/documents")
    doc = Document(
        object_id=object_id,
        filename=filename,
        original_name=file.filename,
        file_type=determine_file_type(file.filename),
        is_public=is_public,
        uploaded_by_id=user.id
    )
    db.add(doc)
    db.commit()
    return {"ok": True, "filename": filename}

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
        <title>QR-Login Aufkleber</title>
        <style>
            body {{ margin: 0; padding: 20px; font-family: sans-serif; text-align: center; }}
            .sticker {{ border: 2px dashed #ccc; padding: 20px; display: inline-block; max-width: 400px; }}
            .sticker img {{ width: 200px; height: 200px; }}
            .sticker h3 {{ margin: 0.5rem 0; color: #333; }}
            .sticker p {{ color: #666; font-size: 0.9rem; margin: 0.3rem 0; }}
            .sticker .url {{ font-family: monospace; background: #f5f5f5; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; }}
            @media print {{
                body {{ padding: 0; }}
                .no-print {{ display: none; }}
                .sticker {{ border: none; box-shadow: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print" style="margin-bottom: 20px;">
            <button onclick="window.print()">🖨️ Drucken</button>
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

@app.get("/api/objects/{object_id}/sticker/print", response_class=HTMLResponse)
def print_sticker(object_id: int, db: Session = Depends(get_db)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    sticker_path = f"uploads/qrcodes/sticker_{obj.object_number}.png"
    # Sticker immer neu generieren, damit Bezeichnung aktuell ist
    generate_sticker(obj.object_number, obj.designation)
    
    import time
    ts = int(time.time())
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Aufkleber {obj.object_number}</title>
        <style>
            body {{ margin: 0; padding: 20px; font-family: sans-serif; text-align: center; }}
            .sticker {{ border: 2px dashed #ccc; padding: 20px; display: inline-block; }}
            img {{ max-width: 100%; height: auto; }}
            @media print {{
                body {{ padding: 0; }}
                .no-print {{ display: none; }}
                .sticker {{ border: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print" style="margin-bottom: 20px;">
            <button onclick="window.print()">🖨️ Drucken</button>
            <p>Empfohlene Aufkleber-Größe: 50 x 25 mm</p>
        </div>
        <div class="sticker">
            <img src="/uploads/qrcodes/sticker_{obj.object_number}.png?t={ts}" alt="Aufkleber">
        </div>
    </body>
    </html>
    """
    return html

# --- Prüfkarten & Prüfungen ---

@app.get("/api/inspection-templates", response_model=List[InspectionTemplateResponse])
def list_templates(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    query = db.query(InspectionTemplate)
    # Standardnutzer sehen nur für sie freigegebene Prüfkarten
    if user.role == UserRole.STANDARD:
        query = query.filter(InspectionTemplate.allow_standard_users == True)
    return query.all()

@app.post("/api/inspection-templates", response_model=InspectionTemplateResponse)
def create_template(data: InspectionTemplateCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    import json
    template = InspectionTemplate(
        name=data.name,
        description=data.description,
        fields=json.dumps([f.model_dump() for f in data.fields]),
        object_type_id=data.object_type_id,
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
    return t

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
    t.allow_standard_users = data.allow_standard_users
    db.commit()
    db.refresh(t)
    return t

@app.get("/api/objects/{object_id}/inspections", response_model=List[InspectionResponse])
def get_inspections(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    query = db.query(Inspection).filter(Inspection.object_id == object_id)
    # Standardnutzer sehen nur Prüfungen mit für sie freigegebenen Templates
    if user.role == UserRole.STANDARD:
        query = query.join(InspectionTemplate).filter(InspectionTemplate.allow_standard_users == True)
    inspections = query.order_by(Inspection.inspected_at.desc()).all()
    result = []
    for i in inspections:
        result.append(InspectionResponse(
            id=i.id,
            object_id=i.object_id,
            template_id=i.template_id,
            template_name=i.template.name if i.template else None,
            inspected_by_name=i.inspected_by.full_name if i.inspected_by else None,
            inspected_at=i.inspected_at,
            results=i.results,
            next_inspection_date=i.next_inspection_date,
            notes=i.notes
        ))
    return result

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

    # Prüfe ob Template für Standardnutzer erlaubt ist
    template = db.query(InspectionTemplate).filter(InspectionTemplate.id == data.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
    if user.role == UserRole.STANDARD and not template.allow_standard_users:
        raise HTTPException(status_code=403, detail="Diese Prüfkarte ist für Standardnutzer nicht verfügbar")

    import json
    inspection = Inspection(
        object_id=object_id,
        template_id=data.template_id,
        inspected_by_id=user.id,
        results=json.dumps(data.results),
        next_inspection_date=data.next_inspection_date,
        notes=data.notes
    )
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return InspectionResponse(
        id=inspection.id,
        object_id=inspection.object_id,
        template_id=inspection.template_id,
        template_name=inspection.template.name if inspection.template else None,
        inspected_by_name=inspection.inspected_by.full_name if inspection.inspected_by else None,
        inspected_at=inspection.inspected_at,
        results=inspection.results,
        next_inspection_date=inspection.next_inspection_date,
        notes=inspection.notes
    )

@app.get("/api/inspections/{inspection_id}", response_model=InspectionResponse)
def get_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    i = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")
    # Standardnutzer dürfen nur Prüfungen mit für sie freigegebenen Templates sehen
    if user.role == UserRole.STANDARD and (not i.template or not i.template.allow_standard_users):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    return InspectionResponse(
        id=i.id,
        object_id=i.object_id,
        template_id=i.template_id,
        template_name=i.template.name if i.template else None,
        inspected_by_name=i.inspected_by.full_name if i.inspected_by else None,
        inspected_at=i.inspected_at,
        results=i.results,
        next_inspection_date=i.next_inspection_date,
        notes=i.notes
    )

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

    # Standardnutzer dürfen nur Prüfungen mit für sie freigegebenen Templates bearbeiten
    if user.role == UserRole.STANDARD and (not i.template or not i.template.allow_standard_users):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    import json
    i.results = json.dumps(data.results)
    i.next_inspection_date = data.next_inspection_date
    i.notes = data.notes
    db.commit()
    db.refresh(i)
    return InspectionResponse(
        id=i.id,
        object_id=i.object_id,
        template_id=i.template_id,
        template_name=i.template.name if i.template else None,
        inspected_by_name=i.inspected_by.full_name if i.inspected_by else None,
        inspected_at=i.inspected_at,
        results=i.results,
        next_inspection_date=i.next_inspection_date,
        notes=i.notes
    )

@app.delete("/api/inspections/{inspection_id}")
def delete_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    i = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Prüfung nicht gefunden")
    db.delete(i)
    db.commit()
    return {"ok": True}

@app.delete("/api/inspection-templates/{template_id}")
def delete_inspection_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    t = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Prüfkarte nicht gefunden")
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
        'Bezeichnung', 'Typ', 'Seriennummer', 'Hersteller',
        'Standort', 'Infotext', 'Hinweise', 'Anschaffungsdatum',
        'Status', 'Prüfintervall_Tage', 'Prüfnotizen'
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
        writer.writerow([
            obj.designation,
            obj.object_type.name if obj.object_type else '',
            obj.serial_number or '',
            obj.manufacturer.name if obj.manufacturer else '',
            get_location_path(obj.location),
            obj.info_text or '',
            obj.usage_hints or '',
            obj.acquisition_date or '',
            obj.status.value if obj.status else '',
            obj.maintenances[0].interval_days if obj.maintenances else '',
            obj.maintenances[0].notes if obj.maintenances else ''
        ])

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

    # Stammdaten laden (für Lookup)
    types = {t.name: t.id for t in db.query(ObjectType).all()}
    manufacturers = {m.name: m.id for m in db.query(Manufacturer).all()}
    locations = {l.name: l.id for l in db.query(Location).all()}

    created_count = 0
    skipped_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=2):
        if not row or not row[0].strip():
            continue

        try:
            designation = row[0].strip()
            type_name = row[1].strip()
            serial_number = row[2].strip() or None
            manufacturer_name = row[3].strip()
            location_name = row[4].strip()
            info_text = row[5].strip() or None
            usage_hints = row[6].strip() or None
            acquisition_date = row[7].strip() or None
            status_str = row[8].strip() or 'in_benutzung'
            interval_days = int(row[9].strip()) if len(row) > 9 and row[9].strip() else None
            maint_notes = row[10].strip() if len(row) > 10 else None

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
                location_id=location_id,
                info_text=info_text,
                usage_hints=usage_hints,
                acquisition_date=acquisition_date,
                status=obj_status,
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

            # Wartung/Prüfintervall anlegen falls angegeben
            if interval_days:
                next_date = None
                if acquisition_date:
                    d = datetime.strptime(acquisition_date, "%Y-%m-%d") + timedelta(days=interval_days)
                    next_date = d.strftime("%Y-%m-%d")
                maint = Maintenance(
                    object_id=obj.id,
                    interval_days=interval_days,
                    last_maintenance_date=acquisition_date,
                    next_maintenance_date=next_date,
                    notes=maint_notes
                )
                db.add(maint)
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

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

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
        'Prüfkarte', 'Prüfer', 'Ergebnisse', 'Nächste Prüfung', 'Bemerkungen'
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
            i.inspected_by.full_name if i.inspected_by else '',
            results_str,
            i.next_inspection_date or '',
            i.notes or ''
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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
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
        ['Prüfer:', inspection.inspected_by.full_name if inspection.inspected_by else '-'],
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
    messages = db.query(Message).filter(Message.status != MessageStatus.GELOESCHT).order_by(
        Message.is_closed.asc(),  # Nicht-abgeschlossene zuerst
        Message.priority == MessagePriority.HOCH,
        Message.priority == MessagePriority.MITTEL,
        Message.created_at.desc()
    ).all()
    return messages

@app.post("/api/messages", response_model=MessageResponse)
def create_message(data: MessageCreate, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    """Neue Meldung anlegen (alle Benutzergruppen)"""
    priority = data.priority or MessagePriority.MITTEL
    if data.message_type in [MessageType.BESCHAEDIGUNG.value, MessageType.DEFEKT.value]:
        priority = MessagePriority.HOCH

    msg = Message(
        message_type=MessageType(data.message_type),
        subject=data.subject,
        device_name=data.device_name,
        device_id=data.device_id,
        description=data.description,
        action=MessageAction(data.action) if data.action else MessageAction.SONSTIGES,
        priority=MessagePriority(priority),
        status=MessageStatus.OFFEN,
        is_closed=False,
        reported_by_name=data.reported_by_name,
        created_by_name=user.full_name
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg

@app.put("/api/messages/{message_id}/status", response_model=MessageResponse)
def update_message_status(message_id: int, data: MessageStatusUpdate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    """Status einer Meldung aktualisieren (erweitert, verwaltung, admin)"""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    if data.status:
        msg.status = MessageStatus(data.status)
    if data.is_closed is not None:
        msg.is_closed = data.is_closed
    msg.updated_by_name = user.full_name
    db.commit()
    db.refresh(msg)
    return msg

@app.delete("/api/messages/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    """Meldung löschen (erweitert, verwaltung, admin)"""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    msg.status = MessageStatus.GELOESCHT
    db.commit()
    return {"ok": True}

@app.get("/api/export/messages-log")
def export_messages_log(db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    """Exportiert alle Meldungen als CSV-Logdatei"""
    messages = db.query(Message).order_by(Message.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')

    writer.writerow([
        'Datum', 'Uhrzeit', 'Typ', 'Thema', 'Gerät', 'Geräte-ID',
        'Beschreibung', 'Maßnahme', 'Priorität', 'Status', 'Abgeschlossen',
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
            m.priority.value if m.priority else '',
            m.status.value if m.status else '',
            'Ja' if m.is_closed else 'Nein',
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
