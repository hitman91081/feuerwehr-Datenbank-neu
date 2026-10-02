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


class ApiClient(Base):
    __tablename__ = "api_clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    key_prefix = Column(String, nullable=False, index=True)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    scopes = Column(String, nullable=False, default="objects:read")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_by = relationship("User")
    audit_entries = relationship("ApiAuditLog", back_populates="client", cascade="all, delete-orphan")


class ApiAuditLog(Base):
    __tablename__ = "api_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("api_clients.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    client = relationship("ApiClient", back_populates="audit_entries")

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

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    objects = relationship("InventoryObject", back_populates="supplier")

class Location(Base):
    __tablename__ = "locations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    location_type = Column(String, nullable=False)  # Fahrzeug, Gerätehaus, Lager, Raum, Platz, etc.
    linked_object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=True)  # Verknüpfung zu Objekt (z.B. Fahrzeug)
    
    parent = relationship("Location", remote_side=[id], back_populates="children")
    children = relationship("Location", back_populates="parent")
    objects = relationship("InventoryObject", foreign_keys="InventoryObject.location_id", back_populates="location")
    linked_object = relationship("InventoryObject", foreign_keys=[linked_object_id], back_populates="linked_location")

# --- Hauptobjekte ---
class InventoryObject(Base):
    __tablename__ = "inventory_objects"
    
    id = Column(Integer, primary_key=True, index=True)
    object_type_id = Column(Integer, ForeignKey("object_types.id"), nullable=False)
    designation = Column(String, nullable=False)  # Bezeichnung
    object_number = Column(String, unique=True, index=True, nullable=False)  # eindeutige ID z.B. FFW-00001
    serial_number = Column(String)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id"))
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    title_image = Column(String)  # Pfad zum Titelbild
    info_text = Column(Text)
    usage_hints = Column(Text)  # Hinweise / Tipps zur Benutzung
    acquisition_date = Column(String)  # YYYY-MM-DD
    status = Column(Enum(ObjectStatus), default=ObjectStatus.IN_BENUTZUNG, nullable=False)
    inspection_required = Column(Boolean, default=True, nullable=False)
    standard_inspection_enabled = Column(Boolean, default=False, nullable=False)
    standard_inspection_template_id = Column(Integer, ForeignKey("inspection_templates.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"))
    
    object_type = relationship("ObjectType", back_populates="objects")
    manufacturer = relationship("Manufacturer", back_populates="objects")
    supplier = relationship("Supplier", back_populates="objects")
    location = relationship("Location", foreign_keys=[location_id], back_populates="objects")
    created_by = relationship("User", back_populates="created_objects")
    linked_location = relationship("Location", foreign_keys="Location.linked_object_id", back_populates="linked_object")
    images = relationship("ObjectImage", back_populates="inventory_object", cascade="all, delete-orphan")
    maintenances = relationship("Maintenance", back_populates="inventory_object", cascade="all, delete-orphan")
    repairs = relationship("Repair", back_populates="inventory_object", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="inventory_object", cascade="all, delete-orphan")
    qr_code = relationship("QRCode", back_populates="inventory_object", uselist=False, cascade="all, delete-orphan")
    standard_inspection_template = relationship("InspectionTemplate", foreign_keys=[standard_inspection_template_id])

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
    description = Column(String, nullable=False, default="Allgemeine Prüfung / Wartung")
    interval_days = Column(Integer, nullable=False)
    last_maintenance_date = Column(String)  # YYYY-MM-DD
    next_maintenance_date = Column(String)  # YYYY-MM-DD
    notes = Column(Text)
    
    inventory_object = relationship("InventoryObject", back_populates="maintenances")
    inspections = relationship("Inspection", back_populates="maintenance")

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


class DocumentLabel(Base):
    __tablename__ = "document_labels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    documents = relationship("Document", back_populates="label")


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=True)
    label_id = Column(Integer, ForeignKey("document_labels.id"), nullable=True)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    file_type = Column(String)  # image, pdf, text, etc.
    is_public = Column(Boolean, default=True)  # Für Standardnutzer sichtbar?
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"))
    
    inventory_object = relationship("InventoryObject", back_populates="documents")
    label = relationship("DocumentLabel", back_populates="documents")
    uploaded_by = relationship("User", back_populates="uploaded_documents")

class QRCode(Base):
    __tablename__ = "qr_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False, unique=True)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    inventory_object = relationship("InventoryObject", back_populates="qr_code")

# --- Prüfkarten ---
class InspectionTemplate(Base):
    __tablename__ = "inspection_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    fields = Column(Text, nullable=False)  # JSON: [{"label": "Visueller Zustand", "type": "checkbox", "required": true}, ...]
    object_type_id = Column(Integer, ForeignKey("object_types.id"), nullable=True)
    default_interval_days = Column(Integer, nullable=True)
    allow_standard_users = Column(Boolean, default=False)  # Für Standardnutzer sichtbar?
    created_at = Column(DateTime, default=datetime.utcnow)

    object_type = relationship("ObjectType", back_populates="inspection_templates")
    inspections = relationship("Inspection", back_populates="template")

