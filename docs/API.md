# API Reference

## Auth
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

## Health
- `GET /health`

## Core receipt APIs
- `POST /receipts/upload` (`admin` session or upload token)
- `GET /upload-jobs/{id}` (`admin` only)
- `GET /receipts` (`admin` or `view`)
- `PATCH /receipts/{id}` (`admin` only)
- `PATCH /receipts/{id}/review` (`admin` only)
- `DELETE /receipts/{id}` (`admin` only)
- `GET /receipts/{id}/image` (`admin` or `view`)
- `GET /receipts/export` (`admin` or `view`)
- `GET /merchants?query=...&limit=...` (`admin` or `view`)

### Receipts list query params
- `date_from` (`YYYY-MM-DD`)
- `date_to` (`YYYY-MM-DD`)
- `merchant` (exact case-insensitive match)
- `reviewed` (`true`/`false`)
- `sort_by`
- `sort_dir` (`asc`/`desc`)
- `limit`
- `offset`

## Admin APIs (`admin` only)
- `GET /admin/users`
- `POST /admin/users`
- `DELETE /admin/users/{id}`
- `PATCH /admin/users/{id}/password`
- `GET /admin/settings`
- `PATCH /admin/settings`
- `POST /admin/reset-instance`
- `GET /admin/api-tokens`
- `POST /admin/api-tokens`
- `PATCH /admin/api-tokens/{token_id}/revoke`

## Upload token usage
Upload tokens are scoped to upload only and can be used only with:
- `POST /receipts/upload`

Example:

```http
POST /receipts/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

## Notes
- Upload endpoint returns `202 Accepted` with upload job payload.
- Poll `GET /upload-jobs/{id}` until `status` is `completed` or `failed`.
- Admin UI endpoint is `GET /admin-panel` (session-auth, admin role required).
