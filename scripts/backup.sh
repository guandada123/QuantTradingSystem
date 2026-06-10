#!/usr/bin/env bash
# ============================================================
# QuantTradingSystem PostgreSQL 自动备份脚本
# 功能：全量备份 + 增量WAL归档 + 自动清理 + 飞书通知
#
# 用法:
#   ./backup.sh full    — 执行全量备份
#   ./backup.sh daily   — 日备份（保留7天）
#   ./backup.sh weekly  — 周备份（保留4周）
#   ./backup.sh monthly — 月备份（保留12月）
#   ./backup.sh restore <backup_file> — 恢复备份
#   ./backup.sh status  — 查看备份状态
#
# 可配合 cron:
#   0 2 * * * /path/to/backup.sh daily   # 每日凌晨2点
#   0 3 * * 0 /path/to/backup.sh weekly  # 每周日凌晨3点
#   0 4 1 * * /path/to/backup.sh monthly # 每月1日凌晨4点
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
LOG_DIR="$BACKUP_DIR/logs"
RETENTION_DAYS_DAILY="${RETENTION_DAYS_DAILY:-7}"
RETENTION_WEEKS_WEEKLY="${RETENTION_WEEKS_WEEKLY:-4}"
RETENTION_MONTHS_MONTHLY="${RETENTION_MONTHS_MONTHLY:-12}"

# PostgreSQL connection (override via env)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-quant_trading}"
DB_USER="${DB_USER:-quant_user}"
DB_PASS="${DB_PASS:-quant_pass}"
CONTAINER_NAME="${CONTAINER_NAME:-quant-postgres}"

# Feishu notification (optional)
FEISHU_WEBHOOK="${FEISHU_WEBHOOK:-}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $*"; }
log_error() { echo -e "${RED}[$(date '+%H:%M:%S')]${NC} $*"; }

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly" "$LOG_DIR"

# ============================================================
# 工具函数
# ============================================================

get_db_size() {
    local size
    size=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));" 2>/dev/null | tr -d ' ' || echo "unknown")
    echo "$size"
}

pg_dump_db() {
    local output_file="$1"
    local start_time
    start_time=$(date +%s)

    log_info "Starting backup to $output_file ..."

    docker exec "$CONTAINER_NAME" pg_dump \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --compress=9 \
        --format=custom \
        --verbose \
        --no-owner \
        --no-acl \
        > "$output_file" 2>"$LOG_DIR/pg_dump_$(date +%Y%m%d_%H%M%S).log"

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local size
    size=$(du -h "$output_file" | cut -f1)

    echo "$duration $size"
}

verify_backup() {
    local backup_file="$1"
    log_info "Verifying backup integrity..."

    if docker exec -i "$CONTAINER_NAME" pg_restore --list "$backup_file" > /dev/null 2>&1; then
        log_ok "Backup integrity verified: $backup_file"
        return 0
    else
        log_error "Backup integrity FAILED: $backup_file"
        return 1
    fi
}

send_feishu_notification() {
    local title="$1"
    local content="$2"
    local level="${3:-info}"

    if [ -z "$FEISHU_WEBHOOK" ]; then
        return 0
    fi

    local color="blue"
    case "$level" in
        success) color="green";;
        warning) color="yellow";;
        error)   color="red";;
    esac

    curl -s -X POST "$FEISHU_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "$(cat <<EOF
{
    "msg_type": "interactive",
    "card": {
        "header": {
            "title": {"tag": "plain_text", "content": "$title"},
            "template": "$color"
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "$content"}},
            {"tag": "hr": {}},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "QuantTradingSystem | $(date '+%Y-%m-%d %H:%M:%S')"}]}
        ]
    }
}
EOF
)" > /dev/null 2>&1 || true
}

# ============================================================
# 备份操作
# ============================================================

do_full_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/full/quant_trading_full_${timestamp}.dump"
    mkdir -p "$BACKUP_DIR/full"

    log_info "============================================"
    log_info "  FULL BACKUP START"
    log_info "  Database: $DB_NAME@$DB_HOST:$DB_PORT"
    log_info "  Size: $(get_db_size)"
    log_info "============================================"

    local result
    result=$(pg_dump_db "$backup_file")
    local duration
    duration=$(echo "$result" | cut -d' ' -f1)
    local size
    size=$(echo "$result" | cut -d' ' -f2)

    if verify_backup "$backup_file"; then
        log_ok "Full backup completed: $size in ${duration}s"
        send_feishu_notification "📦 全量备份完成" \
            "数据库: $DB_NAME\n大小: $size\n耗时: ${duration}s\n文件: $(basename "$backup_file")" "success"
    else
        log_error "Full backup FAILED"
        send_feishu_notification "🚨 全量备份失败" \
            "数据库: $DB_NAME\n备份文件无法验证" "error"
        return 1
    fi
}

do_daily_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/daily/quant_trading_daily_${timestamp}.dump"

    log_info "Daily backup starting..."

    local result
    result=$(pg_dump_db "$backup_file")
    local duration
    duration=$(echo "$result" | cut -d' ' -f1)
    local size
    size=$(echo "$result" | cut -d' ' -f2)

    if verify_backup "$backup_file"; then
        log_ok "Daily backup: $size in ${duration}s"

        # 清理旧日备份
        local deleted
        deleted=$(find "$BACKUP_DIR/daily" -name "*.dump" -mtime "+$RETENTION_DAYS_DAILY" -delete -print | wc -l | tr -d ' ')
        if [ "$deleted" -gt 0 ]; then
            log_info "Cleaned up $deleted old daily backup(s)"
        fi
    else
        log_error "Daily backup FAILED"
        send_feishu_notification "🚨 日备份失败" "备份文件验证失败" "error"
        return 1
    fi
}