class Inspection(Base):
    __tablename__ = "inspections"
    
    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("inspection_templates.id"), nullable=False)
    maintenance_id = Column(Integer, ForeignKey("maintenances.id"), nullable=True)
    inspected_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    inspector_name = Column(String)  # Tatsächlicher Prüfer, wichtig bei gemeinsamem QR-Login
    inspected_at = Column(DateTime, default=datetime.utcnow)
    results = Column(Text, nullable=False)  # JSON: {"Visueller Zustand": true, "Druck": "12 bar", ...}
    next_inspection_date = Column(String)  # YYYY-MM-DD
    notes = Column(Text)
    
    inventory_object = relationship("InventoryObject", back_populates="inspections")
    template = relationship("InspectionTemplate", back_populates="inspections")
    maintenance = relationship("Maintenance", back_populates="inspections")
    inspected_by = relationship("User", back_populates="inspections")
    images = relationship("InspectionImage", back_populates="inspection", cascade="all, delete-orphan")

class InspectionImage(Base):
    __tablename__ = "inspection_images"

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("inspections.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_name = Column(String)
    comment = Column(Text, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="images")

# --- Meldungen / Dashboard ---
class MessageType(str, enum.Enum):
    BESCHAEDIGUNG = "beschaedigung"
    AUFFAELLIGKEIT = "auffaelligkeit"
    DEFEKT = "defekt"
    INFO = "info"
    NOTIZ = "notiz"
    SONSTIGES = "sonstiges"

class MessageAction(str, enum.Enum):
    KEINE = "keine"
    AUSSER_BETRIEB = "ausser_betrieb"
    AUF_FAHRZEUG = "auf_fahrzeug"
    IN_WERKSTATT = "in_werkstatt"
    ENTSORGT = "entsorgt"
    SONSTIGES = "sonstiges"

class MessagePriority(str, enum.Enum):
    HOCH = "hoch"
    MITTEL = "mittel"
    NIEDRIG = "niedrig"

class MessageStatus(str, enum.Enum):
    OFFEN = "offen"
    IN_BEARBEITUNG = "in_bearbeitung"
    IN_KLAERUNG = "in_klaerung"
    ZUR_REPARATUR = "zur_reparatur"
    BEDIENUNGSFEHLER = "bedienungsfehler"
    NICHT_MEHR_AUFGETRETEN = "nicht_mehr_aufgetreten"
    GEPRUEFT_OK = "geprueft_ok"
    ENTSORGT = "entsorgt"
    ABGESCHLOSSEN = "abgeschlossen"
    GELOESCHT = "geloescht"

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    inventory_object_id = Column(Integer, ForeignKey("inventory_objects.id"), index=True)
    message_type = Column(Enum(MessageType), nullable=False)
    subject = Column(String, nullable=False)
    device_name = Column(String)
    device_id = Column(String)
    description = Column(Text)
    action = Column(Enum(MessageAction), default=MessageAction.KEINE)
    action_comment = Column(Text)
    priority = Column(Enum(MessagePriority), default=MessagePriority.MITTEL)
    status = Column(Enum(MessageStatus), default=MessageStatus.OFFEN)
    is_closed = Column(Boolean, default=False)  # Separates "Abgeschlossen"-Flag
    is_visible_to_standard = Column(Boolean, default=True, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    archive_reason = Column(String)
    archived_at = Column(DateTime)
    archived_by_name = Column(String)
    reported_by_name = Column(String)  # Name des eigentlichen Meldenden (z.B. bei Standard-Login)
    created_by_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_name = Column(String)
    images = relationship("MessageImage", back_populates="message", cascade="all, delete-orphan")
    inventory_object = relationship("InventoryObject", back_populates="messages")
    history = relationship(
        "MessageHistory",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageHistory.created_at.asc()"
    )

class MessageImage(Base):
    __tablename__ = "message_images"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_name = Column(String)
    comment = Column(Text, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="images")

class MessageHistory(Base):
    __tablename__ = "message_history_entries"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    entry_type = Column(String, nullable=False)  # status, comment oder visibility
    status = Column(String)
    details = Column(Text)
    expected_end_date = Column(DateTime)
    author_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    message = relationship("Message", back_populates="history")

# Beziehungen zu bestehenden Modellen ergänzen
ObjectType.inspection_templates = relationship("InspectionTemplate", back_populates="object_type")
InventoryObject.inspections = relationship("Inspection", back_populates="inventory_object", cascade="all, delete-orphan", order_by="Inspection.inspected_at.desc()")
InventoryObject.messages = relationship("Message", back_populates="inventory_object", order_by="Message.created_at.desc()")
User.inspections = relationship("Inspection", back_populates="inspected_by")
