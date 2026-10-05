# EXPO: actions, legality and rejection

Status: canonical, reconciled 2026-10-03 (AVR-215). One contract per player-visible action, as the
engine implements it today, with the rule each condition comes from. Rules:
[RULES_SPEC](RULES_SPEC.md). State and ordering: [GAME_STATE](GAME_STATE.md). Differences between
this contract and the intended rules are E-entries in [RECONCILIATION](RECONCILIATION.md).

## Conventions

**Authority.** The engine (`games/expo/engine.py`, `Engine.apply`) decides. The client may hide or
disable a control; the engine rejects the same thing independently. A test that removes the
client's restriction must still see a rejection.

**Envelope.** Every game command is a JSON object with exactly `t` (the verb), `attempt`,
`revision`, `request` (1 to 80 printable ASCII characters, chosen by the client; the client sends
a UUID) and the verb's own fields. Extra
or missing fields, wrong types (a boolean is not an integer) and unknown verbs are rejected.

**Common checks, in order.** These apply to every command below and are not repeated per action.

| # | Check | Code | Message shown to the sender |
|---|---|---|---|
| 1 | sender is a seated human of this table | `actor` | Only seated crew members may act. |
| 2 | nobody seated is away | `paused` | Waiting for the crew to reconnect. |
| 3 | known verb, exact fields and types | `action`, `payload` | Unknown game action. / Invalid action fields or types. |
| 4 | request id not already used with another message | `request` | This request ID was already used. |
| 5 | `attempt` and `revision` are current | `stale` | That moment has passed. Use the latest table state. |
| 6 | table not closed | `phase` | This table is closed. |
| 7 | no crew decision pending (except for `confirm`) | `vote` | Confirm or decline the crew decision first. |

**Repeats.** A message identical to one already accepted in this attempt is ignored without error
and without change. This is checked before staleness, so a retransmission after the state moved on
is harmless.

**Rejection.** Nothing changes: state, random generator and request memory are exactly as before
(the one exception: a passed real-time deadline is recorded even when the command that revealed it
is rejected). Only the sender is told, with a stable code and a plain sentence; the client shows
it as a toast. The reason never describes another player's hidden cards.

**Knowable before submission.** "Yes" means the sender's own view contains everything needed to
know the action is illegal, so the client can disable it with the right reason. "Outcome no" means
the action is legal and whether it helps or loses the mission is deliberately not computed for the
player (R08).

**The reason on an unavailable control is the server's own sentence** (AVR-263, owner decision of
2026-10-05). `Engine.reasons(seat)` works out, for the controls a crew member sees, the sentence
`apply` would reject that very request with, making the same checks in the same order, and the
view carries the result in `me`:

| Field | Control | Absent or null means |
|---|---|---|
| `play_reason` | playing any card (`play_card`) | the viewer plays now |
| `card_reasons` `{card: sentence}` | each card of the viewer's hand and each of Tonoja's face-up cards: `play_card`, or `pass_card` for a hand card during the distress exchange | that card may be sent |
| `task_reasons` `{task: sentence}` | "Take this task" on each open task (`choose_task`) | the viewer may take it for the selecting seat |
| `pass_task_reason` | "Pass selection" (`pass_task`) | the viewer may pass |
| `volunteer_reasons` `{yes, no: sentence}` | the two volunteer answers (`volunteer`) | that answer is accepted |
| `offer_reason` | "Offer all tasks" whoever is named (`assign` with `task: all`, missions 6, 10 and 13) | the viewer may offer |
| `offer_owner_reasons` `{seat: sentence}` | the same offer naming that seat | that seat may be named |

The maps hold only what is refused. A field that does not apply in the current phase or mission is
null or empty. The client shows these sentences and words none of its own for the same refusal;
such a control is disabled exactly when the view gives a reason for it. The reasons read the
public table and the viewer's own hand and nothing else, and a viewer without a seat gets none
(`me` is null). `test_at_any_state_a_reason_is_the_rejection_and_no_reason_means_accepted` sends
every one of these requests in some 1,500 states and compares: a reason is the rejection, word
for word, and no reason means the request is accepted. Controls outside the table above (a crew
decision other than the offer, a prediction, a sonar declaration, the Party Host's Begin, Retry
and Next) carry no reason field; the client hides most of them when they cannot be used.

**Mutation.** Every accepted command also increases `revision` and stores its request id.

## Platform actions (shared session layer)

These belong to the platform; EXPO only constrains them.

