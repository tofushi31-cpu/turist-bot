#!/bin/zsh
# Проверка здоровья turist-bot. Запускается при старте сессии Claude Code.
# Выводит только проблемы; если всё ок — одна короткая строка.
BOT_DIR="/Users/baga/Projects/turist-bot"
ISSUES=()

# 1. Жив ли бот (процесс bot.py с рабочей папкой turist-bot)
ALIVE=0
for p in $(pgrep -f "[b]ot.py"); do
  lsof -p $p 2>/dev/null | grep -q "cwd.*turist-bot$" && ALIVE=$((ALIVE+1))
done
[ $ALIVE -eq 0 ] && ISSUES+=("БОТ НЕ ЗАПУЩЕН (0 процессов)")
[ $ALIVE -gt 1 ] && ISSUES+=("ДУБЛИ БОТА: $ALIVE процессов")

# 2. launchd-задачи не в ошибке
for job in com.baga.turistbot.backup com.baga.turistbot.watchdog; do
  code=$(launchctl list | awk -v j=$job '$3==j {print $2}')
  [ -n "$code" ] && [ "$code" != "0" ] && ISSUES+=("launchd $job: код ошибки $code")
  [ -z "$code" ] && ISSUES+=("launchd $job: не загружена")
done

# 3. Свежесть бэкапа базы (не старше 2 суток)
LAST_BAK=$(ls -t ~/Backups/turist-bot/bookings_*.db 2>/dev/null | head -1)
if [ -z "$LAST_BAK" ]; then
  ISSUES+=("бэкапов базы нет вообще")
elif [ -z "$(find "$LAST_BAK" -mtime -2 2>/dev/null)" ]; then
  ISSUES+=("последний бэкап базы старше 2 суток: $LAST_BAK")
fi

# 4. Ошибки в хвосте лога бота
ERRS=$(tail -50 "$BOT_DIR/bot.log" 2>/dev/null | grep -c 'ERROR\|Traceback')
[ "$ERRS" -gt 0 ] && ISSUES+=("в хвосте bot.log $ERRS строк с ошибками")

if [ ${#ISSUES[@]} -eq 0 ]; then
  echo "healthcheck turist-bot: всё в порядке (бот жив, launchd ок, бэкап свежий)"
else
  echo "healthcheck turist-bot — НАЙДЕНЫ ПРОБЛЕМЫ, сообщи о них Baga в начале ответа:"
  for i in "${ISSUES[@]}"; do echo "  - $i"; done
fi
