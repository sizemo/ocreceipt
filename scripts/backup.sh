#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${1:-./backups/${STAMP}}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-receipts_user}"
DB_NAME="${DB_NAME:-receipts}"
mkdir -p "${OUT_DIR}"

echo "Creating backup in ${OUT_DIR}"

docker compose exec -T "${DB_SERVICE}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" > "${OUT_DIR}/receipts.sql"
docker run --rm -v receipt_uploads:/source -v "$(cd "${OUT_DIR}" && pwd)":/backup alpine \
  sh -lc "tar -czf /backup/uploads.tar.gz -C /source ."

cat > "${OUT_DIR}/manifest.txt" <<EOF
created_at_utc=${STAMP}
files=receipts.sql,uploads.tar.gz
EOF

echo "Backup complete:"
echo "  - ${OUT_DIR}/receipts.sql"
echo "  - ${OUT_DIR}/uploads.tar.gz"
echo "  - ${OUT_DIR}/manifest.txt"
