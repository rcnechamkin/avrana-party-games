#!/usr/bin/env bash
# srv.sh start|stop PORT : a fresh BLUFF dev server from the main clone (stop by exact PID only)
cd ~/avrana-lab/avrana-party-games || exit 1
PORT=$2
pid() { ss -ltnp | grep ":$PORT " | grep -oE "pid=[0-9]+" | cut -d= -f2; }
stop() {
  P=$(pid)
  if [ -n "$P" ] && [ "$(readlink /proc/$P/cwd)" = "$HOME/avrana-lab/avrana-party-games" ]; then kill "$P"; fi
  for i in $(seq 1 60); do ss -ltn | grep -q ":$PORT " || break; read -t 0.25 < /dev/zero 2>/dev/null; done
}
case $1 in
  stop) stop ;;
  start)
    stop
    LANGAMES_PORT=$PORT setsid -f .venv/bin/python server.py > /tmp/srv-$PORT.log 2>&1 < /dev/null
    for i in $(seq 1 60); do ss -ltn | grep -q ":$PORT " && break; read -t 0.25 < /dev/zero 2>/dev/null; done
    echo "port $PORT pid $(pid)" ;;
esac
