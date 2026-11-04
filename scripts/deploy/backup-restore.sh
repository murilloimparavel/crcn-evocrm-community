#!/usr/bin/env bash
# Install/run on a reviewed backup executor, never automatically from CI.
# Creates a logical dump; restores into a disposable, network-isolated database.
set -euo pipefail
umask 077
: "${BACKUP_DIR:?Use a protected directory outside the repository}"
: "${RESTORE_POSTGRES_IMAGE:?Pin the compatible pgvector image with @sha256}"
[[ "$RESTORE_POSTGRES_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]] || exit 2
source_container=postgres-tzbydmxtjuilf4xq2gow9gcs
mkdir -p "$BACKUP_DIR"
backup_dir="$(cd "$BACKUP_DIR" && pwd -P)"
repo_dir="$(cd "$(dirname "$0")/../.." && pwd -P)"
if [[ -e "$repo_dir/.git" ]]; then
  case "$backup_dir/" in "$repo_dir/"*) echo 'Backup directory must be outside repository' >&2; exit 2;; esac
fi
run_id="evocrm-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$"
archive="$backup_dir/$run_id.dump"
volume="$run_id-data"
cleanup() {
  docker rm -f "$run_id" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT
# Password stays inside the source container. Do not enable shell tracing.
docker exec "$source_container" sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -U "$POSTGRES_USER" -d evocrm -Fc --no-owner --no-acl' > "$archive.partial"
test -s "$archive.partial"
mv "$archive.partial" "$archive"
docker volume create "$volume" >/dev/null
docker run -d --name "$run_id" --network none -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$volume:/var/lib/postgresql/data" "$RESTORE_POSTGRES_IMAGE" >/dev/null
ready=false
for _ in $(seq 1 60); do
  if docker exec "$run_id" pg_isready -U postgres >/dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]]
docker exec "$run_id" createdb -U postgres restore_check
docker exec -i "$run_id" pg_restore -U postgres -d restore_check --no-owner --no-acl --exit-on-error < "$archive"
tables="$(docker exec "$run_id" psql -U postgres -d restore_check -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
[[ "$tables" =~ ^[0-9]+$ ]] && (( tables > 0 ))
sha256sum "$archive" > "$archive.sha256"
printf 'Restore verified: %s public tables. Archive retained outside repository.\n' "$tables"
# Offsite upload, roles/grants, storage volumes and functional restoration must
# also be verified before readiness evidence is approved. No retention deletion.
