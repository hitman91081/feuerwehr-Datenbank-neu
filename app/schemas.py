from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import date, datetime
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

class SupplierBase(BaseModel):
    name: str

class SupplierCreate(SupplierBase):
    pass

class SupplierResponse(SupplierBase):
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
    linked_object_id: Optional[int] = None
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
    description: str = "Allgemeine Prüfung / Wartung"
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
    object_id: Optional[int] = None
    object_number: Optional[str] = None
    object_designation: Optional[str] = None
    label_id: Optional[int] = None
    label_name: Optional[str] = None
    filename: str
    original_name: str
    file_type: Optional[str] = None
    is_public: bool = True
    uploaded_at: Optional[datetime] = None
    uploaded_by_name: Optional[str] = None
    class Config:
        from_attributes = True


class DocumentLabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DocumentLabelResponse(BaseModel):
    id: int
    name: str
    is_default: bool = False
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


class DocumentUpdate(BaseModel):
    label_id: Optional[int] = None
    is_public: Optional[bool] = None

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
    default_interval_days: Optional[int] = Field(default=None, ge=1, le=36500)
    allow_standard_users: bool = False

class InspectionTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    fields: str  # JSON string
    object_type_id: Optional[int] = None
    default_interval_days: Optional[int] = None
    allow_standard_users: bool = False
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class InspectionCreate(BaseModel):
    template_id: int
    maintenance_id: Optional[int] = None
    inspector_name: str = Field(min_length=1, max_length=200)
    results: dict
    next_inspection_date: Optional[str] = None
    notes: Optional[str] = None

class InspectionImageResponse(BaseModel):
    id: int
    filename: str
    original_name: Optional[str] = None
    comment: str
    uploaded_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class InspectionResponse(BaseModel):
    id: int
    object_id: int
    template_id: int
    template_name: Optional[str] = None
    maintenance_id: Optional[int] = None
    maintenance_description: Optional[str] = None
    inspected_by_name: Optional[str] = None
    inspector_name: Optional[str] = None
    inspected_at: Optional[datetime] = None
    results: str  # JSON string
    next_inspection_date: Optional[str] = None
    notes: Optional[str] = None
    images: List[InspectionImageResponse] = []
    class Config:
        from_attributes = True

class InspectionDueItem(BaseModel):
    object_id: int
    object_number: str
    designation: str
    serial_number: Optional[str] = None
    object_type: Optional[str] = None
    location_id: Optional[int] = None
    location_name: Optional[str] = None
    object_status: str
    source: str
    template_id: Optional[int] = None
    maintenance_id: Optional[int] = None
    inspection_name: str
    due_date: str
    days_until: int
    last_inspection_date: Optional[datetime] = None
    last_inspected_by: Optional[str] = None
    notes: Optional[str] = None

class InspectionCenterResponse(BaseModel):
    start_date: str
    end_date: str
    include_overdue: bool
    summary: Dict[str, int]
    items: List[InspectionDueItem]

# Öffentliches Schema (Standardnutzer)
class InventoryObjectPublicResponse(BaseModel):
    id: int
    object_type: Optional[ObjectTypeResponse] = None
    designation: str
    object_number: str
    manufacturer: Optional[ManufacturerResponse] = None
    supplier: Optional[SupplierResponse] = None
    location: Optional[LocationResponse] = None
    title_image: Optional[str] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus
    inspection_required: bool = True
    standard_inspection_enabled: bool = False
    standard_inspection_template_id: Optional[int] = None
    documents: List[DocumentResponse] = []
    inspections: List[InspectionResponse] = []
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
    supplier: Optional[SupplierResponse] = None
    location: Optional[LocationResponse] = None
    title_image: Optional[str] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus
    inspection_required: bool = True
    standard_inspection_enabled: bool = False
    standard_inspection_template_id: Optional[int] = None
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

class MaintenanceCreate(BaseModel):
    id: Optional[int] = None
    description: str = Field(min_length=1, max_length=120)
    interval_days: int = Field(ge=1, le=36500)
    last_maintenance_date: Optional[str] = None
    next_maintenance_date: Optional[str] = None
    notes: Optional[str] = None

class InventoryObjectCreate(BaseModel):
    object_type_id: int
    designation: str
    serial_number: Optional[str] = None
    manufacturer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    location_id: Optional[int] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus = ObjectStatus.IN_BENUTZUNG
    inspection_required: bool = True
    standard_inspection_enabled: bool = False
    standard_inspection_template_id: Optional[int] = None
    maintenance_schedules: Optional[List[MaintenanceCreate]] = Field(default=None, max_length=3)
    maintenance_interval_days: Optional[int] = None
    maintenance_notes: Optional[str] = None