| Action | Legal when | Otherwise | Effect | Client |
|---|---|---|---|---|
| join (hello) | lobby with room (5 humans), or an existing seat's credential | a new credential during a table becomes a watcher (a bounded number); a Party round admits players only by ticket | seat restored with nothing changed, or watcher added | join screen; a watcher sees "Watching" |
| `ready`, `start` | lobby; 2 to 5 ready humans; the chosen mission is enabled for that count; no unrecovered snapshot | start refused with the mission's conflict reason or the recovery message; in a Party round both are refused ("The Party Host starts rounds from the Party.") | countdown, then seats are fixed in joining order and the first deal is prepared | Start disabled until the sender is ready and two are ready |
| `settings` (`mission`, `timed`, `tonoja_position`) | lobby only, valid values | ignored silently; ignored in a Party round (E-P1) | settings stored | blocked missions are listed as unavailable and cannot be chosen |
| `profile` | any time | platform rules | name or avatar | name field, avatar grid |
| `again` | platform results screen only | no effect on a live table | back to the lobby | not offered during a table |
| leave / disconnect | any time | | seat kept, marked away; table paused | status line names who is away |

## Task selection

### `choose_task {task}`

- **Phase**: `allocation`, mission allocation `normal` or `skip_captain`.
- **Actor**: the seat whose turn it is in the clockwise ring; for Tonoja, the captain (R10).
- **Legal**: the task is still in the pool; the taking seat is eligible for it (R06).
- **Illegal**:

| Condition | Code | Message |
|---|---|---|
| another allocation mode or phase | `phase` | Tasks are not selected this way in this mission. |
| not the selecting seat's controller | `turn` | It is another crew member's task selection. |
| task not in the pool | `task` | That task was already chosen. |
| the captain taking a captain-comparison task | `owner` | The captain cannot take a captain comparison task. |

- **Mutation**: task moves from pool to the seat, status `pending`; cursor advances; when the pool
  empties the phase becomes `prediction` (if any prediction task was taken) or `assistance`. If
  tasks remain and the next selecting seat can take none of them and may not pass, the attempt
  ends at once as a counted failure: phase `mission_result`, result `failed` with the reason "The
  captain was left with only captain comparison tasks, which the captain may not take. Give those
  tasks to other crew members on the next attempt." (C20). Only the captain can be in that
  position. The unassigned task stays unassigned; the crew may retry with the same or new tasks.
- **Knowable before**: yes. Outcome no: a hard or even hopeless choice is legal (R08).
- **Client**: "Take this task" on each open task, disabled with `me.task_reasons[task]`: the
  `turn` sentence for a viewer who does not control the selecting seat, the `owner` sentence for
  the captain on a captain comparison task. For the selecting seat the sentence is also written
  once under the tasks.
