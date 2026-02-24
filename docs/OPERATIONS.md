# Operations Guide

## Access roles
- `admin`: full receipt + admin-panel access
- `view`: read-only receipt access (view/filter/export)

## Backup and restore

### Backup
```bash
./scripts/backup.sh
# or custom folder
./scripts/backup.sh ./backups/pre-upgrade
```

### Restore
```bash
./scripts/restore.sh ./backups/pre-upgrade
```

Restore is destructive: it replaces current DB data and uploaded files.

## Password recovery (break-glass)
If an admin password is lost and no admin can reset it from UI:

```bash
printf '%s' 'A-NEW-LONG-PASSWORD-HERE' | docker compose exec -T api python -m app.reset_password_cli --username admin --stdin
```

This resets password hash and invalidates sessions for that user.

## Upload API tokens
Admins can create upload-scoped tokens from the Admin Panel.

Usage:

```http
POST /receipts/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

Notes:
- Token works only for `POST /receipts/upload`
- Token is shown once on creation
- Upload returns `202` with job payload
- Poll `GET /upload-jobs/{id}` for completion

## User preferences
- Theme preference (Light/Midnight/OLED) is stored per user.
