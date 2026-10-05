# EXPO: authoritative state, projections, reconnect and restoration

Status: canonical, reconciled 2026-10-03 (AVR-215). This is the state model **as built**, with the
requirements it must meet. Where the build falls short of a requirement the entry number (E-...)
points to [RECONCILIATION](RECONCILIATION.md). Rules are in [RULES_SPEC](RULES_SPEC.md); commands
in [ACTIONS](ACTIONS.md).

## Layers

| Layer | File | Owns | Must not |
|---|---|---|---|
| Rules | `games/expo/rules.py` | deck, legal cards, trick winner, truthful declarations | hold state, read a clock, use randomness |
| Content | `games/expo/content.py`, `content/tasks.json` | mission and task definitions, blocked list, content hash | contain logic that depends on a table |
| Evaluators | `games/expo/tasks.py` | task status from resolved history | mutate anything |
| Engine | `games/expo/engine.py` | the whole table state, command validation, transitions, per-viewer views, snapshots | touch sockets, files, wall clock (time and randomness are passed in) |
| Adapter | `games/expo/game.py` (`ExpoSession`) | mapping platform tokens to seats, lobby and settings, the timer tick, presence, the optional snapshot file, the outcome report | decide any rule |
| Store | `games/expo/storage.py` | atomic write of one JSON file | be imported by the engine |
| Client | `games/expo/web/` | drawing the view it is sent, sending intentions | decide legality, winner, task status or result |
| Platform | `core/session.py`, `core/net.py` | sockets, one lock around every mutation, per-viewer pushes, Party tickets | know EXPO's rules |

Every mutation runs under the binding's lock, one at a time. The client is never trusted: the
engine validates every command again whatever the client enabled or disabled.

## Engine state

One dictionary (`Engine.s`), fully serialisable as JSON. Seats are identified by the platform's
public player id (`p1`, `p2`, ...) or the literal `tonoja`. Cards are strings `suit:rank`
(`blue:4`, `submarine:4`).

Table lifetime:

| Key | Meaning |
|---|---|
| `version`, `content` | snapshot format (1) and content hash: the task catalog and every mission definition, untimed and timed, a blocked mission by its reason. A restore with other values is refused. Rules that live in the engine or the evaluators rather than in a mission definition (the mission 23 sonar rule, the two-player refusals, the deal exceptions, the task evaluators) are not in the hash: changing one needs a new format `version` |
| `humans`, `seats` | the seated players in clockwise order; `seats` also contains `tonoja` for two players |
| `timed` | the table's real-time setting |
| `attempt` | counter of prepared deals, part of every command's scope |
| `revision` | counter of accepted changes, part of every command's scope |
| `mission` | the frozen mission definition for the current attempt |
| `distress` | distress is active for the current mission |
| `attempts`, `counted` | attempts counted for the current mission; whether the current one is already counted |
| `log` | one entry per completed mission: mission, recorded attempts (with the distress surcharge), distress flag |
| `deck`, `used` | the private task deck order and the used pile. A task id is in one place at a time: the deck, the used pile or the mission in play (`selected`); no pile holds an id twice, the `pool` neither, and every id in them is an enabled task. The tasks of a mission that has ended are in the used pile and stay in `selected` until the next mission is prepared. A fixed mission (32) takes its named tasks out of both piles. A snapshot that breaks this is refused |
| `away` | seated players without a connection |
| `dedup` | accepted request ids of the current attempt with their fingerprints. An id is 1 to 80 letters, digits and `-`, so a full memory (10,000 requests) has a known size in the snapshot file |
| `proposal` | the pending crew decision and who has confirmed it; a captain's offer in missions 10 and 13 also names its `recipient`, the only seat that may answer |
| `result` | none, or `{status, reason}` with status `success`, `failed` or `abandoned` |

Per attempt (reset by every preparation):

| Key | Meaning |
|---|---|
| `phase` | `allocation`, `prediction`, `assistance`, `passing`, `before_trick`, `in_trick`, `mission_result`, `closed` |
| `hands` | each human's cards, including any shown by communication |
| `columns` | for two players: seven `{top, covered}` pairs; empty otherwise |
| `planned` | complete tricks in the deal: 13, 10 or 8 |
| `captain`, `leader`, `turn` | derived from the deal and from trick winners |
| `pool`, `selected`, `assignments`, `progress`, `predictions` | undistributed tasks, all tasks of the attempt, owners, statuses, committed predictions |
| `allocation_ring`, `pick_index`, `initial_count` | clockwise selection order, cursor, and the pool size when selection began (for the pass rule) |
| `volunteers`, `answers` | volunteer-mission answers so far |
| `communication`, `terrain` | the mode in force and the terrain card that chose it |
| `spent`, `shared`, `exposures` | players whose token is used, shared tokens left, and the shown cards `{seat, card, assertion, active}` |
| `before_first_only` | sonar allowed only before the first trick (delegated all-tasks missions) |
| `pass_choices`, `direction` | sealed distress choices and the agreed direction |
| `trick`, `history` | plays of the trick in progress; every resolved trick `{index, leader, winner, plays}` |
| `expiry` | real-time deadline, or none: seconds on the clock the adapter passes in, which is the monotonic clock. The view the adapter sends carries the same moment as wall-clock seconds for the browser's countdown |

