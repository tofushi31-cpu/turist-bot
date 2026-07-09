#!/bin/zsh
# Следит, чтобы бот работал ровно в одном экземпляре.
# 0 процессов -> запускает. Больше 1 -> убивает все и запускает один.
BOT_DIR="/Users/baga/Desktop/Teach/turist-bot"
LOG="$BOT_DIR/watchdog.log"
PIDS=($(pgrep -f "[P]ython bot.py" | while read p; do
  lsof -p $p 2>/dev/null | grep -q "cwd.*turist-bot$" && echo $p
done))

start_bot() {
  cd "$BOT_DIR"
  nohup python3 bot.py >> bot.log 2>&1 &
  echo "$(date): бот запущен, pid $!" >> "$LOG"
}

if [ ${#PIDS[@]} -eq 0 ]; then
  echo "$(date): бот не найден — запускаю" >> "$LOG"
  start_bot
elif [ ${#PIDS[@]} -gt 1 ]; then
  echo "$(date): найдено ${#PIDS[@]} процессов (${PIDS[@]}) — убиваю дубли и перезапускаю" >> "$LOG"
  kill ${PIDS[@]} 2>/dev/null
  sleep 2
  start_bot
fi
