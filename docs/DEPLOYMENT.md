# Deployment Guide

## Recommended internet-facing setup
Run OCReceipt behind a TLS reverse proxy.

Keep these settings:
- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_SAMESITE=strict`
- `ALLOWED_HOSTS=<your real hostnames>`
- `PROXY_TRUSTED_HOSTS=<trusted proxy IPs>`

Example:

```env
ALLOWED_HOSTS=receipts.example.com,www.receipts.example.com
PROXY_TRUSTED_HOSTS=127.0.0.1,::1
```

## Local-only HTTP mode
If using plain `http://` locally, set:

```env
FORCE_HTTPS=false
SESSION_COOKIE_SECURE=false
```

Without this, browsers will not persist the auth cookie over HTTP.

## Security-related deployment env
- `MIN_PASSWORD_LENGTH=12`
- `MAX_UPLOAD_BYTES=15728640`
- `LOGIN_RATE_LIMIT_ATTEMPTS=8`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS=300`
- `LOGIN_RATE_LIMIT_BLOCK_SECONDS=900`
- `OCR_DEBUG_ON_LOW_CONFIDENCE=false`
- `OCR_DEBUG_RETENTION_DAYS=7`

## Startup check behavior
The app logs warnings for insecure/self-host-risky config (for example disabled HTTPS or enabled OCR debug artifacts).
