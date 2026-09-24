# ops/lab — Pi development helpers (not deploy tooling)

Copied verbatim on 2026-09-24 from `~/avrana-lab/` on the Pi, where they existed only as untracked
files. They assume the dev clone lives at `~/avrana-lab/avrana-party-games` with a `.venv`.

- `srv.sh start|stop PORT` — (re)start a dev server from the dev clone on PORT (e.g. 8196 for the
  BLUFF playtest); stops only a process whose working directory is the dev clone. Its log goes to
  `/tmp/srv-PORT.log` without timestamps — for a playtest use the timestamped command in the Avrana
  Party repo's `docs/runbooks/bluff-playtest.md`.
- `simrun.sh SEED "sim args"` — one seeded full-game simulator run against a fresh server on :8200.

The live LAN Games service (`/home/cody/LAN-Games`, port 8096) is never touched by these.
