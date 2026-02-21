import csv
import io
import os
import re
import shutil
import secrets
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageOps

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .auth import create_session, delete_session, get_user_by_session_token, hash_api_token, hash_password, verify_password
from .database import Base, engine, get_db
from .models import ApiToken, InstanceSetting, Merchant, Receipt, ReceiptImage, UploadJob, User, UserSession
from .ocr import extract_receipt_fields, get_pdf_page_count, render_pdf_preview_image, run_ocr, run_ocr_pdf
from .schemas import (
    InstanceResetRequest,
    LoginRequest,
    UploadJobOut,
    ReceiptOut,
    ReceiptReviewUpdate,
    ReceiptUpdate,
    SettingsOut,
    SettingsUpdate,
    UserCreate,
    UserOut,
    UserPasswordUpdate,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    ThemeUpdate,
)

app = FastAPI(title="Receipt OCR API", version="1.0.0")
STATIC_DIR = Path(__file__).parent / "static"
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(Path(__file__).parent / "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "ocreceipt_session")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "strict").strip().lower()
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
PROXY_TRUSTED_HOSTS = os.getenv("PROXY_TRUSTED_HOSTS", "127.0.0.1,::1")
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "change-me-now")
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "8"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
LOGIN_RATE_LIMIT_BLOCK_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_BLOCK_SECONDS", "900"))

if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    SESSION_COOKIE_SAMESITE = "strict"

if SESSION_COOKIE_SAMESITE == "none" and not SESSION_COOKIE_SECURE:
    raise RuntimeError("SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true")

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_BLOCKED_UNTIL: dict[str, float] = {}
_LOGIN_LOCK = threading.Lock()
_UPLOAD_QUEUE: list[int] = []
_UPLOAD_QUEUE_LOCK = threading.Lock()
_UPLOAD_QUEUE_COND = threading.Condition(_UPLOAD_QUEUE_LOCK)
_UPLOAD_WORKER_STOP = threading.Event()
_UPLOAD_WORKER_THREAD: threading.Thread | None = None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if FORCE_HTTPS:
            host = (request.url.hostname or "").lower()
            is_local_host = host in {"localhost", "127.0.0.1", "::1"}
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if not is_local_host and proto != "https":
                return JSONResponse(status_code=400, content={"detail": "HTTPS is required"})

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self';"
        if FORCE_HTTPS:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=PROXY_TRUSTED_HOSTS)
app.add_middleware(SecurityHeadersMiddleware)

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")



@app.get("/health")
def health_check():
    return {"status": "ok"}


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    user = get_user_by_session_token(db, session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.get("/admin-panel", include_in_schema=False)
def admin_page(_: User = Depends(require_admin)):
    return FileResponse(STATIC_DIR / "admin.html")

def _get_user_from_upload_token(db: Session, raw_token: str) -> User | None:
    token_hash = hash_api_token(raw_token)
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash, ApiToken.revoked == False))
    if token is None:
        return None

    # Only support upload-scoped tokens for now.
    if (token.scope or '').strip().lower() != 'upload':
        return None

    user = db.scalar(select(User).where(User.id == token.created_by_user_id, User.is_active == True))
    if user is None or user.role != 'admin':
        return None

    token.last_used_at = datetime.now(timezone.utc)
    db.add(token)
    db.commit()
    return user