class InventoryObjectUpdate(BaseModel):
    object_type_id: Optional[int] = None
    designation: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    location_id: Optional[int] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: Optional[ObjectStatus] = None
    inspection_required: Optional[bool] = None
    standard_inspection_enabled: Optional[bool] = None
    standard_inspection_template_id: Optional[int] = None
    maintenance_schedules: Optional[List[MaintenanceCreate]] = Field(default=None, max_length=3)
    maintenance_interval_days: Optional[int] = None
    maintenance_notes: Optional[str] = None

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


# --- Externe API & Sammelanlage ---
class ApiClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: List[str] = Field(default_factory=lambda: ["objects:read"])


class ApiClientResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class ApiClientCreatedResponse(ApiClientResponse):
    api_key: str


class ExternalObjectCreate(BaseModel):
    designation: str = Field(min_length=1, max_length=250)
    object_type: str = Field(min_length=1, max_length=200)
    serial_number: Optional[str] = Field(default=None, max_length=250)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    supplier: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=500)
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus = ObjectStatus.IN_BENUTZUNG
    inspection_required: bool = True
    maintenance_schedules: List[MaintenanceCreate] = Field(default_factory=list, max_length=3)
    create_missing_master_data: bool = False


class ExternalObjectResponse(BaseModel):
    id: int
    object_number: str
    designation: str
    serial_number: Optional[str] = None
    object_type: Optional[str] = None
    manufacturer: Optional[str] = None
    supplier: Optional[str] = None
    location: Optional[str] = None
    status: str
    acquisition_date: Optional[str] = None
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    inspection_required: bool
    maintenance_schedules: List[MaintenanceResponse] = Field(default_factory=list)
    inspection_count: int = 0
    open_message_count: int = 0


class ExternalObjectListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ExternalObjectResponse]


class BulkObjectCreateRequest(BaseModel):
    quantity: int = Field(ge=1, le=100)
    designation: str = Field(min_length=1, max_length=250)
    object_type_id: int
    manufacturer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    location_id: Optional[int] = None
    acquisition_date: Optional[str] = None
    status: ObjectStatus = ObjectStatus.IN_BENUTZUNG
    info_text: Optional[str] = None
    usage_hints: Optional[str] = None
    inspection_required: bool = True
    maintenance_schedules: List[MaintenanceCreate] = Field(default_factory=list, max_length=3)
    generate_serial_numbers: bool = True
    serial_prefix: str = Field(default="", max_length=100)
    serial_start: int = Field(default=1, ge=0, le=999999999)
    serial_padding: int = Field(default=0, ge=0, le=12)
    serial_suffix: str = Field(default="", max_length=100)


class BulkObjectPreviewItem(BaseModel):
    position: int
    designation: str
    serial_number: Optional[str] = None


class BulkObjectPreviewResponse(BaseModel):
    count: int
    items: List[BulkObjectPreviewItem]
    warnings: List[str] = Field(default_factory=list)


class BulkObjectCreateResponse(BaseModel):
    created_count: int
    objects: List[SearchResult]

# --- Message Schemas ---
class MessageCreate(BaseModel):
    inventory_object_id: Optional[int] = None
    message_type: str
    subject: str
    device_name: Optional[str] = None
    device_id: Optional[str] = None
    description: Optional[str] = None
    action: Optional[str] = None
    action_comment: Optional[str] = None
    priority: Optional[str] = None
    reported_by_name: Optional[str] = None

class MessageStatusUpdate(BaseModel):
    status: Optional[str] = None
    is_closed: Optional[bool] = None
    details: Optional[str] = None
    expected_end_date: Optional[date] = None
    author_name: Optional[str] = None

class MessageVisibilityUpdate(BaseModel):
    is_visible_to_standard: bool

class MessageCommentCreate(BaseModel):
    comment: str
    author_name: Optional[str] = None

class MessageArchiveCreate(BaseModel):
    resolution: str
    author_name: str
    comment: Optional[str] = None

class MessageImageResponse(BaseModel):
    id: int
    filename: str
    original_name: Optional[str] = None
    comment: str
    uploaded_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class MessageHistoryResponse(BaseModel):
    id: int
    entry_type: str
    status: Optional[str] = None
    details: Optional[str] = None
    expected_end_date: Optional[datetime] = None
    author_name: str
    created_at: datetime
    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    inventory_object_id: Optional[int] = None
    message_type: str
    subject: str
    device_name: Optional[str] = None
    device_id: Optional[str] = None
    description: Optional[str] = None
    action: Optional[str] = None
    action_comment: Optional[str] = None
    priority: str
    status: str
    is_closed: bool = False
    is_visible_to_standard: bool = True
    is_archived: bool = False
    archive_reason: Optional[str] = None
    archived_at: Optional[datetime] = None
    archived_by_name: Optional[str] = None
    reported_by_name: Optional[str] = None
    created_by_name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by_name: Optional[str] = None
    images: List[MessageImageResponse] = []
    history: List[MessageHistoryResponse] = []
    class Config:
        from_attributes = True
