#!/bin/zsh
# Ежедневный бэкап базы броней. Хранит 30 последних копий в ~/Backups/turist-bot.
set -e
SRC="/Users/baga/Projects/turist-bot/bookings.db"
DST_DIR="$HOME/Backups/turist-bot"
mkdir -p "$DST_DIR"
STAMP=$(date +%Y-%m-%d_%H%M)
/usr/bin/sqlite3 "$SRC" ".backup '$DST_DIR/bookings_$STAMP.db'"
ls -t "$DST_DIR"/bookings_*.db | tail -n +31 | xargs rm -f 2>/dev/null || true
echo "$(date): backup ok -> bookings_$STAMP.db" >> "$DST_DIR/backup.log"
