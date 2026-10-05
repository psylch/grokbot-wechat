#!/bin/bash
# Outer watchdog. Run every 15 minutes (a Grok Bot scheduled routine, cron, or systemd timer).
# run_forward.sh already restarts forward.py when it crashes; this script covers the cases it can't:
#   * the machine/box restarted and run_forward.sh itself is gone
#   * forward.py is alive but stuck (heartbeat older than STALE_S)
# Prints exactly one status line: OK / RESTARTED (reason) / FAILED (reason). Exit 0 unless FAILED.
cd "$(dirname "$(readlink -f "$0")")" || exit 2
DATA="${BRIDGE_DATA_DIR:-.}"
STALE_S="${STALE_S:-600}"     # long-poll returns every ~40s; 10 min without a heartbeat means stuck
reason=""

pid="$(cat "$DATA/forward.pid" 2>/dev/null)"
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null || ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q run_forward.sh; then
  reason="run_forward.sh not running"
elif ! pgrep -P "$pid" -f forward.py >/dev/null; then
  reason="forward.py not running"   # normally restarted within 5s by run_forward.sh; give it one more look
  sleep 8; pgrep -P "$pid" -f forward.py >/dev/null && reason=""
fi
if [ -z "$reason" ] && [ -f "$DATA/forward.heartbeat" ]; then
  age=$(( $(date +%s) - $(cat "$DATA/forward.heartbeat" 2>/dev/null || echo 0) ))
  [ "$age" -gt "$STALE_S" ] && reason="heartbeat stale (${age}s)"
fi

if [ -z "$reason" ]; then
  echo "OK pid=$pid"; exit 0
fi

# Restart cleanly: stop the old loop AND any orphaned forward.py first, so two pollers never share
# one getupdates cursor. Only processes whose cwd is this directory are touched, never other
# forward.py instances on the machine.
here="$(pwd -P)"
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q run_forward.sh; then
  kill "$pid" 2>/dev/null
fi
for p in $(pgrep -f "forward.py"); do
  [ "$(readlink "/proc/$p/cwd" 2>/dev/null)" = "$here" ] && kill "$p" 2>/dev/null
done
sleep 2
nohup setsid ./run_forward.sh >/dev/null 2>&1 < /dev/null &
sleep 5
newpid="$(cat "$DATA/forward.pid" 2>/dev/null)"
if [ -n "$newpid" ] && kill -0 "$newpid" 2>/dev/null; then
  echo "RESTARTED ($reason) pid=$newpid"
  echo "$(date '+%F %T') watchdog restarted forwarder: $reason" >> "$DATA/forward.log"
  exit 0
fi
echo "FAILED ($reason) - see $DATA/forward.out"; exit 1
