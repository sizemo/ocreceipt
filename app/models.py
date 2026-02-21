from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    sales_tax_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    raw_ocr_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReceiptImage(Base):
    __tablename__ = "receipt_images"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), unique=True, index=True)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadJob(Base):
    __tablename__ = "upload_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued", index=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())




class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="upload")
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    password_salt: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="view")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    theme_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstanceSetting(Base):
    __tablename__ = "instance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    visual_accessibility_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