The random generator's state is saved beside this dictionary, so a restored table continues with
the same future shuffles.

## Invariants

Checked after every accepted command and on every restore (`Engine.check`). A violation rejects the
command and rolls it back, or refuses the restore.

- The 40 cards are each in exactly one place: a hand, a Tonoja column, the trick in progress, or a
  resolved trick.
- Seats are distinct; `tonoja` exists exactly when there are two humans; the captain is a human.
- `planned` matches the seat count; there are 7 columns for two players and none otherwise.
- Every resolved trick has one card per seat, in clockwise order from its leader, and its recorded
  winner is the winner the rules compute.
- The trick in progress is a prefix of the clockwise order from the leader, and `turn` is the next
  seat.
- Every task of the attempt is enabled content and is either in the pool or assigned, never both;
  every owner is eligible for their task.
- The mission equals its current definition.

## Phase flow

```
(platform lobby / countdown, or Party roster)
        |
   prepare: terrain draw -> task draw -> repair -> deal (redeal on a deal exception) -> captain
        |
   allocation ----(no tasks)----+
        |                       |
   prediction (only if a prediction task was taken)
        |                       |
   assistance  <----------------+
        |  crew decision: begin            crew decision: distress
        |                                        |
        |                                   passing (sealed, then exchanged at once)
        v                                        |
   before_trick  <-------------------------------+        attempt counted, clock started
        |  ^   communicate (stays in before_trick)
        v  |
   in_trick --(last card of the trick)--> resolve, evaluate tasks and objective
        |
   mission_result  --retry--> prepare (same mission)      --next--> prepare (other mission)
        |
   closed  (crew decision: end, from any phase)  -> platform results -> platform lobby
```

`allocation` can also go straight to `mission_result`: a volunteer who may not own a task, or a
captain left with only captain-comparison tasks, ends the attempt as a counted failure before any
card is played.

`mission_result` is a game phase, not the platform's end screen: the crew stays at the table to
retry or go on. Only `closed` hands control back to the platform (`game_end`).

## What each viewer receives

`Engine.view(seat)` builds the payload on the server. A seated human gets the public part plus
`me`. Everyone else (platform watchers, a TV, Party spectators) gets the public part with
`me = null`.

