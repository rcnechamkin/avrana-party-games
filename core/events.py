"""core.events — one structured log line per player-lifecycle event, for reconstructing a session.

    <asctime> INFO EVENT {"ts": 1790000000.123, "game": "bluff", "ev": "join", "pid": 3, ...}

`grep ' EVENT ' server.log | cut -d' ' -f5-` gives clean JSON lines. Players are identified by
their public pid (and display name); tokens are NEVER logged. `ts` is epoch seconds so a playtest
can line the log up with phone screen recordings after correcting the Pi-clock offset.
"""
import json
import logging
import time

log = logging.getLogger("gamehub.events")


def event(game, ev, **fields):
    log.info("EVENT %s", json.dumps({"ts": round(time.time(), 3), "game": game, "ev": ev, **fields},
                                    ensure_ascii=False, separators=(",", ":")))