- **Not warned**: the client does not tell the crew that a pick will leave the captain without a
  legal task. The information is public (the tasks and the order are visible), and the mistake is
  the crew's to avoid (R08). A draw that makes it unavoidable never reaches selection: it is
  repaired during preparation ([MISSION_MODEL](MISSION_MODEL.md#generation-reuse-and-repair)).

### `pass_task {}`

- **Phase / actor**: as `choose_task`.
- **Legal** (R06): the pool was smaller than the selecting ring when selection began, **and** the
  seats still to come in this circuit are at least as many as the tasks left.
- **Illegal**: `phase` "Passing is not available here."; `turn`; `pass` "The remaining tasks must
  be assigned this round."
- **Mutation**: cursor advances.
- **Knowable before**: yes (`me.pass_task_reason`). `me.may_pass_task` is still sent and is not
  the same fact: it is the rule alone and stays true while a seat is away or a crew decision is
  pending, when the server refuses the pass. The client no longer reads it.
- **Client**: "Pass selection", shown to the viewer who controls the selecting seat and disabled
  with `me.pass_task_reason`, which is also written beside it.

### `volunteer {yes}`

- **Phase**: `allocation`, mission allocation `volunteer` (mission 16).
- **Actor**: the seat being asked: clockwise from the seat after the captain, the captain last.
- **Legal**: any yes; a no only while more seats remain to be asked than volunteers still needed.
- **Illegal**: `phase` "There is no volunteer question now."; `turn` "Answer when the captain asks
  you."; `volunteer` "The remaining crew must take the tasks."
- **Mutation**: the answer is recorded. On the first yes that seat receives every task and the
  phase advances. If that seat may not own one of the tasks (the captain and a captain-comparison
  task), the attempt ends at once as a counted failure with a visible reason (P15).
- **Knowable before**: the forced yes is (`me.volunteer_reasons.no`). `me.may_decline_volunteer`
  is still sent and is not the same fact: it is the rule alone, whoever is asked and whether or
  not a seat is away or a crew decision is pending. The client no longer reads it. The
  eligibility failure is knowable from public tasks but is not shown as a warning.
- **Client**: "Yes · take the tasks" and "No" for the asked seat, each disabled with its entry in
  `me.volunteer_reasons` ("No" when forced), and the sentence is written beside them.

### Crew decision `assign {owner, task}`

See [Crew decisions](#crew-decisions). Used by allocation modes `one`, `captain_one` (with
`task: "all"`) and `free` (one task id).

### `predict {task, count}`

- **Phase**: `prediction`.
- **Actor**: the task's owner; for Tonoja, the captain.
- **Legal**: the task is an assigned prediction task with no prediction yet; `count` is an integer
  from 0 to the planned trick count (P05).
- **Illegal**: `task` "This task does not need a prediction now."; `owner` "Only the task owner can
  predict."; `prediction` "Your prediction must be in range and cannot be changed."; a boolean or
  non-integer is `payload`.
- **Mutation**: the number is stored permanently. When every prediction task has one, the phase
  becomes `assistance`. A secret prediction is sent only to its owner's controller until the
  mission result.
- **Knowable before**: yes.
- **Client**: a number field (0 to planned tricks) and "Lock prediction" on the owner's task.

## Crew decisions

A crew decision is proposed by one seated human and takes effect when **every** seated human has
confirmed it (P09). One may be pending at a time; while it is, no other command is accepted.

The exception is the captain's assignment in missions 10 and 13 (mode `captain_one`, owner
decision Q8, built 2026-10-04, AVR-251). It is the captain's decision, not the crew's:

- the captain names the captain, or Tonoja (whom the captain controls, R10): the tasks are assigned
  in the same command and no decision is pending;
- the captain names another human: an offer is pending that only that human may accept or
  decline. Nobody else can confirm or decline it, the captain included. A declined offer leaves
  every task in the pool and the captain chooses again.

Three of the kinds below are routine steps of a table's life, not decisions the rules give the
crew: `begin`, `retry` and `next` (`engine.LIFECYCLE`). Who commits them depends on the table
(owner decision 2026-10-04, AVR-252):

- **a Party round whose Party names its host** (the view's `lifecycle` is `host`): the Party Host
  commits them, at once, with [`host`](#host-ticket-action-the-party-hosts-lifecycle-steps). A
  seat that proposes one is refused with `host` and the kind's sentence ("Only the Party Host can
  begin the mission." / "... retry the mission." / "... choose the next mission.");
- **a standalone table** (`lifecycle` is `crew`): they are crew decisions like the rest, as below;
- **a Party from before the host claim** (`lifecycle` is `crew`, `lifecycle_transitional` true):
  the same, for now. This is a deploy-order allowance (`game.HOST_CLAIM_TRANSITION`), not a
  mode: the server logs it once per session, the page says the crew decides "for now" and why,
  and it ends when that flag is set False: those steps are then the Party Host's in every Party
  round. The flag stays True through the first paired deployment (so either side can be rolled
  back) and is turned off in a separate change, after the host claim is confirmed in production.

`end` in a Party round is the Party's: every seat's `propose end` is refused with `host` "In a
Party, the Party Host ends EXPO for everyone." and the host ends the session from the Party
(avrana-party ADR 0011), which releases the room whatever the table was doing.

`distress` and `assign` are never the host's. They stay with the crew, or the captain, in every
kind of table.

### `propose {proposal: {kind, ...}}`

| Kind and fields | Legal when | Illegal: code and message | Effect when all confirm |
|---|---|---|---|
| `begin` | phase `assistance` | `phase` Finish task allocation and predictions first. | phase `before_trick`; the attempt is counted; a real-time clock starts |
| `distress {direction}` | phase `assistance`; more than two humans; direction `left` or `right` (R09) | `distress` Distress is available before play; the Tonoja exchange is not yet verified. / `direction` Choose left or right. | distress active for the mission; phase `passing` |
| `assign {owner, task}` | phase `allocation` in mode `one`, `captain_one` or `free`; owner is a seat; every affected task is in the pool and the owner is eligible; in `captain_one` the proposer is the captain | `phase` Use the current task selector. / `owner` Choose a crew member. / `captain` The captain must offer these tasks. / `task` Every task needs an eligible owner. | the task, or all tasks, go to the owner; in `captain_one` with another owner, sonar is limited to before the first trick; phase advances when the pool is empty. In `captain_one` "all confirm" means the recipient alone, and nobody when the owner is the captain or Tonoja |
| `retry {keep}` | phase `mission_result` after a failure; `keep` is a boolean (R p11) | `phase` Retry is available after a failed mission. / `payload` Choose whether to keep the tasks. | a new attempt of the same mission: new deal, sonar and progress reset, distress kept; same tasks or a new draw |
| `next {mission}` | phase `mission_result` after a success; the mission exists and is not blocked | `phase` Complete this mission first. / `mission` with the blocking conflict's reason | the log entry was already written at success; distress and attempts reset; the new mission is prepared |
| `end` | any phase | none | result `abandoned` unless a mission result already stands; phase `closed`; the platform shows its results screen and reports the outcome |

- **Actor**: any seated human.
- **Field types**: `kind`, `direction`, `owner` and `task` are strings, `mission` is an integer
  and `keep` is a boolean. A proposal with a key missing, a key too many or a value of another
  type (a number, a list, an object, null; a boolean is not an integer) is rejected with
  `payload` Invalid crew decision. in every phase and every allocation mode, before the proposal
  itself is looked at. The checks common to every action come first (a seated actor, nobody
  away, a known action, the action's own fields and scope: a `proposal` that is not an object is
  `payload` Invalid action fields or types.). Nothing is stored and the request is not remembered.
- **`task`**: in mode `free` it is the id of one task in the pool. In modes `one` and
  `captain_one` the tasks go together and it is the word `all`; any other string is rejected
  with `task` These tasks go together.
- **Mutation on propose**: the proposal is stored with the proposer's confirmation. A `captain_one`
  offer also stores its `recipient`; a `captain_one` assignment to the captain or Tonoja stores
  nothing and takes effect at once.
- **Knowable before**: yes for every row.
- **Client**: controls appear only in the matching phase. In the stage: "Distress ← left" and
  "Distress → right" (hidden for two players), "Offer all tasks", "Propose owner". In the dock's
  table zone: "Begin without passing" (or the host's "Begin mission") and "End table". On the
  result: "Retry same tasks", "Retry new tasks", "Next mission". "Offer all tasks" is disabled
  with `me.offer_reason`, in words beside it: in `captain_one` the `captain` sentence for
  everyone but the captain. A seat the offer may not name (the captain, when a captain comparison
  task is among the tasks) cannot be chosen in the owner list, and `me.offer_owner_reasons` gives
  the `task` sentence beside it. "Propose owner" lists only a task's eligible owners.
- A two-player `next` to a mission refused for two players (C11) is accepted as a proposal and
  rejected when the last confirmation tries to prepare it; the proposal then stays pending until
  someone declines. The client does not offer those missions.

### `confirm {yes}`

- **Legal**: a decision is pending, the sender is one of those asked (every seated human, or the
  recipient alone for a `captain_one` offer) and has not confirmed it.
- **Illegal**: `vote` "There is no pending decision for you."
- **Mutation**: yes adds the sender; when everyone asked has confirmed, the decision takes
  effect in the same command. No clears the proposal with no other effect.
- **Client**: the decision takes the stage, the centre of the board, so it is on screen with the
  hand for whoever must answer (AVR-266): the proposal in words, the count of confirmations,
  "Agree" and "Decline" for those who have not answered, and who is still asked for the rest. The
  status line, the page's live region, reads "Your answer is needed: ...". After a mission result
  the same panel is drawn inside the result. For a `captain_one` offer the panel is headed
  "Captain's offer", names the captain and the recipient, and shows "Accept" and "Decline" to the
  recipient only.
- **Known defect**: because of common check 2, no decision can be proposed or confirmed while a
  seat is away, including `end` (E-D2, AVR-240).

### `host {ticket, action}`: the Party Host's lifecycle steps

Not a seat's command: a message on the game socket that `core/net.py` answers before the engine
is reached (`GameBinding._party_host_confirm`, then `_party_host_action`; AVR-252, AVR-275).

```json
{"t": "host", "ticket": "<a fresh Party ticket>",
 "action": {"t": "lifecycle", "decision": {"kind": "begin"}, "attempt": 3, "revision": 41}}
```

- **Who**: the Party Host, from a seat or from a Party spectator's socket. Two things must both
  hold (avrana-party ADR 0006, amendment 2026-10-04):
  1. the ticket is valid for the running session, unspent, minted for this connection's own
     participant, and carries `host: true`;
  2. the Party, asked by the game server at that moment (`POST /internal/party-session/v0/host`),
     answers that this participant is its host now.
  Nothing about the host is stored in the room, the adapter or the engine, so a succession, a
  transfer or a reconnect needs no message, and **a former host is refused at once**: tickets
  fetched while host still say `host: true`, and the Party says no.
- **Refused before the engine**: `host` "Only the Party Host can do that." (no ticket's
  participant, another participant's ticket, `host` false or absent, the Party's answer is no,
  an anonymous watcher, no Party session); `host` "The Party could not confirm its Host. Try
  again." (a ticket that is forged, expired, spent or for another session; no answer from the
  Party within 2 s; an answer that is forged or is not to this question); `host` "This table is
  not a Party round."
- **`action`**: exactly `t` = `lifecycle`, `decision`, `attempt`, `revision`. `decision` has the
  shape of a proposal of kind `begin`, `retry {keep}` or `next {mission}` (the same field
  types). There is no `request`: the ticket is single-use and the revision makes a repeat stale.
- **Legal** (`Engine.lifecycle`): the decision's own row in the table above; nobody seated is
  away; `attempt` and `revision` are current; the table is not closed; no crew decision is
  pending.
- **Illegal**: `payload` Invalid lifecycle action. / Invalid crew decision.; `strategic` "The
  crew decides that together." (`distress`, `assign`, `end`); `paused`; `stale`; `phase` with the
  row's sentence; `mission`; `vote` "The crew is deciding something. Wait for their answer."
- **Mutation**: the step takes effect in the same command, as one revision. No decision is ever
  pending and nobody is asked to confirm.
- **What the host cannot skip**: Begin before every task is allocated and every prediction made;
  Begin past a distress request the crew has not answered; Retry or Next without a result; a
  mission that is blocked. The host holds no seat's rights: not the captain's offer, not Tonoja's
  cards, not a vote the host's own seat does not have.
- **The crew's moment** (owner decision 2026-10-04): where the rules offer distress (before
  play, three or more humans, not yet used), the host's Begin is refused with `grace` "The crew
  has a moment to ask for distress first. Begin in a few seconds." for `game.DISTRESS_GRACE`
  (4 s) after the tasks and predictions are settled, once per attempt. The view's `begin_at`
  is the moment it opens. Nobody confirms or says "ready": when the time has passed and no
  request is pending, the host begins alone. A request made in that time blocks Begin by the
  pending-decision rule until the crew answers it; a declined request starts no new wait.
- **Scope**: `begin`, `retry` and `next` are everything this message can do. Any other `t`, any
  other decision kind and any extra field are refused and change nothing
  (`test_the_host_gets_begin_retry_and_next_and_nothing_else`).
- **Client**: the dock's left zone, "Party Host (table control)". The host sees "Begin in N"
  (disabled) during the crew's moment, then "Begin mission", and "End EXPO" otherwise; everyone else sees who the host is and what
  the table is waiting for. On the result the host sees "Retry same tasks", "Retry new tasks" or
  "Next mission", and "End EXPO for everyone"; everyone else sees "Waiting for <host> (Party
  Host) to choose what's next." The page draws these from `AvranaParty.isHost()`, which decides nothing: the
  server reads the ticket.

## Distress exchange

### `pass_card {card}`

- **Phase**: `passing` (after an accepted distress decision).
- **Actor**: each seated human, once.
- **Legal** (R09): the card is in the sender's hand and is not a submarine; the sender has not
  chosen yet.
- **Illegal**: `phase` "Your pass is already locked or unavailable."; `card` "Choose one of your
  color cards."
- **Mutation**: the choice is stored privately and nothing else changes. When the last player
  chooses, all chosen cards leave their hands and arrive at the agreed neighbour in one step, the
  attempt is counted, a real-time clock starts and the phase becomes `before_trick`.
- **Knowable before**: yes.
- **Client**: the hand becomes the chooser. Each card is disabled with `me.card_reasons[card]`: a
  submarine with the `card` sentence, and every card with the `phase` sentence once the viewer's
  own choice is sealed, which then also stands beside the hand. Other players see only that the
  phase is passing.

## Communication

### `communicate {card, assertion}`

- **Phase**: `before_trick` only: after the crew has begun and between tricks, never during one
  (R05).
- **Actor**: any seated human, for their own hand. Never Tonoja.
- **Legal**: all of
  - the mission's mode is not `none`;
  - mission 23: at least one trick is resolved; delegated all-tasks missions: no trick is resolved;
  - a resource is available: in `normal` and `currents` the sender has not communicated this
    attempt; in `rapture` the shared pool is not empty;
  - the card is a color card in the sender's hand and not already shown;
  - `assertion` is `highest`, `only` or `lowest` and is true of that card among the sender's cards
    of that color now. Exactly one declaration is ever legal for a card: `only` when it is the
    sender's single card of that color, otherwise `highest` or `lowest` (C10, P03). The same
    check applies in every communication mode.
- **Illegal**: one code for all, `communication`: "Communication requires an available sonar
  token, a trick boundary, and your highest, lowest or only color card."
- **Mutation**: the token is spent (personal or one from the pool); the exposure `{seat, card,
  assertion, active}` is recorded. The card stays in the hand. The declaration is never revised.
  Playing the card later clears the exposure and does not return the token.
- **Visibility**: the card and who showed it are public. The declaration is public except in
  `currents`, where only its author's own view carries it.
- **Knowable before**: yes; `me.communication_options` lists exactly the legal card and
  declaration pairs.
- **Client**: the Sonar sheet, with the eligible cards and the meanings built from those options;
  when none exist it explains why sonar is unavailable. The Sonar tab is outlined while the
  viewer may communicate.

## Play

### `play_card {card}`

- **Phase**: `before_trick` or `in_trick`.
- **Actor**: the seat whose turn it is; for Tonoja, the captain (R10).
- **Legal** (R03): the card is in the seat's playable cards (a human's hand; Tonoja's face-up
  cards); if the trick has a led suit and the seat holds that suit among its playable cards, the
  card is of that suit.