def require_upload_auth(
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    # Prefer normal cookie session when present.
    user = get_user_by_session_token(db, session_token) if session_token else None
    if user is not None:
        if user.role != 'admin':
            raise HTTPException(status_code=403, detail='Admin required')
        return user

    # Otherwise allow a Bearer token for uploads.
    if not authorization:
        raise HTTPException(status_code=401, detail='Authentication required')

    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise HTTPException(status_code=401, detail='Invalid Authorization header')

    raw = parts[1].strip()
    if not raw:
        raise HTTPException(status_code=401, detail='Invalid token')

    user = _get_user_from_upload_token(db, raw)
    if user is None:
        raise HTTPException(status_code=401, detail='Invalid token')
    return user




@app.post("/auth/login")
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    throttle_key = f"{_get_client_ip(request)}:{username}"
    _enforce_login_rate_limit(throttle_key)

    user = db.scalar(select(User).where(func.lower(User.username) == username, User.is_active == True))
    if user is None or not verify_password(payload.password, user.password_salt, user.password_hash):
        _record_failed_login(throttle_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _clear_failed_login(throttle_key)
    session_token = create_session(db, user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )
    return {"id": user.id, "username": user.username, "role": user.role}


@app.post("/auth/logout")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    delete_session(db, session_token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/auth/me")
def auth_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    setting = _get_or_create_settings(db)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "theme": user.theme_preference or "midnight",
        "default_currency": setting.default_currency,
        "visual_accessibility_enabled": bool(setting.visual_accessibility_enabled),
    }


@app.on_event("startup")
def _start_upload_worker() -> None:
    global _UPLOAD_WORKER_THREAD
    if _UPLOAD_WORKER_THREAD and _UPLOAD_WORKER_THREAD.is_alive():
        return

    _UPLOAD_WORKER_STOP.clear()
    _UPLOAD_WORKER_THREAD = threading.Thread(target=_upload_worker_loop, name="upload-worker", daemon=True)
    _UPLOAD_WORKER_THREAD.start()
    _requeue_incomplete_upload_jobs()


@app.on_event("shutdown")
def _stop_upload_worker() -> None:
    _UPLOAD_WORKER_STOP.set()
    with _UPLOAD_QUEUE_COND:
        _UPLOAD_QUEUE_COND.notify_all()

    global _UPLOAD_WORKER_THREAD
    if _UPLOAD_WORKER_THREAD and _UPLOAD_WORKER_THREAD.is_alive():
        _UPLOAD_WORKER_THREAD.join(timeout=2)
    _UPLOAD_WORKER_THREAD = None




@app.patch("/users/me/theme")
def update_my_theme(payload: ThemeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    theme = (payload.theme or "").strip().lower()
    if theme == "dark":
        theme = "midnight"
    if theme not in {"light", "midnight", "oled"}:
        raise HTTPException(status_code=400, detail="Invalid theme")

    user.theme_preference = theme
    db.add(user)
    db.commit()
    return {"theme": theme}
@app.get("/settings", response_model=SettingsOut)
def get_settings(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    setting = _get_or_create_settings(db)
    return SettingsOut(
        default_currency=setting.default_currency,
        visual_accessibility_enabled=bool(setting.visual_accessibility_enabled),
    )


@app.post("/receipts/upload", response_model=UploadJobOut, status_code=202)
async def upload_receipt(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_upload_auth)):
    content_type = (file.content_type or "").lower()
    original_name = file.filename or "receipt"
    is_pdf = content_type == "application/pdf" or Path(original_name).suffix.lower() == ".pdf"
    is_image = content_type.startswith("image/")

    if not is_image and not is_pdf:
        raise HTTPException(status_code=400, detail="Only image and PDF uploads are supported")

    uploaded_bytes = await file.read()
    if not uploaded_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if is_pdf:
        saved_bytes = uploaded_bytes
        saved_content_type = "application/pdf"
        saved_name = f"{Path(original_name).stem}.pdf"
    else:
        saved_bytes, saved_content_type, saved_name = _normalize_upload_image(uploaded_bytes, original_name, content_type)

    queue_filename = _save_upload_queue_file(saved_name, saved_bytes)
    job = UploadJob(
        status="queued",
        original_filename=original_name,
        stored_filename=queue_filename,
        content_type=saved_content_type,
        created_by_user_id=user.id,
        error_message=None,
    )

    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as exc:
        db.rollback()
        _delete_receipt_image(queue_filename)
        raise HTTPException(status_code=500, detail=f"Failed to create upload job: {exc}") from exc

    _enqueue_upload_job(job.id)
    return _serialize_upload_job(job)


@app.get("/upload-jobs/{job_id}", response_model=UploadJobOut)
def get_upload_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_upload_auth)):
    stmt = select(UploadJob).where(UploadJob.id == job_id)
    if user.role != "admin":
        stmt = stmt.where(UploadJob.created_by_user_id == user.id)

    job = db.scalar(stmt)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload job not found")
    return _serialize_upload_job(job)


@app.get("/receipts", response_model=list[ReceiptOut])
def list_receipts(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    merchant: str | None = Query(default=None, max_length=200),
    reviewed: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Receipt)

    if date_from is not None:
        stmt = stmt.where(Receipt.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Receipt.purchase_date <= date_to)

    merchant_filter = (merchant or "").strip()
    if merchant_filter:
        stmt = stmt.where(Receipt.merchant.ilike(f"%{merchant_filter}%"))

    if reviewed is not None:
        stmt = stmt.where(Receipt.needs_review == (not reviewed))

    receipts = db.scalars(stmt.order_by(Receipt.created_at.desc())).all()
    if not receipts:
        return []

    receipt_ids = [receipt.id for receipt in receipts]
    image_ids = set(db.scalars(select(ReceiptImage.receipt_id).where(ReceiptImage.receipt_id.in_(receipt_ids))).all())

    return [_serialize_receipt(receipt, has_image=receipt.id in image_ids) for receipt in receipts]


@app.patch("/receipts/{receipt_id}", response_model=ReceiptOut)
def update_receipt(
    receipt_id: int,
    payload: ReceiptUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id))
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    if "merchant" in updates:
        receipt.merchant = _normalize_merchant(updates["merchant"])
    if "purchase_date" in updates:
        receipt.purchase_date = updates["purchase_date"]
    if "total_amount" in updates:
        receipt.total_amount = _as_decimal(updates["total_amount"])
    if "sales_tax_amount" in updates:
        receipt.sales_tax_amount = _as_decimal(updates["sales_tax_amount"])

    receipt.needs_review = False

    try:
        if receipt.merchant:
            _upsert_merchant(db, receipt.merchant)
        db.commit()
        db.refresh(receipt)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update receipt: {exc}") from exc

    has_image = db.scalar(select(ReceiptImage.id).where(ReceiptImage.receipt_id == receipt.id)) is not None
    return _serialize_receipt(receipt, has_image=has_image)