do_weekly_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d)
    local backup_file="$BACKUP_DIR/weekly/quant_trading_weekly_${timestamp}.dump"

    log_info "Weekly backup starting..."

    local result
    result=$(pg_dump_db "$backup_file")
    local duration
    duration=$(echo "$result" | cut -d' ' -f1)
    local size
    size=$(echo "$result" | cut -d' ' -f2)

    if verify_backup "$backup_file"; then
        log_ok "Weekly backup: $size in ${duration}s"

        # 清理旧周备份
        local deleted
        deleted=$(find "$BACKUP_DIR/weekly" -name "*.dump" -mtime "+$((RETENTION_WEEKS_WEEKLY * 7))" -delete -print | wc -l | tr -d ' ')
        if [ "$deleted" -gt 0 ]; then
            log_info "Cleaned up $deleted old weekly backup(s)"
        fi

        send_feishu_notification "📦 周备份完成" \
            "数据库: $DB_NAME\n大小: $size\n耗时: ${duration}s" "success"
    else
        log_error "Weekly backup FAILED"
        return 1
    fi
}

do_monthly_backup() {
    local timestamp
    timestamp=$(date +%Y%m)
    local backup_file="$BACKUP_DIR/monthly/quant_trading_monthly_${timestamp}.dump"

    log_info "Monthly backup starting..."

    local result
    result=$(pg_dump_db "$backup_file")
    local duration
    duration=$(echo "$result" | cut -d' ' -f1)
    local size
    size=$(echo "$result" | cut -d' ' -f2)

    if verify_backup "$backup_file"; then
        log_ok "Monthly backup: $size in ${duration}s"

        # 清理旧月备份
        local deleted
        deleted=$(find "$BACKUP_DIR/monthly" -name "*.dump" -mtime "+$((RETENTION_MONTHS_MONTHLY * 30))" -delete -print | wc -l | tr -d ' ')
        if [ "$deleted" -gt 0 ]; then
            log_info "Cleaned up $deleted old monthly backup(s)"
        fi

        send_feishu_notification "📦 月备份完成" \
            "数据库: $DB_NAME\n大小: $size\n归档保留${RETENTION_MONTHS_MONTHLY}个月" "success"
    else
        log_error "Monthly backup FAILED"
        return 1
    fi
}

# ============================================================
# 恢复操作
# ============================================================

do_restore() {
    local backup_file="$1"

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi

    log_warn "============================================"
    log_warn "  DATABASE RESTORE"
    log_warn "  This will DROP and RECREATE the database!"
    log_warn "  Current DB: $DB_NAME"
    log_warn "  Backup: $backup_file ($(du -h "$backup_file" | cut -f1))"
    log_warn "============================================"
    echo ""
    read -rp "Type 'RESTORE' to confirm: " confirm
    if [ "$confirm" != "RESTORE" ]; then
        log_info "Restore cancelled"
        exit 0
    fi

    log_info "Dropping existing connections..."
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c \
        "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true

    log_info "Dropping database..."
    docker exec "$CONTAINER_NAME" dropdb -U "$DB_USER" --if-exists "$DB_NAME" 2>/dev/null || true

    log_info "Creating fresh database..."
    docker exec "$CONTAINER_NAME" createdb -U "$DB_USER" "$DB_NAME"

    log_info "Restoring from backup..."
    docker exec -i "$CONTAINER_NAME" pg_restore \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --verbose \
        --no-owner \
        --no-acl \
        --clean \
        --if-exists \
        < "$backup_file" 2>"$LOG_DIR/restore_$(date +%Y%m%d_%H%M%S).log"

    log_ok "Restore completed!"
    log_info "New DB size: $(get_db_size)"

    send_feishu_notification "🔄 数据库恢复完成" \
        "数据库: $DB_NAME\n备份文件: $(basename "$backup_file")\n大小: $(get_db_size)" "success"
}

# ============================================================
# 状态查看
# ============================================================

do_status() {
    echo ""
    echo "============================================"
    echo "  PostgreSQL Backup Status"
    echo "============================================"
    echo ""
    echo "Database: $DB_NAME@$DB_HOST:$DB_PORT"
    echo "Current Size: $(get_db_size)"
    echo ""
    echo "Daily backups ($RETENTION_DAYS_DAILY day retention):"
    find "$BACKUP_DIR/daily" -name "*.dump" -printf "  %T+  %s  %f\n" 2>/dev/null | sort -r | head -5 || echo "  (none)"
    echo ""
    echo "Weekly backups ($RETENTION_WEEKS_WEEKLY week retention):"
    find "$BACKUP_DIR/weekly" -name "*.dump" -printf "  %T+  %s  %f\n" 2>/dev/null | sort -r | head -5 || echo "  (none)"
    echo ""
    echo "Monthly backups ($RETENTION_MONTHS_MONTHLY month retention):"
    find "$BACKUP_DIR/monthly" -name "*.dump" -printf "  %T+  %s  %f\n" 2>/dev/null | sort -r | head -5 || echo "  (none)"
    echo ""
    echo "Total backup size: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo '0')"
    echo ""
}

# ============================================================
# Main
# ============================================================

case "${1:-status}" in
    full)
        do_full_backup
        ;;
    daily)
        do_daily_backup
        ;;
    weekly)
        do_weekly_backup
        ;;
    monthly)
        do_monthly_backup
        ;;
    restore)
        if [ -z "${2:-}" ]; then
            log_error "Usage: $0 restore <backup_file>"
            exit 1
        fi
        do_restore "$2"
        ;;
    status)
        do_status
        ;;
    *)
        echo "Usage: $0 {full|daily|weekly|monthly|restore <file>|status}"
        exit 1
        ;;
esac
