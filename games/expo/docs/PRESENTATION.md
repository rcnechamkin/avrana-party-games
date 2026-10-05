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
| B. Crew strip | `#seats` | per seat: name, Captain mark, Party Host tag where the Party names a host who is seated, turn marker, hand size and tricks, radio state (ready, used, the card being shown, shared supply, off), "Reconnecting…" for a seat that is away |
| C. Shared trick | `#stage` | each card in its player's place, numbered in play order from the lead, the lead marked and its suit named; for a resolved trick the winner the server resolved, marked WON, the others tucked. A pending crew decision, mission preparation and the open radio take this zone's place |
| D. Crew objectives | `#objectives` | up to two task cards (owner, text, the task's `state`: Standby, Active, Done, Failed, Lost), and done-of-total; opens the full task list. The log of the latest trick is the button beside it |
| E. Hand and controls | `#hand-panel`, `#dock` | the hand, the server's reason when play is unavailable, the Radio control, Play; table control (Party Host or crew) stays in its own half of the dock |

The mission stage is 15 to 25 percent of the screen height at every phone size tested (16.5 % by
default, 15.5 % on screens of 700 px or less, 18 % from 820 px). On screens of 700 px or less the
status line moves between the two top-bar buttons so that its row goes to the board; the word
"Connected" is not spelled out there, and a lost connection still is ("Reconnecting…").

**Not shown: who is winning an unfinished trick.** The view and the events do not say, and the
client does not work out a rule. See "Not built".

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

Each radio state is named by the fiction and stated as a rule beside it: clear (one transmission
each), degraded (`currents`: the card is shown, its meaning hidden), shared (`rapture`: one
supply for the crew), off (`none`). On `COMMUNICATION_SENT` the sender's tile carries the card
for everyone, the mission stage and the live region say it in words, and the director pulses the
sender's tile and, for the others, the stage.

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
director at all.

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
| `node tests/expo_director_test.mjs` | the planner's cases above; every engine event has a tier and every duration is inside it; a resolution fits the hold or is not played; the three fidelity tiers (only `high` moves, `low` animates nothing, only `transform` and `opacity` are animated); the director's source has no sender and is called only through the guard; a frozen view; the sound and haptics gate; the slots manifest; nothing fetched from outside |
| `tests/playtest_expo.mjs`, `tests/playtest_expo_party.mjs` with `tests/_expo_phone.mjs` | in a real browser on five phone sizes: the zones in order and the stage's share of the screen; the crew strip; the trick; card states; the radio flow; the resolving hold and the director's timing against it; reload mid-trick, a reconnect on a resolving view and a reload on a result; the three shapes of a cause; no frame sent with the director on the stack |

Both playtests take `EXPO_FX=high|medium|low|off` and `EXPO_MOTION=reduced`. The runs made for
this change are in [the report](RECONCILIATION.md#avr-267-2026-10-05).

## Not built

- **Final art, audio, a real phone.** Placeholders only; simulated phones only.
- **The current winner of an unfinished trick.** Needs a field from the server (for example the
  leading seat on `CARD_PLAYED`); working it out in the client would be a rule in the client.
- **Fiction per mission and cinematic templates per cause.** One placeholder line per kind of
  failure.
- **A replay or recap of an attempt.** The server sends the latest trick only.
- **Collecting a trick off the table.** A resolved trick stays, tucked, until the next card, as
  AVR-275 built it.
- **A TV view, Canvas or WebGL effects, sprites.** DOM, CSS and inline SVG only.
- **Avatars on the board.** Names only; `crew.portrait` is a slot.