@app.patch("/receipts/{receipt_id}/review", response_model=ReceiptOut)
def update_receipt_review(
    receipt_id: int,
    payload: ReceiptReviewUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id))
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")

    receipt.needs_review = not payload.reviewed

    try:
        db.commit()
        db.refresh(receipt)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update review status: {exc}") from exc

    has_image = db.scalar(select(ReceiptImage.id).where(ReceiptImage.receipt_id == receipt.id)) is not None
    return _serialize_receipt(receipt, has_image=has_image)


@app.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id))
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")

    image = db.scalar(select(ReceiptImage).where(ReceiptImage.receipt_id == receipt_id))
    filename = image.stored_filename if image else None

    try:
        db.delete(receipt)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete receipt: {exc}") from exc

    if filename:
        _delete_receipt_image(filename)

    return {"status": "deleted", "receipt_id": receipt_id}


@app.get("/merchants")
def list_merchants(
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    search = query.strip().lower()

    stmt = select(Receipt.merchant).where(Receipt.merchant.is_not(None))
    raw_names = db.scalars(stmt).all()

    deduped: dict[str, str] = {}
    for raw_name in raw_names:
        name = (raw_name or "").strip()
        if not name:
            continue

        key = name.lower()
        if search and not key.startswith(search):
            continue

        if key not in deduped:
            deduped[key] = name

    names = [deduped[key] for key in sorted(deduped.keys())[:limit]]
    return {"merchants": names}


def _get_receipt_image_record(db: Session, receipt_id: int) -> tuple[ReceiptImage, Path]:
    image = db.scalar(select(ReceiptImage).where(ReceiptImage.receipt_id == receipt_id))
    if image is None:
        raise HTTPException(status_code=404, detail="Receipt image not found")

    image_path = UPLOADS_DIR / image.stored_filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Stored receipt image file is missing")

    return image, image_path


def _is_pdf_receipt_image(image: ReceiptImage, image_path: Path) -> bool:
    content_type = (image.content_type or "").lower()
    return content_type == "application/pdf" or image_path.suffix.lower() == ".pdf"


@app.get("/receipts/{receipt_id}/preview")
def get_receipt_preview(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    image, image_path = _get_receipt_image_record(db, receipt_id)

    if not _is_pdf_receipt_image(image, image_path):
        return {
            "kind": "image",
            "page_count": 1,
            "image_url": f"/receipts/{receipt_id}/preview-image",
            "pages": [f"/receipts/{receipt_id}/preview-image"],
        }

    pdf_bytes = image_path.read_bytes()
    page_count = get_pdf_page_count(pdf_bytes)
    if page_count <= 0:
        raise HTTPException(status_code=404, detail="PDF contains no pages")

    pages = [f"/receipts/{receipt_id}/pdf-page/{idx}" for idx in range(1, page_count + 1)]
    return {
        "kind": "pdf",
        "page_count": page_count,
        "image_url": pages[0],
        "pages": pages,
    }


@app.get("/receipts/{receipt_id}/preview-image")
def get_receipt_preview_image(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    image, image_path = _get_receipt_image_record(db, receipt_id)

    if _is_pdf_receipt_image(image, image_path):
        try:
            preview = render_pdf_preview_image(image_path.read_bytes(), page_index=0)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to render PDF preview: {exc}") from exc
        return Response(content=preview, media_type="image/png")

    return FileResponse(image_path, media_type=image.content_type or "application/octet-stream")


@app.get("/receipts/{receipt_id}/pdf-page/{page_number}")
def get_receipt_pdf_page(
    receipt_id: int,
    page_number: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if page_number < 1:
        raise HTTPException(status_code=400, detail="page_number must be >= 1")

    image, image_path = _get_receipt_image_record(db, receipt_id)
    if not _is_pdf_receipt_image(image, image_path):
        raise HTTPException(status_code=400, detail="Receipt is not a PDF")

    pdf_bytes = image_path.read_bytes()
    page_count = get_pdf_page_count(pdf_bytes)
    if page_number > page_count:
        raise HTTPException(status_code=404, detail="PDF page not found")

    try:
        rendered = render_pdf_preview_image(pdf_bytes, page_index=page_number - 1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {exc}") from exc

    return Response(content=rendered, media_type="image/png")


@app.get("/receipts/{receipt_id}/image")
def get_receipt_image(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    image, image_path = _get_receipt_image_record(db, receipt_id)
    return FileResponse(image_path, media_type=image.content_type or "application/octet-stream")


@app.get("/receipts/export")
def export_receipts_csv(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    merchant: str | None = Query(default=None, max_length=200),
    reviewed: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Receipt)

    if date_from is not None:
        stmt = stmt.where(Receipt.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Receipt.purchase_date <= date_to)
    if merchant:
        stmt = stmt.where(func.lower(Receipt.merchant) == merchant.strip().lower())
    if reviewed is not None:
        stmt = stmt.where(Receipt.needs_review == (not reviewed))

    receipts = db.scalars(stmt.order_by(Receipt.created_at.asc())).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "merchant",
        "purchase_date",
        "total_amount",
        "sales_tax_amount",
        "extraction_confidence",
        "needs_review",
        "created_at",
    ])

    for receipt in receipts:
        writer.writerow([
            receipt.id,
            receipt.merchant,
            receipt.purchase_date.isoformat() if receipt.purchase_date else "",
            f"{receipt.total_amount:.2f}" if receipt.total_amount is not None else "",
            f"{receipt.sales_tax_amount:.2f}" if receipt.sales_tax_amount is not None else "",
            f"{receipt.extraction_confidence:.2f}" if receipt.extraction_confidence is not None else "",
            "yes" if receipt.needs_review else "no",
            receipt.created_at.isoformat() if receipt.created_at else "",
        ])

    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="receipts_export.csv"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)




@app.get("/admin/api-tokens", response_model=list[ApiTokenOut])
def admin_list_api_tokens(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    tokens = db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc())).all()
    return [
        ApiTokenOut(
            id=t.id,
            name=t.name,
            scope=t.scope,
            token_prefix=t.token_prefix,
            revoked=bool(t.revoked),
            created_at=t.created_at,
            last_used_at=t.last_used_at,
        )
        for t in tokens
    ]


@app.post("/admin/api-tokens", response_model=ApiTokenCreated)
def admin_create_api_token(payload: ApiTokenCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    name = (payload.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Name is required')

    scope = (payload.scope or 'upload').strip().lower()
    if scope != 'upload':
        raise HTTPException(status_code=400, detail='Only upload-scoped tokens are supported')

    import secrets

    raw = 'ocrt_' + secrets.token_urlsafe(48)
    token_hash = hash_api_token(raw)
    token_prefix = raw[:10]

    token = ApiToken(
        name=name,
        scope=scope,
        token_hash=token_hash,
        token_prefix=token_prefix,
        created_by_user_id=admin.id,
        revoked=False,
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    meta = ApiTokenOut(
        id=token.id,
        name=token.name,
        scope=token.scope,
        token_prefix=token.token_prefix,
        revoked=bool(token.revoked),
        created_at=token.created_at,
        last_used_at=token.last_used_at,
    )
    return ApiTokenCreated(token=raw, token_meta=meta)


@app.patch("/admin/api-tokens/{token_id}/revoke")
def admin_revoke_api_token(token_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    token = db.scalar(select(ApiToken).where(ApiToken.id == token_id))
    if token is None:
        raise HTTPException(status_code=404, detail='Token not found')
    token.revoked = True
    db.add(token)
    db.commit()
    return {"status": "revoked", "token_id": token_id}
@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.scalars(select(User).order_by(User.created_at.asc())).all()
    return [UserOut(id=u.id, username=u.username, role=u.role, is_active=u.is_active, created_at=u.created_at) for u in users]


@app.post("/admin/users", response_model=UserOut)
def admin_create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    role = payload.role.strip().lower()
    if role not in {"admin", "view"}:
        raise HTTPException(status_code=400, detail="Role must be admin or view")

    username = payload.username.strip().lower()
    if not re.match(r"^[a-z0-9_.-]{3,120}$", username):
        raise HTTPException(status_code=400, detail="Username must be 3-120 chars: a-z, 0-9, _, ., -")

    exists = db.scalar(select(User.id).where(func.lower(User.username) == username))
    if exists is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    salt, digest = hash_password(payload.password)
    user = User(username=username, password_salt=salt, password_hash=digest, role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, username=user.username, role=user.role, is_active=user.is_active, created_at=user.created_at)


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.delete(user)
    db.commit()
    return {"status": "deleted", "user_id": user_id}


@app.patch("/admin/users/{user_id}/password")
def admin_update_user_password(
    user_id: int,
    payload: UserPasswordUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    salt, digest = hash_password(payload.password)
    user.password_salt = salt
    user.password_hash = digest
    db.commit()
    return {"status": "password_updated", "user_id": user_id}


@app.get("/admin/settings", response_model=SettingsOut)
def admin_get_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    setting = _get_or_create_settings(db)
    return SettingsOut(
        default_currency=setting.default_currency,
        visual_accessibility_enabled=bool(setting.visual_accessibility_enabled),
    )


@app.patch("/admin/settings", response_model=SettingsOut)
def admin_update_settings(payload: SettingsUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    currency = payload.default_currency.strip().upper()
    if not re.match(r"^[A-Z]{3}$", currency):
        raise HTTPException(status_code=400, detail="default_currency must be a 3-letter currency code")

    setting = _get_or_create_settings(db)
    setting.default_currency = currency
    setting.visual_accessibility_enabled = bool(payload.visual_accessibility_enabled)
    db.commit()
    db.refresh(setting)
    return SettingsOut(
        default_currency=setting.default_currency,
        visual_accessibility_enabled=bool(setting.visual_accessibility_enabled),
    )


@app.post("/admin/reset-instance")
def admin_reset_instance(
    payload: InstanceResetRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if payload.confirm.strip().upper() != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation value must be DELETE")

    db.execute(delete(ReceiptImage))
    db.execute(delete(Receipt))
    db.execute(delete(Merchant))
    db.execute(delete(UserSession).where(UserSession.user_id != admin.id))
    db.execute(delete(User).where(User.id != admin.id))

    setting = _get_or_create_settings(db)
    setting.default_currency = "USD"
    setting.visual_accessibility_enabled = True
    db.commit()

    if UPLOADS_DIR.exists():
        for item in UPLOADS_DIR.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)

    return {"status": "instance_reset"}


def _as_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid numeric value: {value}") from exc


def _normalize_merchant(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _upsert_merchant(db: Session, name: str) -> None:
    normalized = _normalize_merchant(name)
    if not normalized:
        return

    existing = db.scalar(select(Merchant.id).where(func.lower(Merchant.name) == normalized.lower()))
    if existing is None:
        db.add(Merchant(name=normalized))


def _normalize_upload_image(uploaded_bytes: bytes, original_name: str, content_type: str | None) -> tuple[bytes, str | None, str]:
    """Normalize images so previews do not depend on EXIF orientation.

    Many phone photos store the "real" pixels rotated and rely on EXIF orientation for display.
    Browsers often honor EXIF, but PIL/OpenCV and some viewers might not. We transpose on upload
    and re-encode to strip EXIF so OCR and UI see the same upright image.
    """

    try:
        img = Image.open(io.BytesIO(uploaded_bytes))
        img = ImageOps.exif_transpose(img)

        ext = Path(original_name or '').suffix.lower()
        is_png = (content_type or '').lower() == 'image/png' or ext == '.png'

        buf = io.BytesIO()
        if is_png:
            # Preserve alpha if present.
            img.save(buf, format='PNG', optimize=True)
            return buf.getvalue(), 'image/png', f"{Path(original_name).stem}.png"

        # Default: JPEG
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        elif img.mode == 'L':
            # Keep grayscale, but save as RGB for more consistent browser rendering.
            img = img.convert('RGB')

        img.save(buf, format='JPEG', quality=92, optimize=True, progressive=True)
        return buf.getvalue(), 'image/jpeg', f"{Path(original_name).stem}.jpg"
    except Exception:
        return uploaded_bytes, content_type or None, original_name


def _save_receipt_image(receipt_id: int, original_name: str | None, image_bytes: bytes) -> str:
    ext = Path(original_name or "").suffix.lower()
    if not ext or len(ext) > 8:
        ext = ".bin"

    filename = f"receipt_{receipt_id}{ext}"
    image_path = UPLOADS_DIR / filename
    image_path.write_bytes(image_bytes)
    return filename


def _delete_receipt_image(filename: str) -> None:
    image_path = UPLOADS_DIR / filename
    try:
        image_path.unlink(missing_ok=True)
    except Exception:
        pass


def _serialize_receipt(receipt: Receipt, has_image: bool) -> dict:
    image_url = f"/receipts/{receipt.id}/preview-image" if has_image else None
    return {
        "id": receipt.id,
        "merchant": receipt.merchant,
        "purchase_date": receipt.purchase_date,
        "total_amount": receipt.total_amount,
        "sales_tax_amount": receipt.sales_tax_amount,
        "extraction_confidence": float(receipt.extraction_confidence) if receipt.extraction_confidence is not None else None,
        "needs_review": bool(receipt.needs_review),
        "raw_ocr_text": receipt.raw_ocr_text,
        "created_at": receipt.created_at,
        "image_url": image_url,
    }


def _serialize_upload_job(job: UploadJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "original_filename": job.original_filename,
        "content_type": job.content_type,
        "receipt_id": job.receipt_id,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _save_upload_queue_file(original_name: str | None, file_bytes: bytes) -> str:
    ext = Path(original_name or "").suffix.lower()
    if not ext or len(ext) > 8:
        ext = ".bin"
    filename = f"upload_{int(time.time() * 1000)}_{secrets.token_hex(6)}{ext}"
    (UPLOADS_DIR / filename).write_bytes(file_bytes)
    return filename


def _enqueue_upload_job(job_id: int) -> None:
    with _UPLOAD_QUEUE_COND:
        _UPLOAD_QUEUE.append(job_id)
        _UPLOAD_QUEUE_COND.notify()


def _requeue_incomplete_upload_jobs() -> None:
    with Session(bind=engine) as db:
        pending = db.scalars(select(UploadJob.id).where(UploadJob.status.in_(["queued", "processing"]))).all()
    if not pending:
        return
    with _UPLOAD_QUEUE_COND:
        for job_id in pending:
            _UPLOAD_QUEUE.append(job_id)
        _UPLOAD_QUEUE_COND.notify_all()


def _upload_worker_loop() -> None:
    while not _UPLOAD_WORKER_STOP.is_set():
        job_id: int | None = None
        with _UPLOAD_QUEUE_COND:
            while not _UPLOAD_QUEUE and not _UPLOAD_WORKER_STOP.is_set():
                _UPLOAD_QUEUE_COND.wait(timeout=0.5)
            if _UPLOAD_WORKER_STOP.is_set():
                return
            if _UPLOAD_QUEUE:
                job_id = _UPLOAD_QUEUE.pop(0)

        if job_id is not None:
            _process_upload_job(job_id)


def _process_upload_job(job_id: int) -> None:
    with Session(bind=engine) as db:
        job = db.scalar(select(UploadJob).where(UploadJob.id == job_id))
        if job is None:
            return
        if job.status not in {"queued", "processing"}:
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        db.add(job)
        db.commit()

        queue_filename = job.stored_filename
        queue_path = UPLOADS_DIR / queue_filename
        if not queue_path.exists():
            _mark_upload_job_failed(job_id, "Uploaded file is missing")
            return

        try:
            payload = queue_path.read_bytes()
            is_pdf = (job.content_type or "").lower() == "application/pdf" or queue_path.suffix.lower() == ".pdf"
            ocr_result = run_ocr_pdf(payload) if is_pdf else run_ocr(payload)
            extracted = extract_receipt_fields(ocr_result)

            merchant_name = _normalize_merchant(extracted["merchant"])
            receipt = Receipt(
                merchant=merchant_name,
                purchase_date=extracted["purchase_date"],
                total_amount=_as_decimal(extracted["total_amount"]),
                sales_tax_amount=_as_decimal(extracted["sales_tax_amount"]),
                extraction_confidence=_as_decimal(extracted.get("extraction_confidence")),
                needs_review=bool(extracted.get("needs_review", False)),
                raw_ocr_text=extracted["raw_ocr_text"],
            )

            db.add(receipt)
            db.flush()

            final_filename = _save_receipt_image(receipt.id, job.stored_filename, payload)
            db.add(ReceiptImage(receipt_id=receipt.id, stored_filename=final_filename, content_type=job.content_type))

            if merchant_name:
                _upsert_merchant(db, merchant_name)

            job.receipt_id = receipt.id
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = None
            db.add(job)
            db.commit()
        except Exception as exc:
            db.rollback()
            _mark_upload_job_failed(job_id, str(exc))
            return
        finally:
            _delete_receipt_image(queue_filename)


def _mark_upload_job_failed(job_id: int, error: str) -> None:
    with Session(bind=engine) as db:
        job = db.scalar(select(UploadJob).where(UploadJob.id == job_id))
        if job is None:
            return
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = (error or "OCR failed")[:2000]
        db.add(job)
        db.commit()


def _ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE receipts ADD COLUMN IF NOT EXISTS extraction_confidence NUMERIC(5,2)"))
        conn.execute(text("ALTER TABLE receipts ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_preference TEXT"))
        conn.execute(text("ALTER TABLE instance_settings ADD COLUMN IF NOT EXISTS visual_accessibility_enabled BOOLEAN NOT NULL DEFAULT TRUE"))



def _get_or_create_settings(db: Session) -> InstanceSetting:
    setting = db.scalar(select(InstanceSetting).where(InstanceSetting.id == 1))
    if setting is None:
        setting = InstanceSetting(id=1, default_currency="USD", visual_accessibility_enabled=True)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def _ensure_default_settings() -> None:
    with Session(bind=engine) as db:
        _get_or_create_settings(db)


def _ensure_bootstrap_admin() -> None:
    with Session(bind=engine) as db:
        existing_admin = db.scalar(select(User.id).where(User.role == "admin"))
        if existing_admin is not None:
            return

        weak_password = DEFAULT_ADMIN_PASSWORD in {"change-me-now", "password", "admin", "admin123"}
        if weak_password or len(DEFAULT_ADMIN_PASSWORD) < 12:
            raise RuntimeError(
                "Refusing bootstrap admin with weak DEFAULT_ADMIN_PASSWORD. "
                "Set a strong value (12+ chars) via environment."
            )

        salt, digest = hash_password(DEFAULT_ADMIN_PASSWORD)
        admin = User(
            username=DEFAULT_ADMIN_USERNAME.strip().lower(),
            password_salt=salt,
            password_hash=digest,
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()


def _get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_login_rate_limit(key: str) -> None:
    now = time.time()
    with _LOGIN_LOCK:
        blocked_until = _LOGIN_BLOCKED_UNTIL.get(key)
        if blocked_until and blocked_until > now:
            retry_after = max(1, int(blocked_until - now))
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts. Retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        if blocked_until and blocked_until <= now:
            _LOGIN_BLOCKED_UNTIL.pop(key, None)

        attempts = [ts for ts in _LOGIN_ATTEMPTS.get(key, []) if now - ts <= LOGIN_RATE_LIMIT_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[key] = attempts


def _record_failed_login(key: str) -> None:
    now = time.time()
    with _LOGIN_LOCK:
        attempts = [ts for ts in _LOGIN_ATTEMPTS.get(key, []) if now - ts <= LOGIN_RATE_LIMIT_WINDOW_SECONDS]
        attempts.append(now)
        _LOGIN_ATTEMPTS[key] = attempts
        if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
            _LOGIN_BLOCKED_UNTIL[key] = now + LOGIN_RATE_LIMIT_BLOCK_SECONDS
            _LOGIN_ATTEMPTS[key] = []


def _clear_failed_login(key: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)
        _LOGIN_BLOCKED_UNTIL.pop(key, None)


_ensure_schema()
_ensure_default_settings()
_ensure_bootstrap_admin()
