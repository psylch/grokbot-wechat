#!/bin/bash
# Inner watchdog: restarts forward.py whenever it exits. The PID of THIS loop is written to forward.pid.
# Start it detached, e.g.:  nohup setsid ./run_forward.sh >/dev/null 2>&1 &
# It does not survive a machine/box restart; watchdog.sh (run every 15 min) covers that.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
LOGDIR="${BRIDGE_DATA_DIR:-.}"
echo $$ > "$LOGDIR/forward.pid"
while true; do
  python3 -u forward.py >> "$LOGDIR/forward.out" 2>&1
  echo "$(date '+%F %T') forward.py exited ($?), restarting in 5s" >> "$LOGDIR/forward.log"
  sleep 5
done
