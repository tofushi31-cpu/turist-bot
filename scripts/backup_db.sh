#!/bin/zsh
# Ежедневный бэкап базы броней. Хранит 30 последних копий в ~/Backups/turist-bot.
set -e
SRC="/Users/baga/Projects/turist-bot/bookings.db"
DST_DIR="$HOME/Backups/turist-bot"

valli_alert() {
  # токен и chat_id лежат в .env (не в git); алерт только при сбое
  local env_file="/Users/baga/Projects/turist-bot/.env"
  local token=$(grep '^VALLI_BOT_TOKEN=' "$env_file" | cut -d= -f2-)
  local chat=$(grep '^VALLI_CHAT_ID=' "$env_file" | cut -d= -f2-)
  [ -n "$token" ] && [ -n "$chat" ] && curl -s -m 10 -X POST \
    "https://api.telegram.org/bot$token/sendMessage" \
    -d chat_id="$chat" --data-urlencode "text=$1" > /dev/null 2>&1
}
trap 'valli_alert "❌ Валли: ежедневный бэкап базы turist-bot НЕ выполнен — проверь backup.log на Маке."' ERR
mkdir -p "$DST_DIR"
STAMP=$(date +%Y-%m-%d_%H%M)
/usr/bin/sqlite3 "$SRC" ".backup '$DST_DIR/bookings_$STAMP.db'"
ls -t "$DST_DIR"/bookings_*.db | tail -n +31 | xargs rm -f 2>/dev/null || true
echo "$(date): backup ok -> bookings_$STAMP.db" >> "$DST_DIR/backup.log"

# Копия в iCloud Drive (переживёт потерю ноутбука). Храним 10 последних.
ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Backups/turist-bot"
if mkdir -p "$ICLOUD_DIR" 2>/dev/null; then
  cp "$DST_DIR/bookings_$STAMP.db" "$ICLOUD_DIR/"
  ls -t "$ICLOUD_DIR"/bookings_*.db | tail -n +11 | xargs rm -f 2>/dev/null || true
  echo "$(date): icloud copy ok" >> "$DST_DIR/backup.log"
else
  echo "$(date): icloud copy SKIPPED (нет iCloud Drive)" >> "$DST_DIR/backup.log"
fi
