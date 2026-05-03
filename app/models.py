from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Float, Enum
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime
import enum

class UserRole(str, enum.Enum):
    STANDARD = "standard"
    ERWEITERT = "erweitert"
    VERWALTUNG = "verwaltung"
    ADMIN = "admin"

class ObjectStatus(str, enum.Enum):
    IN_BENUTZUNG = "in_benutzung"
    IN_REPARATUR = "in_reparatur"
    AUSGEMUSTERT = "ausgemustert"
    RESERVE = "reserve"
    ZUR_REINIGUNG = "zur_reinigung"

# --- Benutzer ---
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.STANDARD, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    created_objects = relationship("InventoryObject", back_populates="created_by")
    uploaded_documents = relationship("Document", back_populates="uploaded_by")

# --- Stammdaten ---
class ObjectType(Base):
    __tablename__ = "object_types"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)  # Fahrzeug, Gebrauchsgegenstand, Verbrauchsgegenstand, Ausrüstung
    
    objects = relationship("InventoryObject", back_populates="object_type")

class Manufacturer(Base):
    __tablename__ = "manufacturers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    
    objects = relationship("InventoryObject", back_populates="manufacturer")

class Location(Base):
    __tablename__ = "locations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    location_type = Column(String, nullable=False)  # Fahrzeug, Gerätehaus, Lager, Raum, Platz, etc.
    
    parent = relationship("Location", remote_side=[id], back_populates="children")
    children = relationship("Location", back_populates="parent")
    objects = relationship("InventoryObject", back_populates="location")

# --- Hauptobjekte ---
class InventoryObject(Base):
    __tablename__ = "inventory_objects"
    
    id = Column(Integer, primary_key=True, index=True)
    object_type_id = Column(Integer, ForeignKey("object_types.id"), nullable=False)
    designation = Column(String, nullable=False)  # Bezeichnung
    object_number = Column(String, unique=True, index=True, nullable=False)  # eindeutige ID z.B. FFW-00001
    serial_number = Column(String)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    title_image = Column(String)  # Pfad zum Titelbild
    info_text = Column(Text)
    usage_hints = Column(Text)  # Hinweise / Tipps zur Benutzung
    acquisition_date = Column(String)  # YYYY-MM-DD
    status = Column(Enum(ObjectStatus), default=ObjectStatus.IN_BENUTZUNG, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"))
    
    object_type = relationship("ObjectType", back_populates="objects")
    manufacturer = relationship("Manufacturer", back_populates="objects")
    location = relationship("Location", back_populates="objects")
    created_by = relationship("User", back_populates="created_objects")
    images = relationship("ObjectImage", back_populates="inventory_object", cascade="all, delete-orphan")
    maintenances = relationship("Maintenance", back_populates="inventory_object", cascade="all, delete-orphan")
    repairs = relationship("Repair", back_populates="inventory_object", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="inventory_object", cascade="all, delete-orphan")
    qr_code = relationship("QRCode", back_populates="inventory_object", uselist=False, cascade="all, delete-orphan")

class ObjectImage(Base):
    __tablename__ = "object_images"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False)
    filename = Column(String, nullable=False)
    caption = Column(String)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    inventory_object = relationship("InventoryObject", back_populates="images")

class Maintenance(Base):
    __tablename__ = "maintenances"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False)
    interval_days = Column(Integer, nullable=False)
    last_maintenance_date = Column(String)  # YYYY-MM-DD
    next_maintenance_date = Column(String)  # YYYY-MM-DD
    notes = Column(Text)
    
    inventory_object = relationship("InventoryObject", back_populates="maintenances")

class Repair(Base):
    __tablename__ = "repairs"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    description = Column(Text, nullable=False)
    cost = Column(Float)
    performed_by = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    inventory_object = relationship("InventoryObject", back_populates="repairs")

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    file_type = Column(String)  # image, pdf, text, etc.
    is_public = Column(Boolean, default=True)  # Für Standardnutzer sichtbar?
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"))
    
    inventory_object = relationship("InventoryObject", back_populates="documents")
    uploaded_by = relationship("User", back_populates="uploaded_documents")

class QRCode(Base):
    __tablename__ = "qr_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False, unique=True)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    inventory_object = relationship("InventoryObject", back_populates="qr_code")
