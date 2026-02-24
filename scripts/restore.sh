#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup_dir>"
  exit 1
fi

BACKUP_DIR="$1"
SQL_FILE="${BACKUP_DIR}/receipts.sql"
UPLOADS_TAR="${BACKUP_DIR}/uploads.tar.gz"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-receipts_user}"
DB_NAME="${DB_NAME:-receipts}"

if [[ ! -f "${SQL_FILE}" ]]; then
  echo "Missing SQL backup: ${SQL_FILE}"
  exit 1
fi

if [[ ! -f "${UPLOADS_TAR}" ]]; then
  echo "Missing uploads backup: ${UPLOADS_TAR}"
  exit 1
fi

echo "This will overwrite current database data and uploaded files."
read -r -p "Type RESTORE to continue: " CONFIRM
if [[ "${CONFIRM}" != "RESTORE" ]]; then
  echo "Aborted."
  exit 1
fi

docker compose exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<SQL
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO ${DB_USER};
GRANT ALL ON SCHEMA public TO public;
SQL

docker compose exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${SQL_FILE}"

docker run --rm -v receipt_uploads:/target alpine sh -lc "rm -rf /target/*"
docker run --rm -v receipt_uploads:/target -v "$(cd "${BACKUP_DIR}" && pwd)":/backup alpine \
  sh -lc "tar -xzf /backup/uploads.tar.gz -C /target"

echo "Restore complete from ${BACKUP_DIR}"
