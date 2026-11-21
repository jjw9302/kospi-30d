#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/var/www/html/02kospi}"
PYTHON_BIN="$(command -v python3)"
LOG_FILE="$APP_DIR/data/cron.log"

mkdir -p "$APP_DIR/data"

# 기존 KOSPI_02_AUTO 항목 제거 후 3단계 예약 작업 등록
(
  crontab -l 2>/dev/null | grep -v 'KOSPI_02_AUTO' || true
  echo "*/10 * * * * TZ=Asia/Seoul /usr/bin/flock -n /tmp/kospi_10m.lock $PYTHON_BIN $APP_DIR/update_kospi.py --mode 10m >> $LOG_FILE 2>&1 # KOSPI_02_AUTO_10M"
  echo "0 17 * * 6 TZ=Asia/Seoul /usr/bin/flock -n /tmp/kospi_weekly.lock $PYTHON_BIN $APP_DIR/update_kospi.py --mode weekly >> $LOG_FILE 2>&1 # KOSPI_02_AUTO_WEEKLY"
  echo "0 18 1 * * TZ=Asia/Seoul /usr/bin/flock -n /tmp/kospi_monthly.lock $PYTHON_BIN $APP_DIR/update_kospi.py --mode monthly >> $LOG_FILE 2>&1 # KOSPI_02_AUTO_MONTHLY"
) | crontab -

echo "crontab 등록 완료 ($APP_DIR):"
crontab -l | grep 'KOSPI_02_AUTO'
