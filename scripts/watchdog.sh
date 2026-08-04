#!/bin/zsh
# Следит, чтобы бот работал ровно в одном экземпляре.
# 0 процессов -> запускает. Больше 1 -> убивает все и запускает один.
BOT_DIR="/Users/baga/Projects/turist-bot"
LOG="$BOT_DIR/watchdog.log"
PIDS=($(pgrep -f "[b]ot.py" | while read p; do
  lsof -p $p 2>/dev/null | grep -q "cwd.*turist-bot$" && echo $p
done))

valli_alert() {
  # токен и chat_id лежат в .env (не в git)
  local token=$(grep '^VALLI_BOT_TOKEN=' "$BOT_DIR/.env" | cut -d= -f2-)
  local chat=$(grep '^VALLI_CHAT_ID=' "$BOT_DIR/.env" | cut -d= -f2-)
  [ -n "$token" ] && [ -n "$chat" ] && curl -s -m 10 -X POST \
    "https://api.telegram.org/bot$token/sendMessage" \
    -d chat_id="$chat" --data-urlencode "text=$1" >> /tmp/valli-ping.log 2>&1
}

start_bot() {
  cd "$BOT_DIR"
  nohup "$BOT_DIR/venv/bin/python3" bot.py >> bot.log 2>&1 &
  echo "$(date): бот запущен, pid $!" >> "$LOG"
}

if [ ${#PIDS[@]} -eq 0 ]; then
  echo "$(date): бот не найден — запускаю" >> "$LOG"
  start_bot
  valli_alert "⚠️ Валли: turist-bot был не запущен — поднял его ($(date '+%H:%M'))."
elif [ ${#PIDS[@]} -gt 1 ]; then
  echo "$(date): найдено ${#PIDS[@]} процессов (${PIDS[@]}) — убиваю дубли и перезапускаю" >> "$LOG"
  kill ${PIDS[@]} 2>/dev/null
  sleep 2
  start_bot
  valli_alert "⚠️ Валли: у turist-bot было ${#PIDS[@]} процессов-дублей — почистил и перезапустил ($(date '+%H:%M'))."
fi

# Проверка сетевых обрывов (бот жив, но не может достучаться до Telegram API)
NET_STATE="/tmp/turistbot-netalert-state"
NET_THRESHOLD=3
NET_COOLDOWN=1800
CUTOFF=$(date -v-6M +"%Y-%m-%d %H:%M:%S")
NET_ERRORS=$(awk -v cutoff="$CUTOFF" '
  /ERROR aiogram.dispatcher/ {
    ts = $1 " " $2
    gsub(/,.*/, "", ts)
    if (ts >= cutoff) c++
  }
  END { print c+0 }
' "$BOT_DIR/bot.log")

if [ "$NET_ERRORS" -ge "$NET_THRESHOLD" ]; then
  LAST_ALERT=0
  [ -f "$NET_STATE" ] && LAST_ALERT=$(cat "$NET_STATE")
  NOW=$(date +%s)
  if [ $((NOW - LAST_ALERT)) -gt "$NET_COOLDOWN" ]; then
    echo "$(date): нестабильная связь с Telegram API — $NET_ERRORS ошибок за 6 мин" >> "$LOG"
    valli_alert "📡 Валли: turist-bot не может достучаться до Telegram API ($NET_ERRORS обрывов за 6 мин). Бот жив, сам переподключается."
    echo "$NOW" > "$NET_STATE"
  fi
elif [ -f "$NET_STATE" ]; then
  echo "$(date): связь с Telegram API восстановилась" >> "$LOG"
  valli_alert "✅ Валли: связь turist-bot с Telegram API восстановилась."
  rm -f "$NET_STATE"
fi
