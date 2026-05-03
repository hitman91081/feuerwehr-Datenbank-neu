import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db, engine, Base
from app.models import (
    User, UserRole, ObjectType, Manufacturer, Location, InventoryObject,
    ObjectImage, Maintenance, Repair, Document, QRCode, ObjectStatus,
    InspectionTemplate, Inspection
)
from app.schemas import (
    Token, UserLogin, UserCreate, UserResponse, UserUpdate,
    ObjectTypeCreate, ObjectTypeResponse, ManufacturerCreate, ManufacturerResponse,
    LocationCreate, LocationResponse, InventoryObjectCreate, InventoryObjectUpdate,
    InventoryObjectPublicResponse, InventoryObjectFullResponse,
    MaintenanceCreate, MaintenanceResponse, RepairCreate, RepairResponse,
    DocumentResponse, SearchResult, QRCodeResponse,
    InspectionTemplateCreate, InspectionTemplateResponse, InspectionCreate, InspectionResponse
)
from app.auth import (
    verify_password, create_access_token, get_current_user,
    require_admin, require_verwaltung, require_erweitert, require_any_user,
    get_password_hash, create_default_admin
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
    # Standard-Stammdaten anlegen
    if not db.query(ObjectType).first():
        for name in [
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
            "Sonstiges"
        ]:
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
                fields=json.dumps(t["fields"])
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
    return db.query(Location).filter(Location.parent_id == None).all()

@app.post("/api/locations", response_model=LocationResponse)
def create_location(data: LocationCreate, db: Session = Depends(get_db), user: User = Depends(require_erweitert)):
    loc = Location(name=data.name, location_type=data.location_type, parent_id=data.parent_id)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc

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
            location_name=obj.location.name if obj.location else None
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
            location_name=obj.location.name if obj.location else None
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
            location_name=obj.location.name if obj.location else None
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
            qr_code=QRCodeResponse(id=obj.qr_code.id, filename=obj.qr_code.filename, created_at=obj.qr_code.created_at) if obj.qr_code else None
        )
    
    return InventoryObjectFullResponse.model_validate(obj)

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
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)
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

# --- QR Code & Sticker ---

@app.get("/api/objects/{object_id}/qr")
def get_qr_code(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj or not obj.qr_code:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    return FileResponse(f"uploads/qrcodes/{obj.qr_code.filename}")

@app.get("/api/objects/{object_id}/sticker")
def get_sticker(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    sticker_path = f"uploads/qrcodes/sticker_{obj.object_number}.png"
    if not os.path.exists(sticker_path):
        generate_sticker(obj.object_number, obj.designation)
    return FileResponse(sticker_path)

@app.get("/api/objects/{object_id}/sticker/print", response_class=HTMLResponse)
def print_sticker(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    sticker_path = f"uploads/qrcodes/sticker_{obj.object_number}.png"
    if not os.path.exists(sticker_path):
        generate_sticker(obj.object_number, obj.designation)
    
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
            <img src="/uploads/qrcodes/sticker_{obj.object_number}.png" alt="Aufkleber">
        </div>
    </body>
    </html>
    """
    return html

# --- Prüfkarten & Prüfungen ---

@app.get("/api/inspection-templates", response_model=List[InspectionTemplateResponse])
def list_templates(db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    return db.query(InspectionTemplate).all()

@app.post("/api/inspection-templates", response_model=InspectionTemplateResponse)
def create_template(data: InspectionTemplateCreate, db: Session = Depends(get_db), user: User = Depends(require_verwaltung)):
    import json
    template = InspectionTemplate(
        name=data.name,
        description=data.description,
        fields=json.dumps([f.model_dump() for f in data.fields]),
        object_type_id=data.object_type_id
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template

@app.get("/api/objects/{object_id}/inspections", response_model=List[InspectionResponse])
def get_inspections(object_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_user)):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    inspections = db.query(Inspection).filter(Inspection.object_id == object_id).order_by(Inspection.inspected_at.desc()).all()
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
    user: User = Depends(require_erweitert)
):
    obj = db.query(InventoryObject).filter(InventoryObject.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
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

# --- Frontend ---

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
async def health():
    return {"status": "ok"}
