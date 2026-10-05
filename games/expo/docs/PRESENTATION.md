# EXPO: the mission board and its presentation layer

Status: canonical, written 2026-10-05 (AVR-267). This is the client's presentation **as built**:
the five-zone phone board, the presentation director, the fidelity tiers and the asset slots.
The engine's side (semantic events, failure causality, the resolving phase) is in
[GAME_STATE](GAME_STATE.md#semantic-events-failure-causality-and-the-resolving-phase); the
one-viewport contract it builds on is the AVR-275 report in
[RECONCILIATION](RECONCILIATION.md). Two **non-canonical** drafts gave the intent
([MISSION_GAMEPLAY_UI_UX_SPEC](MISSION_GAMEPLAY_UI_UX_SPEC.md),
[STATE_DRIVEN_GAMEPLAY_BEHAVIOR_SPEC](STATE_DRIVEN_GAMEPLAY_BEHAVIOR_SPEC.md)); where they differ
from this file, this file and the code win. What was not built is listed at the end and in
[the AVR-267 report](RECONCILIATION.md#avr-267-2026-10-05).

**What this is not.** No final artwork, no audio and no real-phone acceptance exist. Every
visual is a neutral placeholder in a named slot. The product rule is "the cards are the game; the
wasteland is the experience": nothing here decides a rule, and the game is the same with all of
it switched off.

## Boundary

| Part | File | May | May not |
|---|---|---|---|
| Board | `web/client.js`, `web/expo.css`, `web/index.html` | draw every zone from the view; send the player's intentions | decide legality, a winner, a task's state or a result |
| Director | `web/director.js` | read a frozen copy of the view and the page; add transient effects (Web Animations on `transform` and `opacity`, its briefing strip, haptics) | send anything; write game state; disable, cover or delay a control; be needed to play |
| Slots | `web/slots.js`, `--slot-*` in `expo.css`, `#expo-slot-*` in `index.html` | name where final art, audio and haptics go | hold anything fetched from outside the appliance |

The board is complete without the director. `client.js` draws the whole view first, then calls
the director inside a guard: a throw is caught and counted, and after three the director stands
down for the rest of the page's life. The director is created with a clock, the per-browser
preferences, the slots and two naming helpers; of the connection it is given only the clock.
Its source contains no sender, which a test checks.

## The five zones

One viewport, phone first; the trick is the only flexible row.

| Zone | Element | Shows (all from the view) |
|---|---|---|
| A. Mission stage | `#mission-stage` | mission number, trick counter, timer; the mission's objective in one line; a conditions chip (attempt, clock running, distress active, or the result); a radio chip (clear, degraded, shared with the tokens left, off); the newest two events in words; the placeholder environment behind a scrim |
| B. Crew strip | `#seats` | per seat: name, Captain mark, Party Host tag where the Party names a host who is seated, turn marker, hand size and tricks, radio state (ready, used, the card being shown, shared supply, off), "Reconnecting…" for a seat that is away (in place of its hand size and tricks) |
| C. Shared trick | `#stage` | each card in its player's place, numbered in play order from the lead, the lead marked and its suit named; for a resolved trick the winner the server resolved, marked WON, the others tucked. A pending crew decision, mission preparation and the open radio take this zone's place |
| D. Crew objectives | `#objectives` | up to two task cards (owner, text, the task's `state`: Standby, Active, Done, Failed, Lost), and done-of-total; opens the full task list. The log of the latest trick is the button beside it |
| E. Hand and controls | `#hand-panel`, `#dock` | the hand, the server's reason when play is unavailable, the Radio control, Play; table control (Party Host or crew) stays in its own half of the dock |

The mission stage is 15 to 25 percent of the screen height at every phone size tested (16.5 % by
default, 15.5 % on screens of 700 px or less, 18 % from 820 px). On screens of 700 px or less the
status line moves between the two top-bar buttons so that its row goes to the board; the word
"Connected" is not spelled out there, and a lost connection still is ("Reconnecting…").

**The status line is always read whole** (owner direction 2026-10-05). It is the one live
instruction. Three things make that true at every size, 360x600 included:

- *Sentences of bounded length, in the status line only.* There, a sentence that waits for people
  names one and counts the rest ("Waiting for Ava and 2 more to reconnect. Your table is
  preserved."); the crew strip and the crew sheet name every seat, and a decision in the trick's
  place lists everyone who has not answered, by name. A decision's status asks its question
  without the sentence of consequence ("Your answer is needed: Activate distress and pass one
  color card left?"); the decision itself shows both sentences.
- *Its own place first.* A strip above the board (two lines), or between the top-bar buttons on a
  screen of 700 px or less (three lines).
- *Room taken from the mission stage when that is not enough.* `fitStatus` (client.js) measures
  the line after every draw. A sentence that does not fit its place is shown whole over the
  mission stage's lesser lines (the objective's line, the two chips, the news) under the
  mission's title, trick counter and clock, which stay. Those lines come back with the next
  shorter sentence. The mission stage's size does not change.

**A decision's answers are in the dock** (owner decision, 2026-10-05: "When a decision requires
an answer, Agree / Decline temporarily replace Radio / Play in the action dock. Once the decision
resolves, the normal Radio / Play controls return. This is intentional responsive behavior, not a
temporary hack."). In the trick's place a decision is its sentences: the
question, then for someone who must answer the count and "Your answer is below, beside your
hand.", and for someone waiting the full list of who has not answered. Its heading is for a
screen reader only. The two answers (Agree or Accept, and Decline) take the place of Radio and
Play in the dock, under "Your answer (decision)", until the decision is answered: there they are
whole 44 px targets at every size and seat count and can never be scrolled out of reach, and the
sentences have the whole of the trick's place. (On the result, the answers stay under the
question.) `longestStatusesFit` asserts both answers on screen and full targets wherever the
viewer must answer. The reason the hand cannot be played wraps instead of being cut.

While a long sentence is over the mission stage on a short screen, a lost connection is said
("Reconnecting…") in the place between the top-bar buttons that the status line left. `fitStatus`
runs after every draw, when the connection's words appear or go, and on the Party's countdown
tick.
`criticalTextWhole` (tests/_expo_phone.mjs) asserts that the status line, a decision's sentences,
the radio's sentence and rule and the hand's reason are not cut by an ellipsis, a line clamp,
their box, a scrolled panel or the screen; `longestStatusesFit` draws the longest status
sentences the page can produce with 14-letter names of W at all five phone sizes and asserts the
same, with the one-viewport contract.

**A narrow crew tile keeps its name.** With four or five seats on a 360 px screen a tile is about 65 to 80 px wide. The
name's row carries the turn marker, the Captain mark and the name, and nothing else: the hand
size and tricks are abbreviated ("8c · 0t"), the radio state is its icon and one word, and the
Party Host tag is the letter H on the second line (the tile's label for a screen reader and the
crew sheet say "Party Host" in full). With three seats it is the letter H beside the name (HOST
did not leave a four-letter name whole at 360 px beside the turn marker and the Captain mark),
with two it reads HOST, and on screens taller than 700 px the roles are spelled out under it. The playtests require every name whole and at least
28 px of the row left for it.

**Who is winning an unfinished trick** is the view's `trick_leading`, the server's word (the
function that resolves a trick, asked about the cards on the table: see
[GAME_STATE](GAME_STATE.md#the-seat-leading-an-unfinished-trick)). That seat's place in the trick
carries the word WINNING, with an outline; the lead keeps LEAD, and a seat can carry both. The
live region carries "Ava is winning the trick." after the news. The intent is that a screen
reader hears it when it changes and not with every card; that is not established: `#status` is
`role="status"`, which is announced whole by default, so a reader may repeat the sentence with
each change of the line, and no screen reader has been listened to. The page compares seats with
that field and never looks at a card to decide anything. What guards that is behaviour:
`trickShows` requires the tag on exactly the seat the view names, in a real browser, and the
field comes from the server. A static test also catches the obvious forms of card arithmetic in
`client.js` (a card's number made into a number, compared or sorted); it is a tripwire and can be
written around. It is public table state: nothing in the hand changes appearance because of it,
and `trickShows` asserts that.

**A timed mission's clock.** The deadline never moves (owner decision 2026-10-05). The chip reads
"Clock running" until `expiry` is reached on the server's clock and "Clock at zero" after, and
the status line then reads "The mission clock is at zero"; the page's own tick redraws both the
moment it happens. When that happens while a trick is held, the cards still say "The trick is
being resolved." (true), and no outcome is shown until the server sends the result. A deadline's
cause names no trick and no card on the result (its `trick` is one that never opened).

## Card states

| State | Look | Source |
|---|---|---|
| Legal | normal | `me.legal_cards` |
| Hard-illegal | muted (opacity 0.5), readable, cannot be chosen; the reason is text beside the hand | not in `me.legal_cards`; reason from `me.play_reason`, or a sentence written to equal the server's refusal of the same request (the playtest compares them; six other reasons still differ, E-D8, AVR-263) |
| Legal but losing | identical to every other legal card | there is no such state in the client: no view carries it and no style exists for it |
| Transmitted | a marker on the card (HIGH, LOW, ONLY, or SENT when the meaning is hidden) until it leaves the hand | the seat's own entry in `exposures` |

The playtests compare every legal card's classes, computed style and structure with every other
legal card's on the player's own turn.

## The helmet radio (Burst Transmission)

The fiction's name for the rules' communication (the server's own sentences still say "sonar").
The Radio control sits beside Play. Open, it takes the trick's place: the stage, the crew strip,
the objectives and table control dim to half; the hand lights exactly the keys of
`me.communication_options`; choosing a card shows exactly that card's list of meanings; nothing is
sent until Transmit. It closes on Transmit, on Escape, on its own button, and whenever the table
moves on or a crew decision arrives. When nothing can be sent it still opens and says why.
The sentence that names the meaning being sent ("7 yellow is your:" and the meanings beside it)
is on one line and whole. The controls that step back while the radio is open are dimmed, not
disabled: they can still be tapped.

In a two-player crew the radio is about the player's own cards. Open, it shows them and the
switch between the player's hand and Tonoja's is put away; closed, by any of the ways above, the
hand shows again whichever cards it showed before.

Each radio state is named by the fiction and stated as a rule beside it: clear (one transmission
each), degraded (`currents`: the card is shown, its meaning hidden), shared (`rapture`: one
supply for the crew), off (`none`). On `COMMUNICATION_SENT` the sender's tile carries the card
for everyone, the mission stage and the live region say it in words, and the director pulses the
sender's tile and, for the others, the stage. In the degraded state the sender's own phone, and
only that phone, shows the meaning (the server sends it to nobody else); there it is followed by
"meaning hidden from the crew", in the mission stage, the live region, the tile's label, the crew
sheet and the card's label. What everyone else sees is unchanged.

## The director

`ExpoDirector.advance(cursor, view, env)` is a pure function. It keeps the highest `seq` shown
and classifies each view:

| Situation | Result |
|---|---|
| first view after a load, or after the socket reconnects (`resync`) | settle: nothing in the view is replayed. A mission start is briefed if this tab has not briefed this attempt (a mark in `sessionStorage`) |
| the same push again | nothing |
| fresh events numbered without a break up to `event_seq` | presented once, oldest first |
| a break in the numbers, or events older than the window a viewer is sent | settle |
| `event_seq` lower than the cursor | settle |
| the tab is hidden | settle |
| more than 24 fresh events | settle |
| another attempt | settle; a mission start is briefed |

Settling means the cursor moves to `event_seq` and the board, already drawn from the view, is the
whole presentation.

A table that is restored, or a view that arrives late, can bring a trick's resolution and a
deadline's `MISSION_FAILURE` in one batch with `result` set. The failure is not about that trick,
so the trick's beat (and its card and objective beats) is not played over the result; the board
already shows both. A trick that itself ends the mission is still presented beside its result.
`event_seq` can go backwards across a server restart (a restored table numbers on from its
snapshot): the planner settles ("rewound"), replays nothing, and takes the next event as new.

A briefing belongs to the preparation. When a view arrives in which the table has left it (the
first trick has begun, a result stands, or there is no table), a running briefing is ended at
once and the mission stage is given back; so does a tap or a key.

**Event to intensity tier.** Micro (100 to 400 ms): `CARD_PLAYED`, `TURN_STARTED`,
`OBJECTIVE_PROGRESS`, `PLAYER_RECONNECTED`. Gameplay (500 to 1500 ms): `TRICK_RESOLVED`,
`COMMUNICATION_SENT`, `OBJECTIVE_COMPLETED`, `OBJECTIVE_FAILED`, `MISSION_MODIFIER_ACTIVATED`.
Cinematic (2 to 6 s): `MISSION_SUCCESS`, `MISSION_FAILURE`, and the mission briefing (5.6 s; 2.2 s
for a repeated attempt). Durations are `ExpoDirector.TIMING`.

**Effects.** A played card travels from its place in the hand (or from its player's tile) to its
place in the trick, the hand closes the gap, the tile pulses. A resolved trick: the lead suit is
reinforced, the winner comes forward, the others tuck, the winner's tile pulses. Objective and
modifier events pulse their zone. A result adds a short beat to the result screen. The briefing
runs inside the mission stage only.

**The resolving hold.** A trick's resolution is given `resolving.until` minus now minus a 60 ms
margin, at most 700 ms; under 250 ms it is not played. The server's hold is 0.8 s, so the
resolution ends before the server lets the table go. The objective's beat starts inside the hold
and may end up to about 400 ms after it; it holds nothing. A trick that ends the mission is not
held by the server and is given the full 700 ms beside the result.

**Never blocking.** No effect disables, covers or waits for a control. The briefing strip takes
no pointer events, and a tap or a key ends any cinematic beat at once.

## Fidelity tiers

Chosen per browser: reduced motion (the system's, or the suite's per-browser setting) always
gives `low`; otherwise an explicit choice (table menu, Effects: Full, Light, Still; stored as
`expo-fx`); otherwise `medium` on a device that reports 2 GB or less, two cores or less, or data
saving, and `high` on the rest. `expo-fx=off` (set by hand, for diagnosis) does not create the
director at all. Under reduced motion the three Effects buttons are disabled and the menu says
why ("Reduced motion is on for this browser, so the board stays still and this choice is off.").

| Tier | What runs |
|---|---|
| high | movement, pulses, the ambient stage (drifting haze, a slow glow), cinematic beats |
| medium | opacity pulses only: no movement, no ambient motion, no cinematic beat |
| low | nothing is animated |

All tiers have the same board, the same words and the same controls. The ambient stage runs only
at `high`, sits behind a scrim, and stops when the tab is hidden.

## Meaning is always words

Every event that carries meaning is also state or text drawn from the view: the trick and its
winner, the tiles, the task states, the chips, and a line in the mission stage with the newest
two events as sentences. The same sentences are appended, for a screen reader only, to the
existing live region (`#status`), after what is asked of the player now. Colour and motion repeat
what the words say and never say anything alone.

## A failed attempt

The result shows the server's `cause` as three lines and adds nothing: what failed (the task's
text or the mission objective, and the kind of failure), the deciding play (`trigger_seat`,
`trigger_card`, `trick`; "No single play decided it." when the server names nobody), and whose
objective it was (`affected_seat`; "own" when it is the triggering seat). When a seat is named the
page adds: "Every play was legal. This names the card that decided it, not a fault." No assist is
shown, because the engine records none. One line of fiction, keyed by the kind of failure, sits
above the facts; it is placeholder copy.

The final trick shown is `last_trick`, with the cards the cause names outlined. Only the latest
resolved trick's events reach a viewer, also after the result, so there is no replay of the
attempt and none is simulated.

## Sound and haptics

Slots and a gate, no content. `slots.js` names eleven audio slots, all empty, and ten haptic
slots. Nothing is played or felt before the first tap or key on the page, with haptics off
(`lg-haptics`) or with sound muted (`wc-muted`). A filled audio slot would play through the
gate; none is filled.

## Asset slots

Listed with their placeholders in [docs/ASSETS.md](../../../docs/ASSETS.md#expo-presentation-slots).
Final art must be made or licensed by people and recorded there with its source and licence.

## Tests

| Test | Proves |
|---|---|
| `node tests/expo_director_test.mjs` | a deadline's failure and a trick in one batch; `event_seq` going backwards after a restart; `client.js` holds no trick rule; the planner's cases above; every engine event has a tier and every duration is inside it; a resolution fits the hold or is not played; the three fidelity tiers (only `high` moves, `low` animates nothing, only `transform` and `opacity` are animated); the director's source has no sender and is called only through the guard; a frozen view; the sound and haptics gate; the slots manifest; nothing fetched from outside |
| `tests/playtest_expo.mjs`, `tests/playtest_expo_party.mjs` with `tests/_expo_phone.mjs` | in a real browser on five phone sizes: the zones in order and the stage's share of the screen; the crew strip; the trick; card states; the radio flow; the resolving hold and the director's timing against it; reload mid-trick, a reconnect on a resolving view and a reload on a result; the three shapes of a cause; no frame sent with the director on the stack |

Both playtests take `EXPO_FX=high|medium|low|off` and `EXPO_MOTION=reduced`. The runs made for
this change are in [the report](RECONCILIATION.md#avr-267-2026-10-05).

## Merging with AVR-263 and AVR-245

**AVR-263 is merged** (`main` at 7320c87, 2026-10-05). On this client every control is disabled
exactly when the view gives a reason, and shows that sentence as its title and in words:

| Control | The view's reason | Where the words are |
|---|---|---|
| a card in the hand, or Tonoja's | `me.card_reasons[card]` | the line beside the hand (`#hand-reason`) when every card showing shares it; the card's title |
| Take this task | `me.task_reasons[task]` | once under the task list |
| Pass selection | `me.pass_task_reason` | under the task list |
| the volunteer's Yes and No | `me.volunteer_reasons` | under the task list |
| Offer all tasks, and each owner in its list | `me.offer_reason`, `me.offer_owner_reasons` | under the task list; a refused owner cannot be chosen |
| Lock prediction | `me.predict_reasons[task]` | once under the predictions |
| Begin (the Party Host's, or the crew's) | `lifecycle_reasons.begin` | `data-key="begin-why"`, first in the preparation panel or last in a pending decision, inside the trick's place, which keeps its size |
| Retry, Next | `lifecycle_reasons.retry`, `.next` | under the buttons on the result |

The page words no refusal of its own and does not open Begin from its own clock (`begin_at` only
counts the wait down). With the radio open the hand is a picker: the cards the server lists are
lit, the rest are not offered, and the line beside the hand says what to do; nothing is refused
there, so no reason is shown. Kept from this branch through the merge: `#hand-reason` wraps and
is never clamped; the short-screen status place, the `.app.status-long` rules and the mission
stage's height; `criticalTextWhole`, `longestStatusesFit` and the `trick_leading` assertions.
Not taken from `main`'s stylesheet: the rule that moves a shown sonar card beside the name (this
board's crew tile has a radio line of its own at every size) and the shorter status strip at
610 px (the strip is between the top-bar buttons there). `main`'s forced worst-state check (two
humans and Tonoja, 360x600, a card shown, another seat on turn, the stage at 84 px or more)
passes on this board.

**AVR-245 is not merged.** When it meets this branch:

- its `drawSetup` writes `#status.textContent`; it must call `say(text)`. If it does not, nothing
  breaks (`say` rebuilds the line's two parts), but the sentence then skips `fitStatus`;
- its new status sentences belong in `longestStatusesFit`, and `draw()` must still end with
  `fitStatus()`;
- the setup view must carry `trick_leading` like every other view (`trickShows` requires the
  field), and a setup phase is a preparation phase for `ExpoDirector.briefable`;
- its `question()` and `seatWords()` must be reconciled with this client's `question()` (the
  status line uses the question without its sentence of consequence) and `whoOf()`.

## Not built

- **Final art, audio, a real phone.** Placeholders only; simulated phones only.
- **Acceptance.** The direction is provisional (owner note, 2026-10-05) and may be revisited
  after real-phone playtesting, which is the gate. Safari, a screen reader and accessibility
  validation have not been done.
- **Fiction per mission and cinematic templates per cause.** One placeholder line per kind of
  failure.
- **A replay or recap of an attempt.** The server sends the latest trick only.
- **Collecting a trick off the table.** A resolved trick stays, tucked, until the next card, as
  AVR-275 built it.
- **A TV view, Canvas or WebGL effects, sprites.** DOM, CSS and inline SVG only.
- **Avatars on the board.** Names only; `crew.portrait` is a slot.
