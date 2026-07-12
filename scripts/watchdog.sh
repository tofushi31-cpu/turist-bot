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
