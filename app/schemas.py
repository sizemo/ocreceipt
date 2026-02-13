from datetime import date, datetime

from pydantic import BaseModel, Field


class ReceiptOut(BaseModel):
    id: int
    merchant: str | None
    purchase_date: date | None
    total_amount: float | None
    sales_tax_amount: float | None
    extraction_confidence: float | None
    needs_review: bool
    raw_ocr_text: str
    created_at: datetime | None
    image_url: str | None = None

    model_config = {"from_attributes": True}


class ReceiptUpdate(BaseModel):
    merchant: str | None = None
    purchase_date: date | None = None
    total_amount: float | None = None
    sales_tax_amount: float | None = None


class ReceiptReviewUpdate(BaseModel):
    reviewed: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    role: str


class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class SettingsOut(BaseModel):
    default_currency: str


class SettingsUpdate(BaseModel):
    default_currency: str = Field(min_length=3, max_length=3)


class InstanceResetRequest(BaseModel):
    confirm: str
