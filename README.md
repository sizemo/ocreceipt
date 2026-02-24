# OCReceipt

Self-hosted receipt OCR and tracking app for individuals. Upload receipt images/PDFs, extract structured fields, review/edit results, and export data.

## Project overview

### What this project does
- Upload one or many receipts (images or PDFs)
- Run OCR and extract merchant/date/total/tax/confidence
- Review/edit extracted data in a table workflow
- Preview original receipts and export CSV
- Manage users (`admin`, `view`) and app settings from an admin panel

### Security model (high level)
- Cookie-based auth for web users
- Upload API tokens (admin-created, upload-scoped)
- Trusted host enforcement + reverse-proxy aware headers
- Login rate limiting and temporary lockouts
- Secure defaults for self-hosting (password policy, upload limits, debug off)

## Deploy and get it running

### Prerequisites
- Docker + Docker Compose

### First startup (quick path)
1. Copy env template:

```bash
cp .env.example .env
```

2. Start the stack:

```bash
docker compose up --build -d
```

3. Open the app:
- App: `http://localhost:8780`
- Admin panel: `http://localhost:8780/admin-panel`
- On first launch, create your initial admin account in the UI.

### Change host port (optional)

```bash
APP_PORT=8088 docker compose up --build -d
```

### First-run account setup
If no users exist yet, the app shows an initial setup form on the login screen.
The first account created becomes the `admin` user for that instance.

### Internet-facing deployment (recommended baseline)
Put the app behind a TLS reverse proxy and keep:
- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_SAMESITE=strict`
- `ALLOWED_HOSTS` set to your real hostnames

Local HTTP-only testing should use:

```env
FORCE_HTTPS=false
SESSION_COOKIE_SECURE=false
```

Detailed deployment guidance: [docs/DEPLOYMENT.md](https://github.com/sizemo/ocreceipt/tree/main/docs/DEPLOYMENT.md)

## Configuration after initial startup

### Core security and limits
Key `.env` options:
- `MIN_PASSWORD_LENGTH=12`
- `MAX_UPLOAD_BYTES=15728640` (15 MB)
- `LOGIN_RATE_LIMIT_ATTEMPTS=8`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS=300`
- `LOGIN_RATE_LIMIT_BLOCK_SECONDS=900`
- `ALLOWED_HOSTS=...`
- `PROXY_TRUSTED_HOSTS=...`

### Self-hosting checklist
- Use TLS if the app is reachable beyond localhost
- Keep debug artifacts off unless actively investigating OCR issues
- Keep upload size conservative
- Back up DB + uploads before upgrades

## Docs
- Deployment and reverse proxy hardening: [docs/DEPLOYMENT.md](https://github.com/sizemo/ocreceipt/tree/main/docs/DEPLOYMENT.md)
- Operations (backup/restore, recovery, tokens): [docs/OPERATIONS.md](https://github.com/sizemo/ocreceipt/tree/main/docs/OPERATIONS.md)
- OCR tuning and debug artifacts: [docs/OCR.md](https://github.com/sizemo/ocreceipt/tree/main/docs/OCR.md)
- API endpoints: [docs/API.md](https://github.com/sizemo/ocreceipt/tree/main/docs/API.md)

## API reference
See [docs/API.md](https://github.com/sizemo/ocreceipt/tree/main/docs/API.md).