| Public | Private to its owner | Never sent |
|---|---|---|
| mission definition, seats, captain, leader, turn | own hand | other hands |
| trick in progress, the most recent resolved trick only | own legal cards and, for each of the viewer's own controls that is unavailable, the server's reason ([ACTIONS](ACTIONS.md#conventions): `play_reason`, `card_reasons`, `task_reasons`, `pass_task_reason`, `volunteer_reasons`, `offer_reason`, `offer_owner_reasons`, `predict_reasons`) | Tonoja's covered cards |
| per-seat hand counts and trick counts | own communication options | resolved tricks before the latest |
| tasks: text, difficulty, owner, status, eligible owners | own secret prediction, until the mission result | task deck order, used pile |
| predictions that are public; whether one is committed | whether own distress choice is locked | sealed distress choices |
| shown cards and, except in currents, their declarations | own declaration in currents | random generator state |
| shared tokens left, players whose token is spent | | request memory, platform tokens |
| Tonoja's face-up cards | | |
| distress flag, attempts, log, result, deadline, who is away | | |
| the pending crew decision and who confirmed | | |
| `lifecycle`: who moves the table on, `host` or `crew` (added by the adapter) | | who the Party Host is: the game is never told |
| `begin_at`: the wall-clock moment the host's Begin opens, or null (adapter) | | |
| `lifecycle_reasons` `{begin, retry, next}`: for each step the sentence the server refuses it with now, or null (adapter and engine; [ACTIONS](ACTIONS.md#conventions)). The same for every viewer: it reads who is away, whether a decision is pending, the phase, the result and the crew's moment, and no hand | | |
| `lifecycle_transitional`: true only under a Party that does not name its host yet (adapter) | | |

Requirements met: no viewer receives another seat's legal cards; unseated viewers cannot act;
identity is the authenticated connection, never a field in the message. In currents the
declaration is sent to its author only.

## Commands, ordering and repeats

Every command carries the attempt number, the revision it was built against, and a request id
chosen by the client: 1 to 80 characters, each an ASCII letter, a digit or `-` (the client sends
a UUID). In order:

1. An expired deadline is recorded first, whatever the command is.
2. The sender must be a seated human; nobody may be away.
3. The verb and its fields must be exactly the expected names and types.
4. A request id already accepted in this attempt: the identical message is a silent no-op; a
   different message with that id is rejected.
5. The attempt and revision must be current, otherwise the command is rejected as stale.
6. While a crew decision is pending, only a confirmation is accepted.
7. The command runs; invariants are checked; revision increases by one.

Any rejection restores the state and the random generator exactly. The client sends a fresh
request id for each press and blocks a second press until the next state arrives.

Request memory holds accepted requests only. This is deliberate (decided in AVR-242; it was
recorded as shortfall E-D6 when an earlier draft asked for rejected requests to be kept too):

- A repeated rejected request cannot become an accepted duplicate. Every change of state raises
  `revision`, so the repeat is either judged against the same state and rejected the same way, or
  it is stale.
- A request refused only because the snapshot could not be written is sent again unchanged once
  the disk recovers, and must then succeed. Remembering the refusal would forbid that.
- Request memory is capped at 10,000 per attempt and a full memory refuses every command. If
  rejections counted, one seated player could fill it alone and lock the table. Accepted commands
  need the table's cooperation.

A rejected request id used again is therefore a new request, judged on its own; once accepted it
is remembered like any other.

## Presence and reconnect

No source covers disconnection; all of this is policy (P12 to P14).

- A seat is never given up during a table. When a seated player's last connection closes, the seat
  is marked away and **every** command is refused until they return. Nothing is played for them,
  no card is revealed and no bot takes over.
- A returning player is recognised by the platform credential they joined with (a browser token
  standalone, a Party ticket in a Party round). They receive the full current view: same seat,
  hand, shown card, prediction, tasks, trick and pending decision. No missed events need replaying
  because the view is complete.
- An unknown credential during a table is a watcher with the public view. Nobody can claim a seat
  by name or id.
- Several connections of one player are one player; presence changes when the last one closes.
- A real-time deadline keeps running while someone is away and still fails the mission.
- The platform's "again" cannot reset a live table.
- Shortfall: a table cannot be ended while someone is away, so a player who never returns strands
  a standalone table until the server restarts (E-D2, AVR-240).

Why this is deterministic: the engine state is the only authority and it does not depend on who is
connected, except for the `away` list that gates commands. Reconnect changes `away` and nothing
else.

## Restoration after a server restart

Two modes:

| Mode | Behaviour |
|---|---|
| Default | the table lives in memory; a server restart loses it |
| `EXPO_SNAPSHOT_PATH` set to a private file | after every accepted command the adapter writes one JSON snapshot (engine state, random state, settings, the seated players' platform records) by temporary file, flush, fsync and atomic replace |

With the snapshot file:

- A command whose snapshot cannot be written is rolled back and reported as a storage error. The
  table in memory stays as it was.
- The file has one size limit, 4,000,000 bytes, for writing and for reading
  (`MAX_SNAPSHOT_BYTES` in `games/expo/storage.py`). The bytes of the file are counted before
  anything is written. A snapshot over the limit is a failed write like any other: the command
  is rolled back, its request id is not remembered, the file stays as the last accepted command
  left it and a restart restores that table. A file over the limit is refused on start.
- Request ids alone cannot reach the limit. A full request memory (10,000 commands, every id
  80 characters) made of the largest command a seat can have accepted, a task with the longest
  id offered to Tonoja and declined, leaves a file of 3,069,966 bytes for two seats (measured).
  The issue's run, proposing to end and declining, leaves 2,744,892 (measured). Longer seat
  ids, attempt numbers and revisions add digits only: about 3.2 million bytes with a
  four-digit attempt and seat ids, by calculation from the engine's own format. That leaves
  about 0.8 million bytes for the rest of the table, which takes about 11,000.
- A table at the limit is known to be reachable only from a large file written before this
  rule (AVR-273), with request ids that are no longer accepted. Such a table refuses every
  command that makes its file larger, which is nearly every command. A proposal to end the
  table can still fit while the confirmation that would end it does not: every answer to it,
  yes or no, is then refused with `storage`, and the table cannot be ended from inside. It is
  still restored on every start. The way out is the operator's: stop the server and remove
  the snapshot file; the next start has no table.
- On start, the adapter restores the file if present. Every seated player starts away and must
  reconnect with their original credential. A table saved in `closed` goes straight to the
  platform's results.
- A file that is unreadable, has another format version or content hash, or fails the invariants
  is **not** restored and is not overwritten: the lobby shows a recovery message and refuses to
  start a new table until the file is dealt with.
- The file contains hidden hands, the random state and reconnect credentials. It must be outside
  any served directory and must never be committed.
- A Party round neither restores nor writes the file: Party tickets die with the Party session.

A timed mission and the clock (AVR-242, was E-D7):

- The deadline is kept on the monotonic clock. A step of the wall clock while the table is live,
  in either direction, neither grants nor takes time. On a host that suspends, the monotonic
  clock may stand still during the suspend and the deadline with it; the appliance does not
  suspend.
- Every snapshot records the wall clock, the monotonic clock and the kernel's identity for the
  current boot (`/proc/sys/kernel/random/boot_id`) at the moment it was written.
- A restored table with a running deadline continues only when all of this holds: the boot
  identity is readable and is the one in the snapshot, the monotonic clock has not gone backward,
  and the difference between the two clocks is what it was, within two seconds. That is a restart
  of the service on the same boot. The downtime is charged, and a deadline that passed meanwhile
  fails the mission.
- Otherwise (a reboot, even one whose clocks line up as before; a wall clock that stepped either
  way; a suspend; a host that cannot name its boot; a snapshot without the record) the timed
  attempt ends at once as a counted failure with its own reason, and that end is written to the
  snapshot so that no later restart finds the deadline still running. If that write fails, the
  next restart judges the clocks again: after a reboot the attempt ends again. On the same boot
  it ends again too, unless the clocks have come back into agreement in the meantime; it then
  has only the time the monotonic clock says is left. A saved deadline
  later than a full timer from the moment the snapshot was written, or a clock reading that is
  not a plain number of seconds within a sane range, also ends the attempt as a counted failure.
  A snapshot whose deadline is not a number, or stands beside a mission result or an untimed
  mission, is refused like any other invalid snapshot. The table itself is kept
  and the crew may retry. An appliance without a real-time clock cannot say how long it was off,
  so a reboot always ends a running timed attempt.
- A table with no running deadline restores whatever the clocks say.

## Party rounds

When Party launches EXPO (`core/party_session.py`, Party ADR 0006 and 0010):

- The roster's players are the seats, in roster order, under their Party names. The game's own
  lobby and settings are skipped (E-P1, AVR-245).
- Players are admitted by Party ticket; a browser token only watches.
- Party spectators receive the public view.
- **Two authorities** (AVR-252, AVR-275). The Party Host owns the table's routine steps (Begin,
  Retry, Next) and ends EXPO; the EXPO captain owns what the rules give the captain (the first
  lead, Tonoja's cards, the offer in missions 10 and 13) and nothing else; the crew still decides
  together what the rules say it decides together (distress, shared assignments). The host may be
  the captain, another seat or a spectator.
- **Who the host is** is never stored here. `GameSession.party_host` only records that this
  Party says who its host is (a ticket carried the claim). Each host action brings a fresh
  ticket, and the game server then asks the Party whether that participant is its host at that
  moment ([ACTIONS](ACTIONS.md#crew-decisions)): a former host is refused at once. The view's
  `lifecycle` is `host` then. At a standalone table it is `crew`. Under a Party that does not
  say it is `crew` with `lifecycle_transitional`: an allowance for deploy order that is logged
  and shown, not a way to run a Party round.
- **The crew's moment before Begin.** Where distress is available the host's Begin opens
  `DISTRESS_GRACE` seconds after the tasks are settled (`begin_at`), once per attempt. The
  moment is the adapter's (`ExpoSession._grace`, monotonic clock), not engine state: it is not
  saved, and a restored table gives the crew the moment again. While it is open
  `lifecycle_reasons.begin` is its sentence, and the table's one timer (otherwise the mission's
  deadline, which does not run before play) is set for its end: the tick pushes a state in which
  the reason is gone, so no page opens Begin from its own clock (AVR-263).
- **Why a step is unavailable** is the server's to say: `lifecycle_reasons` gives every viewer
  the sentence Begin, Retry and Next are each refused with at that moment, from the same ordered
  checks that refuse them (`Engine._lifecycle_refusals`, `ExpoSession._host_refusal`; for a table
  the crew moves on, `Engine.apply`'s refusal of the proposal).
- **An away seat** still stops Begin, Retry and Next (AVR-240 owns recovery). It never strands
  the Party: the host's end is the Party's and does not pass through the table.
- No seat ends a Party round from inside the game. The host ends it from the Party, whose signed
  `end` releases the room; the Party records `ended_by_host`. A standalone table still closes by
  the crew's `end`, reporting `completed` if a mission result stood and `abandoned` otherwise.
- A mission result is not the end of the Party session: the table stays, the result takes over
  every phone, and the host retries, moves on or ends EXPO.
