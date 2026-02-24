# OCR Tuning and Debug

## OCR retry behavior
Upload processing runs a fast OCR pass first. If extraction confidence is below threshold, a retry pass can run and the better result is kept.

## OCR env settings
- `OCR_RETRY_ON_LOW_CONFIDENCE=true`
- `OCR_RETRY_CONFIDENCE_THRESHOLD=60`
- `OCR_RETRY_FULL_MODE_ENABLED=false`

## Debug artifacts (recommended off by default)
- `OCR_DEBUG_ON_LOW_CONFIDENCE=false`
- `OCR_DEBUG_RETENTION_DAYS=7`
- `OCR_DEBUG_DIR=/app/uploads/debug` (optional override)

When debug artifacts are enabled, the app may store:
- original uploaded file
- `ocr_debug_report.json`

Retention cleanup runs on startup and removes old debug artifacts based on `OCR_DEBUG_RETENTION_DAYS`.
