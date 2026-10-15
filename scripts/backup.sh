#!/bin/sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
RCLONE_DEST="${RCLONE_DESTINATION:-}"
PG_DATABASE="${POSTGRES_DB:-agenda_atende}"
PG_USER="${POSTGRES_USER:-agenda_user}"
PG_HOST="${POSTGRES_HOST:-postgres}"

case "$RETENTION_DAYS" in
    ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be numeric" >&2; exit 2 ;;
esac

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
    PGPASSWORD="$(tr -d '\r\n' < "$POSTGRES_PASSWORD_FILE")"
else
    PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD or POSTGRES_PASSWORD_FILE is required}"
fi
export PGPASSWORD
mkdir -p "$BACKUP_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

do_backup() {
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    final_file="${BACKUP_DIR}/agenda_${PG_DATABASE}_${timestamp}.sql.gz"
    dump_file="${final_file%.gz}.tmp"
    temp_file="${final_file}.tmp"
    trap 'rm -f "$dump_file" "$temp_file"' EXIT HUP INT TERM

    log "Iniciando backup do banco ${PG_DATABASE}..."
    pg_dump -h "$PG_HOST" -U "$PG_USER" -d "$PG_DATABASE" \
        --no-owner --no-privileges --clean --if-exists > "$dump_file"
    test -s "$dump_file"
    gzip -c "$dump_file" > "$temp_file"
    test -s "$temp_file"
    gzip -t "$temp_file"
    mv "$temp_file" "$final_file"
    rm -f "$dump_file"
    trap - EXIT HUP INT TERM
    log "Backup concluído: $final_file"

    if [ -n "$RCLONE_DEST" ]; then
        rclone_args=""
        if [ -n "${RCLONE_CONFIG_FILE:-}" ]; then
            rclone_args="--config ${RCLONE_CONFIG_FILE}"
        fi
        # shellcheck disable=SC2086
        rclone $rclone_args copy "$final_file" "$RCLONE_DEST"
    fi

    find "$BACKUP_DIR" -name "agenda_${PG_DATABASE}_*.sql.gz" \
        -mtime "+${RETENTION_DAYS}" -delete
}

if [ -n "${BACKUP_SCHEDULE:-}" ]; then
    log "Modo agendado ativado: $BACKUP_SCHEDULE"
    echo "$BACKUP_SCHEDULE /backup.sh" > /etc/crontabs/root
    do_backup
    exec crond -f -l 2
else
    do_backup
fi
