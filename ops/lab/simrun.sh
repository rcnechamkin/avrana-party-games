#!/usr/bin/env bash
# Run one simulator configuration against a fresh, seeded BLUFF server on :8200.
# usage: simrun.sh SEED "sim args..."
cd ~/avrana-lab/avrana-party-games || exit 1
PY=.venv/bin/python
SEED=$1; shift
ss -ltn | grep -q ":8200 " && { echo "8200 busy"; exit 1; }
LANGAMES_PORT=8200 setsid -f $PY tests/sim_bluff.py --serve --server-seed "$SEED" > /tmp/sim-serve-$SEED.log 2>&1 < /dev/null
for i in $(seq 1 40); do ss -ltn | grep -q ":8200 " && break; read -t 0.25 < /dev/zero 2>/dev/null; done
PID=$(ss -ltnp | grep ":8200 " | grep -oE "pid=[0-9]+" | cut -d= -f2)
timeout 900 $PY tests/sim_bluff.py --url ws://127.0.0.1:8200 --seed "$SEED" "$@" > /tmp/sim-run-$SEED.log 2>&1
RC=$?
[ -n "$PID" ] && [ "$(readlink /proc/$PID/cwd)" = "$HOME/avrana-lab/avrana-party-games" ] && kill "$PID"
for i in $(seq 1 60); do ss -ltn | grep -q ":8200 " || break; read -t 0.25 < /dev/zero 2>/dev/null; done
echo "seed $SEED args [$*] exit=$RC :: $(grep -ciE 'violation|mismatch|assert|traceback' /tmp/sim-run-$SEED.log) problem lines"
tail -3 /tmp/sim-run-$SEED.log
grep -ciE "traceback" /tmp/sim-serve-$SEED.log
