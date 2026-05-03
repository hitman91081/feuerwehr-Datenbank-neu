from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models import UserRole, ObjectStatus

# --- Auth Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserBase(BaseModel):
    username: str
    full_name: str
    email: Optional[str] = None
    role: UserRole = UserRole.STANDARD
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class UserResponse(UserBase):
    id: int
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# --- Stammdaten Schemas ---
class ObjectTypeBase(BaseModel):
    name: str

class ObjectTypeCreate(ObjectTypeBase):
    pass

class ObjectTypeResponse(ObjectTypeBase):
    id: int
    class Config:
        from_attributes = True

class ManufacturerBase(BaseModel):
    name: str

class ManufacturerCreate(ManufacturerBase):
    pass

class ManufacturerResponse(ManufacturerBase):
    id: int
    class Config:
        from_attributes = True

class LocationBase(BaseModel):
    name: str
    location_type: str
    parent_id: Optional[int] = None

class LocationCreate(LocationBase):
    pass

class LocationResponse(LocationBase):
    id: int
    children: List["LocationResponse"] = []
    class Config:
        from_attributes = True

# --- Object Schemas ---
class ObjectImageResponse(BaseModel):
    id: int
    filename: str
    caption: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class MaintenanceResponse(BaseModel):
    id: int
    interval_days: int
    last_maintenance_date: Optional[str] = None
    next_maintenance_date: Optional[str] = None
    notes: Optional[str] = None
    class Config:
        from_attributes = True

class RepairResponse(BaseModel):
    id: int
    date: str
    description: str
    cost: Optional[float] = None
    performed_by: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class DocumentResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    file_type: Optional[str] = None
    is_public: bool = True
    uploaded_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class QRCodeResponse(BaseModel):
    id: int
    filename: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# --- Inspection Schemas ---
class InspectionField(BaseModel):
    label: str
    type: str  # checkbox, text, number, select, textarea
    required: bool = False
    options: Optional[List[str]] = None  # Für select

class InspectionTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    fields: List[InspectionField]
    object_type_id: Optional[int] = None

class InspectionTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    fields: str  # JSON string
    object_type_id: Optional[int] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class InspectionCreate(BaseModel):
    template_id: int
    results: dict
    next_inspection_date: Optional[str] = None
    notes: Optional[str] = None

class InspectionResponse(BaseModel):
    id: int
    object_id: int
    template_id: int
    template_name: Optional[str] = None
    inspected_by_name: Optional[str] = None
    inspected_at: Optional[datetime] = None
    results: str  # JSON string
    next_inspection_date: Optional[str] = None
    notes: Optional[str] = None
    class Config:
        from_attributes = True

# Öffentliches Schema (Standardnutzer)
class InventoryObjectPublicResponse(BaseModel):
    id: int
    object_type: Optional[ObjectTypeResponse] = None
    designation: str
    object_number: str
    manufacturer: Optional[ManufacturerResponse] = None
    location: Optional[LocationResponse] = None
    title_image: Optional[str] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    documents: List[DocumentResponse] = []
    qr_code: Optional[QRCodeResponse] = None
    class Config:
        from_attributes = True

# Volles Schema (Admin, Verwaltung, Erweitert)
class InventoryObjectFullResponse(BaseModel):
    id: int
    object_type: Optional[ObjectTypeResponse] = None
    designation: str
    object_number: str
    serial_number: Optional[str] = None
    manufacturer: Optional[ManufacturerResponse] = None
    location: Optional[LocationResponse] = None
    title_image: Optional[str] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    images: List[ObjectImageResponse] = []
    maintenances: List[MaintenanceResponse] = []
    repairs: List[RepairResponse] = []
    documents: List[DocumentResponse] = []
    inspections: List[InspectionResponse] = []
    qr_code: Optional[QRCodeResponse] = None
    class Config:
        from_attributes = True

class InventoryObjectCreate(BaseModel):
    object_type_id: int
    designation: str
    serial_number: Optional[str] = None
    manufacturer_id: Optional[int] = None
    location_id: Optional[int] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus = ObjectStatus.IN_BENUTZUNG
    maintenance_interval_days: Optional[int] = None
    maintenance_notes: Optional[str] = None

class InventoryObjectUpdate(BaseModel):
    object_type_id: Optional[int] = None
    designation: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer_id: Optional[int] = None
    location_id: Optional[int] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: Optional[ObjectStatus] = None

class MaintenanceCreate(BaseModel):
    interval_days: int
    last_maintenance_date: Optional[str] = None
    next_maintenance_date: Optional[str] = None
    notes: Optional[str] = None

class RepairCreate(BaseModel):
    date: str
    description: str
    cost: Optional[float] = None
    performed_by: Optional[str] = None

class DocumentUpload(BaseModel):
    is_public: bool = True

class SearchResult(BaseModel):
    id: int
    designation: str
    object_number: str
    object_type: Optional[str] = None
    status: Optional[str] = None
    title_image: Optional[str] = None
    location_name: Optional[str] = None
    location_id: Optional[int] = None
    class Config:
        from_attributes = True
