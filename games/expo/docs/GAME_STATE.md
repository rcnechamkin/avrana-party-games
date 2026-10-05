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
| `dedup` | accepted request ids of the current attempt with their fingerprints |
| `proposal` | the pending crew decision and who has confirmed it; a captain's offer in missions 10 and 13 also names its `recipient`, the only seat that may answer |
| `result` | none, or `{status, reason}` with status `success`, `failed` or `abandoned` |
| `events`, `event_seq` | the bounded log of semantic events and the number of the newest one (AVR-246); see [Semantic events](#semantic-events) |

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
| `resolving` | none, or `{trick}`: the trick just resolved, while no seat may act (AVR-246); see [The resolving phase](#the-resolving-phase) |
| `cause`, `failures` | what a failed attempt is attributed to, and the kind of each task failure (AVR-246); see [Failure causality](#failure-causality) |

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
- The event log is in sequence order, no longer than its bound and not ahead of its counter. A
  table is resolving only between two tricks of an attempt still in play, for the trick just
  resolved (AVR-246).

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

Between a completed trick and the next one the table is briefly **resolving** (AVR-246): `phase`
is already `before_trick`, a separate mark holds every seat's command until the server settles
it. See [The resolving phase](#the-resolving-phase).

## What each viewer receives

`Engine.view(seat)` builds the payload on the server. A seated human gets the public part plus
`me`. Everyone else (platform watchers, a TV, Party spectators) gets the public part with
`me = null`.

| Public | Private to its owner | Never sent |
|---|---|---|
| mission definition, seats, captain, leader, turn | own hand | other hands |
| trick in progress, the most recent resolved trick only | own legal cards and the reason play is unavailable | Tonoja's covered cards |
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
| `lifecycle_transitional`: true only under a Party that does not name its host yet (adapter) | | |
| `events`, `event_seq`: the events of the latest resolved trick and after (AVR-246) | own declaration in a currents `COMMUNICATION_SENT` | events of earlier tricks and earlier attempts; the rest of the log |
| `resolving`: the trick being resolved, with `until` (adapter); `cause` of a failed attempt | | |
| each task's `state`: PENDING, ACTIVE, COMPLETED, FAILED, IMPOSSIBLE | | |

Requirements met: no viewer receives another seat's legal cards; unseated viewers cannot act;
identity is the authenticated connection, never a field in the message. In currents the
declaration is sent to its author only.

## Commands, ordering and repeats

Every command carries the attempt number, the revision it was built against, and a request id
chosen by the client. In order:

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
connected, except for the `away` list that gates commands. Reconnect changes `away`, raises
`revision` and adds one `PLAYER_RECONNECTED` event (AVR-246), and nothing else
(`Engine.presence`).

## Restoration after a server restart

Two modes:

| Mode | Behaviour |
|---|---|
| Default | the table lives in memory; a server restart loses it |
| `EXPO_SNAPSHOT_PATH` set to a private file | after every accepted command the adapter writes one JSON snapshot (engine state, random state, settings, the seated players' platform records) by temporary file, flush, fsync and atomic replace |

With the snapshot file:

- A command whose snapshot cannot be written is rolled back and reported as a storage error. The
  table in memory stays as it was.
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

## Semantic events, failure causality and the resolving phase

Added 2026-10-04 (AVR-246; was deferred entry E-X1). The product intent is in two
**non-canonical** drafts kept beside this file,
[STATE_DRIVEN_GAMEPLAY_BEHAVIOR_SPEC](STATE_DRIVEN_GAMEPLAY_BEHAVIOR_SPEC.md) and
[MISSION_GAMEPLAY_UI_UX_SPEC](MISSION_GAMEPLAY_UI_UX_SPEC.md). They are reference only: this
section, the code and the tests are the contract, and what was not built from the drafts is listed
in [RECONCILIATION](RECONCILIATION.md#avr-246-2026-10-04).

Nothing here changes a rule. Which cards are legal, who wins a trick, when a task is complete or
lost and when a mission ends are exactly what they were; the engine now also reports them.

### Semantic events

The engine keeps a log of what happened, as meaning (`Engine.s['events']`). An event is written in
the same transaction as the change it reports, so a rejected command writes none. An event never
says how to show, sound, vibrate or time anything and carries no fiction: that is the client's
business (AVR-267). Nothing in the engine reads the log to decide a rule
(`test_the_engine_never_reads_the_log_to_decide_a_rule`).

Every event has `seq`, `type`, `attempt`, `mission` (the mission's number) and `trick`. `seq`
counts from 1 for the life of the table, rises by one per event and is never reused, across
attempts and missions. `trick` is the trick the event belongs to: 0 before play begins, otherwise
the trick in progress, and for the events of a resolution the trick that was resolved.

| Type | When | Fields besides the common ones |
|---|---|---|
| `MISSION_MODIFIER_ACTIVATED` | when an attempt is prepared, once for each thing it changes from the base rules, and when one takes effect later | `modifier`, `value`: `communication` (the mode in force when it is not `normal`; `drawn` says whether a terrain card chose it; the card itself is not named), `allocation` (when not `normal`), `objective`, `distress` (`active` when carried into the attempt, else the direction agreed), `timer` (seconds, when the clock starts), `sonar` (`before_first_trick_only`) |
| `TURN_STARTED` | when play begins; after each card that does not complete its trick; when a resolved trick is settled | `seat`, `controller` (the captain for Tonoja), `lead` (true for the seat that opens the trick) |
| `CARD_PLAYED` | an accepted `play_card` | `seat`, `controller`, `card`, `position` (1 for the lead), `lead_suit` |
| `TRICK_RESOLVED` | the card that completes a trick | `winner`, `winning_card`, `leader`, `lead_suit`, `plays` |
| `COMMUNICATION_SENT` | an accepted `communicate` | `seat`, `card`, `mode`, `token` (`personal` or `shared`), `assertion` (see masking below) |
| `OBJECTIVE_PROGRESS` | a trick is resolved, a task is still open and its owner won the trick | `objective` (task id), `scope` (`task`), `owner`, `change` (`owner_won_trick`), `owner_tricks`. It says that what the task is judged on has changed, never whether that helps |
| `OBJECTIVE_COMPLETED` | a task becomes complete; a mission objective holds at the end | `objective`, `scope` (`task` or `mission_objective`), `owner` |
| `OBJECTIVE_FAILED` | a task or a mission objective is lost | `objective`, `scope`, `owner`, `failure`, `state`, `trigger_seat`, `affected_seat`, `cards` (see causality) |
| `MISSION_SUCCESS` | the attempt succeeds | `reason`, `attempts`, `distress` |
| `MISSION_FAILURE` | the attempt fails, for any reason | `reason` (the result's sentence), `cause` (the whole causality record, or null) |
| `PLAYER_RECONNECTED` | a seated player's first connection comes back | `seat` |

**Order.** Within one command the order is fixed by the code: `CARD_PLAYED`; if the card completes
the trick, `TRICK_RESOLVED`, then the tasks in assignment order (`OBJECTIVE_COMPLETED`,
`OBJECTIVE_PROGRESS`, or `OBJECTIVE_FAILED` for the first task found lost), then the mission
objective; then `MISSION_SUCCESS` or `MISSION_FAILURE` if the attempt is decided; otherwise, for a
card that did not complete the trick, `TURN_STARTED` for the next seat. The winner's
`TURN_STARTED` belongs to the settle that ends the resolving phase, not to the card.

**Determinism.** Events contain no clock reading and no random value. The same seed and the same
commands and server events in the same order give the same log, byte for byte
(`test_the_same_seed_and_the_same_commands_give_the_same_event_stream`).

**No oracle.** An event exists only after its command was committed. Before a card is played no
view carries anything about what it will do: the views of a seat about to lose the mission and of
the same seat about to win it differ only in the public owner of the task
(`test_nothing_in_any_view_tells_a_player_what_a_legal_card_will_do_before_it_is_played`).

**Retention.** The newest 240 events are kept (`engine.EVENT_LIMIT`), across attempts. A whole
attempt is about 90 events plus its objective events, so the log holds the attempt in play and
most of the one before. It is part of the snapshot. It is kept for reconnect, review of the last
trick, a debrief, debugging and a later replay; only the part below is ever sent.

**What a viewer is sent** (`Engine.events(seat)`, in the view as `events`, with `event_seq`, the
newest sequence number at the table whether sent or not):

- only events of the attempt in play;
- of those, only the events of the most recently resolved trick and everything after it; before
  the first trick is resolved, the whole attempt so far. This is R04: only the most recently won
  trick may be looked at again. Events of earlier tricks stay on the server, also after the
  mission result;
- every field of an event was public when it happened. One field is not public and is stored
  apart: in `currents` the `assertion` of `COMMUNICATION_SENT` is kept under `private` and is
  added only to its author's own events, exactly as the view treats the declaration. A watcher, a
  spectator and every other seat receive the event without it;
- copies. Nothing a caller does to what it is given reaches the table
  (`test_what_a_viewer_is_given_is_a_copy_that_cannot_change_the_table`), and no command has a
  field through which an event, a cause or the resolving mark could be written
  (`test_no_command_can_write_an_event_or_a_cause`).

No event carries a hand, a covered Tonoja card, a sealed distress choice, a secret prediction, the
terrain card, the task deck or the random state
(`test_no_event_names_a_card_that_was_not_played_or_shown_and_none_carries_a_prediction`,
`test_no_viewers_events_depend_on_what_that_viewer_may_not_see`).

**Not reported as events:** the steps of task selection and prediction, the distress exchange, a
seat going away, the end of a table, a covered Tonoja card turning face up. The view shows them as
before.

**Reconnect.** A returning player's view carries the same events as before the drop and one more,
`PLAYER_RECONNECTED`; a client that keeps the highest `seq` it has shown can tell what is new
(`test_a_returning_player_is_announced_and_is_sent_the_same_events_again`). A client that has seen
nothing shows the table from the view itself; events are never needed to know the state.

### Failure causality

A failed attempt has a `cause` beside its `result` (state key `cause`, view key `cause`; `result`
itself is unchanged). Every field comes from public facts: the cards played, who won, who owns
the task.

| Field | Meaning |
|---|---|
| `kind` | `task`, `mission_objective`, `allocation` (the attempt ended during task selection), `deadline`, `final_trick` |
| `objective` | the task id, or the mission objective's name (`balance9`, `balance1`, `first_winner`, `final_yellow5`), or null |
| `failure` | for a task, what the evaluator found: `violated` (something the task forbids happened), `unreachable` (what it needs can no longer happen) or `unmet_at_end` (the deal ended without it). Otherwise `violated`, `unmet_at_end`, `deadline`, `captain_left_with_comparison_tasks` or `ineligible_volunteer` |
| `state` | `IMPOSSIBLE` when `failure` is `unreachable`, otherwise `FAILED` |
| `affected_seat` | the task's owner; in mission 23 the first trick's winner; the captain or the volunteer in a selection failure; otherwise null |
| `trigger_seat`, `trigger_controller`, `trigger_card` | see below; null where nobody can honestly be named |
| `action` | the committed command the failure followed: `{t, seat, controller, card}` for a play, the selection command for a selection failure, null for a deadline |
| `cards` | the cards of the deciding trick that the objective is about (the cards a task names, or the ones its selector counts), and the triggering card |
| `trick` | the trick in which it was established; 0 during task selection |
| `mission` | `{id, attempt, objective, allocation, communication, timed, distress}` |

**Who triggered it.** The engine names a seat only where that is a fact and not an opinion:

- a failure established when a trick resolved: the seat that **won the trick**, with its winning
  card. Every task evaluator is a function of who won which cards, so the winner's card is what
  decided it. This is not always the seat that played last
  (`test_the_trigger_is_the_seat_that_won_the_trick_not_the_one_that_played_last`), and it may or
  may not be the affected seat
  (`test_a_legal_card_that_loses_the_mission_is_accepted_and_names_who_triggered_it_and_who_lost`,
  `test_a_seat_that_breaks_its_own_task_is_both_trigger_and_affected_and_the_state_is_failed`);
- a failure established by one card before its trick ended (a forbidden lead, yellow 5 played out
  of place): the seat that played that card;
- a failure during task selection: the seat whose choice or answer ended the attempt;
- a condition merely not met when the deal ended, and a deadline: nobody.

It is an attribution of the deciding card, not a judgement of fault: the engine does not ask
whether another seat could have prevented it.

**Objective state.** Each task in the view has `state` beside its unchanged `status`: `PENDING`
(not in play yet), `ACTIVE` (in play, undecided), `COMPLETED`, `FAILED`, `IMPOSSIBLE`. The kind
of each failure is kept in state key `failures`.

**Limits, stated plainly.**

- `IMPOSSIBLE` is reported for the cases the evaluators always detected (a named card taken by
  another seat, too few tricks or matching cards left, a missed required trick, a split exact
  run). No new impossibility is searched for, and no mission ends earlier or later than before.
- When several tasks are lost by the same trick, the engine stops at the first in assignment
  order, as it always did: that one is the `objective`, and the others stay `pending`
  (`ACTIVE`) in the result.
- No "assist" or "enabled by" is recorded for a success: the engine cannot derive one reliably.
- A success has no cause.

### The resolving phase

When a card completes a trick and the mission is not decided by it, the table is **resolving**:
state key `resolving` is `{trick}`, the trick just resolved. Everything about the trick is already
decided and in the state (winner, task statuses, the next leader); what waits is the next action.

- While resolving, every seat's command is refused with `resolving` "The trick is being
  resolved." and changes nothing. The view says so: `resolving` is set, `me.legal_cards` and
  `me.communication_options` are empty and `me.play_reason` is that sentence. `phase` stays
  `before_trick` and the view's `stage` with it.
- It ends by `Engine.settle()`, a server event like expiry: no seat can send it, it does not wait
  for a seat that is away, and it is never refused. It clears the mark, emits the winner's
  `TURN_STARTED` and raises `revision`.
- The engine holds no clock for it. **The adapter decides when**: it holds the trick for
  `game.RESOLVE_HOLD` (0.8 s) on the monotonic clock, arms the session's one timer for that
  moment (a mission deadline waits behind it), and settles when the timer fires. The view the adapter
  sends adds `resolving.until`, the wall-clock moment the next trick opens, for a client that
  wants to time its presentation to it.
- **It cannot strand a table.** A command that arrives after the hold settles the trick first,
  timer or no timer (the command itself is then stale, and the next one is accepted). A restore
  settles at once: the hold is not saved, and nobody is watching a table that has just been
  restored. A refused command does not move the moment. Going away does not stop it
  (`test_a_command_after_the_hold_settles_the_trick_even_if_the_timer_never_fired`,
  `test_a_table_cannot_stay_resolving_when_everyone_leaves`,
  `test_a_restart_during_a_resolving_trick_restores_a_table_that_is_not_held`).
- A trick that ends the mission is never resolving: the result is its own boundary, and nothing
  delays Retry, Next or End.
- **A real-time mission's clock stands while a trick is resolving.** Nobody may act, so no time
  is the crew's: `Engine.observe_time` records no expiry meanwhile, and `Engine.settle(credit)`
  moves the deadline by the time the adapter held the table (at most `RESOLVE_HOLD`, never the
  extra time a lost timer added). The crew has the same seconds to act as before the hold
  existed; the attempt lasts 0.8 s longer on the wall clock for each trick. A restore credits
  nothing: what downtime costs a timed attempt is decided by the clock rules above
  (`test_a_missions_clock_stands_while_a_trick_is_resolving_and_the_hold_is_credited`,
  `test_the_hold_and_a_mission_deadline_share_the_one_timer_and_the_hold_is_credited`).

Why this design, and what was rejected:

| Alternative | Why not |
|---|---|
| a new `phase` value `resolving` | the previous build refuses a snapshot whose phase it does not know, so it would need a new snapshot format; and every place that reads the stage would change. A separate mark keeps format 1 readable in both directions and the existing client untouched |
| let the next accepted action end it, with no refusal | no boundary: a fast phone plays into the moment the others are still being shown the trick |
| a deadline inside the engine state, like `expiry` | a monotonic moment in a snapshot means nothing after a reboot (the E-D7 problem), and a presentation duration would live in the rules engine |
| wait for every phone to acknowledge | one stalled or absent phone would hold the table (the E-D2 class of defect) |
| hold the last trick of a mission too | the result already stops play; a hold would only refuse Retry, Next and End for a moment the client does not expect |

### Snapshot

Format `version` stays 1. The keys `events`, `event_seq`, `resolving`, `cause` and `failures` are
additive: a snapshot written before them is read as a table with an empty log, nothing resolving
and no cause (`test_a_snapshot_written_before_the_events_existed_is_read_with_an_empty_log`), and
the previous build reads a snapshot that has them, ignoring them (checked by hand against the
build before this change; it then plays on without a hold). A snapshot whose log is out of order,
longer than the bound or ahead of its counter, or whose resolving mark does not name the trick
just resolved in an attempt still in play, is refused like any other invalid snapshot.

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
  saved, and a restored table gives the crew the moment again.
- **An away seat** still stops Begin, Retry and Next (AVR-240 owns recovery). It never strands
  the Party: the host's end is the Party's and does not pass through the table.
- No seat ends a Party round from inside the game. The host ends it from the Party, whose signed
  `end` releases the room; the Party records `ended_by_host`. A standalone table still closes by
  the crew's `end`, reporting `completed` if a mission result stood and `abandoned` otherwise.
- A mission result is not the end of the Party session: the table stays, the result takes over
  every phone, and the host retries, moves on or ends EXPO.