- **Illegal**:

| Condition | Code | Message |
|---|---|---|
| wrong phase | `phase` | This is not a card-play phase. |
| not the turn seat's controller | `turn` | It is another crew member's turn. |
| card not playable by that seat (not held, already played, covered) | `card` | That card is not in the playable hand. |
| a card of the led suit is held | `follow_suit` | You must follow the opening suit. |
| the deadline has passed | `stale` after the failure is recorded | (the result shows "Time has run out.") |

- **Mutation**: the card leaves the hand or column and joins the trick; a matching exposure
  becomes inactive. If it completes the trick: the winner is computed (R04), the trick is appended
  to history, Tonoja's uncovered cards turn face up, the winner becomes leader and next to play.
  Then every pending task and the mission objective are evaluated, failure before success, and the
  phase becomes `mission_result` if the mission is decided.
- **Knowable before**: legality yes (`me.legal_cards`, `me.play_reason`, `me.card_reasons`).
  Outcome no: a legal card that loses a task or the mission is accepted and the failure follows
  (R03, R08).
- **Client**: each hand card is a button, enabled exactly when `me.card_reasons` gives no reason
  for it. Tapping a card chooses it; "Play <card>" in the dock sends it, so a small card is never
  played by a slip. A disabled card's title gives the server's reason, and when no card showing
  can be chosen the same words stand beside the hand. Tonoja's face-up cards replace the
  captain's hand on Tonoja's turn and are buttons with the same reasons; the other player can
  look at them and reads why they are not theirs to play.
  A legal card is never marked, warned about or confirmed for what it may do to the mission.

## Looking at information

Not commands; they are part of every view ([GAME_STATE](GAME_STATE.md#what-each-viewer-receives)).

- The most recent resolved trick is always available; earlier tricks are never sent (R04).
- Task status is derived and shown; there is no way to mark a task done or failed.
- Cards won toward a task are not displayed (deferred, E-X2).

## Things no client can do

There is no verb to set the captain, choose a winner, complete or fail a task, move a card, reveal
a covered card, change the timer or difficulty, change the communication mode, undo a play or ask
for a redeal. Unknown verbs are rejected by common check 3.

## Server events that are not player actions

- Preparation of an attempt: terrain draw, task draw, repair, deal, deal-exception redeal, captain.
- Trick resolution, task and objective evaluation, Tonoja reveals.
- Real-time expiry: checked on every command and on the adapter's timer tick, so it fails the
  mission with no traffic at all. It is measured on the monotonic clock; a restored timed attempt
  whose elapsed time cannot be proven ends at once ([GAME_STATE](GAME_STATE.md#restoration-after-a-server-restart)).
- Presence changes.
- Restore from a snapshot.
