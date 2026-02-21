# OCReceipt

A self-hosted Dockerized app that lets you upload receipt images, runs OCR, extracts key tax fields, and stores them in PostgreSQL.

This helps you track sales tax expenditures if you're itemizing US taxes in a state with no income taxes or if you pay less in income taxes than in sales taxes. Or if you just want to track sales taxes to know if you pay more income than sales taxes! The possibilities are limitless when the limit is three.

## Major features
- Multi-file receipt uploads with OCR extraction (images and PDFs)
- Logged receipt table with filters (date range, merchant, review status)
- Manual correction workflow and mark-reviewed actions
- Receipt image preview and CSV export
- Role-based access control (`admin`, `view`)
- Login/session authentication with secure cookies
- Reverse-proxy hardening middleware and host validation
- Login rate limiting and temporary lockouts
- Admin panel for:
  - creating/deleting users
  - changing any user password (including admin)
  - setting default currency
  - resetting the entire instance data

## Roles
- `admin`
  - Full access: upload/edit/delete/mark reviewed
  - Admin panel access (users, settings, reset)
- `view`
  - Read-only receipt access: view/filter/export
  - No upload/edit/delete/admin actions

## Run

1. Copy env template and set a strong admin password:

```bash
cp .env.example .env
```

2. Edit `.env` and set at least:

```bash
DEFAULT_ADMIN_PASSWORD=<your-strong-password>
```

3. Start the stack:

```bash
docker compose up --build
```

Open: `http://localhost:8780` (default host port)
Admin page: `http://localhost:8780/admin-panel` (admin auth required)

Default host port is `8780` (chosen to reduce collisions), but it is configurable for coexistence with other apps:

```bash
APP_PORT=8088 docker compose up --build
```

## Bootstrap admin safety
When there is no admin user in the database, the API creates one from env vars:
- `DEFAULT_ADMIN_USERNAME` (default: `admin`)
- `DEFAULT_ADMIN_PASSWORD` (required in compose)

If no admin exists and `DEFAULT_ADMIN_PASSWORD` is weak (<12 chars or common default), startup fails intentionally.

## Authentication endpoints
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

## Core API endpoints
- `GET /health`
- `POST /receipts/upload` (admin only)
- `GET /upload-jobs/{id}` (admin only; poll async OCR status)
- `GET /receipts` (supports `date_from`, `date_to`, `merchant`, `reviewed`)
- `PATCH /receipts/{id}` (admin only)
- `PATCH /receipts/{id}/review` (admin only)
- `DELETE /receipts/{id}` (admin only)
- `GET /receipts/{id}/image`
- `GET /receipts/export`
- `GET /merchants?query=...&limit=...`

## Admin API endpoints
- `GET /admin/users`
- `POST /admin/users`
- `DELETE /admin/users/{id}`
- `PATCH /admin/users/{id}/password`
- `GET /admin/settings`
- `PATCH /admin/settings`
- `POST /admin/reset-instance`

## Reverse proxy + security env

Recommended for production:
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_SAMESITE=strict`
- `FORCE_HTTPS=true`
- `ALLOWED_HOSTS=your.domain.com`
- `PROXY_TRUSTED_HOSTS=<trusted proxy IP/CIDR list>`
- `LOGIN_RATE_LIMIT_ATTEMPTS=8`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS=300`
- `LOGIN_RATE_LIMIT_BLOCK_SECONDS=900`


### Local HTTP (no TLS)
If you access the app over `http://` (for example, `http://localhost:8780`), you must disable secure cookies or the browser will not store the session cookie and login will appear to do nothing.

Use:

```env
FORCE_HTTPS=false
SESSION_COOKIE_SECURE=false
```

When running behind a TLS-terminating reverse proxy (recommended), keep:
- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`


### Domain + allowed hosts
Yes: if you want domain access, add that domain to `ALLOWED_HOSTS` in your `.env` (or compose environment).
Include every hostname that may hit this app (domain(s), and optionally localhost for local testing).

Example:

```env
ALLOWED_HOSTS=receipts.example.com,www.receipts.example.com,localhost,127.0.0.1
PROXY_TRUSTED_HOSTS=127.0.0.1,::1
```

Security middleware includes:
- Trusted host filtering
- Proxy header support
- Security headers (`CSP`, `X-Frame-Options`, `HSTS` when HTTPS enforced, `Permissions-Policy`)

## Notes
- Uploaded images are persisted in Docker volume `receipt_uploads`.
- Default currency is configurable in Admin Panel and used in table formatting.
- Reset Instance keeps the currently logged-in admin but clears receipts/merchants/other users and uploaded images.

## OCR retry tuning
Uploads run a fast OCR pass first. If extraction confidence is below threshold, the API automatically runs a more expensive full OCR pass and keeps the better result.

Config:
- `OCR_RETRY_ON_LOW_CONFIDENCE=true`
- `OCR_RETRY_CONFIDENCE_THRESHOLD=60`
- `OCR_DEBUG_ON_LOW_CONFIDENCE=true` (writes debug bundles for poor OCR outputs)



Debug bundles are written under `/app/app/uploads/debug` by default and include the original file plus `ocr_debug_report.json` with extracted fields.

## Password recovery
If the admin forgets their password, there is no email-based reset (this is intentionally offline/self-hosted).

Recovery options:
- If you still have another admin account, sign in and use the Admin Panel to change the password.
- If you have shell access to the host, run the break-glass reset tool inside the container.

Break-glass reset (recommended: avoid shell history by using stdin):

```bash
printf '%s' 'A-NEW-LONG-PASSWORD-HERE' | docker compose exec -T api python -m app.reset_password_cli --username admin --stdin
```

Notes:
- This updates the password hash in the database and invalidates existing sessions for that user.
- `DEFAULT_ADMIN_PASSWORD` is only used to bootstrap the first admin if none exists; changing it later will not overwrite an existing admin password.


## Theme preference
Theme selection (Light/Midnight Blue/OLED Black) is stored per user in the database and is applied on login.


## API tokens
For Apple Shortcuts (Share Sheet upload) or other automation, you can create an upload-scoped API token in the Admin Panel.

Use it by sending a Bearer token in the `Authorization` header:

```http
POST /receipts/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

Notes:
- Upload tokens can only be used for `POST /receipts/upload`.
- Tokens are shown only once when created; store them somewhere safe.
- `POST /receipts/upload` now returns `202 Accepted` with a job payload (`id`, `status`).
- Poll `GET /upload-jobs/{id}` until `status` is `completed` or `failed`.
