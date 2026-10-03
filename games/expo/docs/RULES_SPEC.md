# EXPO: canonical rules specification

Status: canonical, reconciled 2026-10-03 (AVR-215). This document states what the game is supposed
to do and which source says so. It does not describe the code; where the code differs, the
difference is an entry in [RECONCILIATION](RECONCILIATION.md), never an edit here.

Companion contracts: [GAME_STATE](GAME_STATE.md), [ACTIONS](ACTIONS.md),
[MISSION_MODEL](MISSION_MODEL.md), [VTT_REFERENCE](VTT_REFERENCE.md) (sources, pins, conflict
register), [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md) (architecture, test matrix, next work).

Words used precisely:

- **MUST**: required behaviour established by a source.
- **POLICY**: an Avrana digital decision where no source speaks. Each has a P number and an owner
  status in [RECONCILIATION](RECONCILIATION.md#digital-policy-audit).
- **BLOCKED**: content that stays disabled until a conflict (C number) is resolved.

## Sources and authority

EXPO is the internal working title of Avrana's rules-enforced adaptation of a published
cooperative trick-taking card game. Intended behaviour is derived in this order; a lower source
never silently overrides a higher one.

| | Source | What it is | Cited as |
|---|---|---|---|
| R | The publisher's rulebook, 24 pages, imprint 691869-02-200121 (2021) | highest authority for rules | `R p9` = printed page 9 |
| L | The supplied mission logbook material | a third-party web transcription of the logbook (18 pages), **not** the publisher's document; it omits values and repeats one mission's text | `L M11` = mission 11 |
| V | VirtualTabletop "The Team II", pinned at upstream commit `03c41d8` | a manual digital tabletop, not a rules engine; data source for task identities and difficulties | `V` |
| A | Existing Avrana Party and Games conventions | platform lifecycle only, never game rules | `A` |

Neither R nor L is in this repository: the repository is public and they are the publisher's
copyrighted material. They are identified by hash in [VTT_REFERENCE](VTT_REFERENCE.md#pins), cited
by page and described in our own words. Rule text below is paraphrase, not quotation.

Base rules (R01 to R10) are immutable: no mission changes them unless a source says so explicitly.
Mission-specific behaviour is specified separately in [MISSION_MODEL](MISSION_MODEL.md).

## R01 Cards and deal

Sources: R p2, p7, p21; V deal routine.

- MUST: 40 playing cards. Four color suits (pink, blue, green, yellow) ranked 1 to 9, and four
  submarine cards ranked 1 to 4. Reminder cards, tokens and task cards are not playing cards.
- MUST: with 3, 4 or 5 crew seats, shuffle all 40 and deal them all face down, as evenly as
  possible: 14/13/13, 10 each, or 8 each (R p7).
- MUST: with three seats the extra card stays in its hand and is never played: the attempt has 13
  complete tricks. It may be submarine 4 (R p23). Planned tricks are 13, 10 and 8.
- MUST: every new attempt reshuffles and redeals (R p11).
- POLICY P01: the seat that receives the first card is drawn from the game's private random
  source, so the three-seat extra card is not tied to seat order.
- Two players: see R10.

## R02 Captain and turn order

Sources: R p9, p11, p24.

- MUST: the holder of submarine 4 is captain for the attempt. It is derived from the deal and
  announced; nobody chooses it. The captain still counts as a crew member.
- MUST: the captain selects the first task and opens the first trick. Every later trick is opened
  by the winner of the previous one. This also holds in missions without tasks.
- MUST: each seat plays exactly one card per trick, clockwise from the leader.
- MUST: seat order is fixed for the attempt.

## R03 Leading and following suit

Sources: R p3 to p5, p24.

- MUST: the leader may play any card in hand. (Mission 12's lead restriction is BLOCKED, C12.)
- MUST: there are five suits, the four colors and submarine. Every other seat must play a card of
  the led suit if it holds one. This applies to a led submarine exactly as to a led color.
- MUST: a seat with no card of the led suit may play any card. Playing a submarine then is
  optional, never required.
- MUST: nobody is ever forced to win a trick or to play a particular card among the legal ones.
- MUST: a card shown by communication is still in the hand and is subject to the same rules.
- MUST: a legal card is accepted even when it makes a task or the mission fail. R p11 gives the
  example of a legal submarine that would fail another player's task. Task conditions never filter
  legal plays.

## R04 Trick resolution and visibility

Sources: R p3 to p5, p16.

- MUST: if the trick contains any submarine, the highest submarine wins. Otherwise the highest card
  of the led suit wins. Cards of other colors can never win.
- MUST: the winner takes every card in the trick.
- MUST: won tricks are face down. Only the most recently won trick may be looked at again.
- MAY: cards won toward an unfinished task may be shown beside that task until it completes
  (R p16). This is optional and is not implemented (deferred, E-X2).
- POLICY P02: public trick counts per seat and card counts per hand are shown. Both are observable
  at a physical table.

## R05 Communication

Sources: R p5 to p7, p24; modes R p19 to p20.

- MUST: each player has one sonar token per attempt. It is usable once, only before a trick and
  never during one, and only after all tasks are distributed (R p5). It is available again on the
  next attempt.
- MUST: to communicate, a player shows one color card from hand and declares exactly one of:
  highest, only, or lowest card of that color in the hand. The declaration must be true at that
  moment. A card that is none of the three cannot be shown.
- MUST: submarine cards can never be communicated.
- MUST: the shown card stays in the hand and is played normally.
- MUST: the declaration is never changed or withdrawn, even when later plays make it untrue.
- MUST: when the shown card is played, its reminder is removed. The token stays spent.
- MUST: any player may communicate at a trick boundary, not only the leader.
- AMBIGUITY C10: R does not say whether a player's only card of a color may be declared highest or
  lowest instead of only. POLICY P03 accepts all three truthful declarations.
- Communication modes are mission modifiers, specified in
  [MISSION_MODEL](MISSION_MODEL.md#communication-modes): normal, currents, rapture of the deep,
  unfamiliar terrain, none.

## R06 Task generation and selection

Sources: R p8 to p10, p12, p18.

- MUST: a mission's challenge is a total difficulty, not a number of cards (R p8). L's captions say
  "N tasks"; R controls (C15).
- MUST: each task has three difficulty values, for 3, 4 and 5 crew seats. Two players with Tonoja
  use the three-seat value (R p22).
- MUST: draw from the shuffled task deck one card at a time. Take the card if its difficulty does
  not exceed what is still needed, otherwise skip it, until the total is exactly the target.
- SHOULD: used tasks stay out of the deck until it runs low, then are reshuffled in (R p8, a
  suggestion). POLICY P04 defines the exact mechanics (C09).
- MUST: drawn tasks are public. Starting with the captain and going clockwise, each seat takes one
  task of its choice, round after round, until none remain. Seats can end with different numbers.
- MUST: passing is allowed only if there were fewer tasks than seats when selection began. Even
  then every task must be taken within one circuit, so a seat may pass only while enough later
  seats remain to take what is left. With as many tasks as seats or more, nobody may pass (R p9).
- MUST: the captain may never take a task that compares the owner's tricks with the captain's
  (R p18).
- MUST: a task belongs only to the seat that took it and never moves during play.
- MUST: prediction tasks record their number before play, openly or secretly as the task says
  (R p18). POLICY P05: the number is 0 to the planned trick count and cannot be changed.

## R07 Task and mission outcome

Sources: R p10 to p11, p16 to p19.

- MUST: a task is complete when its condition is met **and can no longer fail** (R p10). One trick
  may complete several tasks.
- MUST: the mission succeeds as soon as every task is complete. This can be before the last trick.
- MUST: if any task can no longer be completed, the mission fails at once.
- MUST: "exactly" is judged at the end of the attempt; "at least" may be exceeded (R p17).
- MUST: "in a row" means consecutive tricks; winning more tricks overall does not matter (R p17).
  A task that says "exactly N tricks, in a row" needs exactly N wins, all consecutive (L M32).
- MUST: the final trick is the last complete trick of the deal. The three-seat unplayed card can
  never satisfy a capture or final-play condition (R p7, L M27).
- MUST: multi-color illustrations on tasks mean the four color suits, never submarines (R p16).
- MUST: missions without tasks have their own condition and end only when it is decided.
- Task families and their exact conditions: [MISSION_MODEL](MISSION_MODEL.md#task-families).

## R08 Feasibility and attempts

Sources: R p13 to p14, p17.

- MUST: a failure after assignment counts as a failed attempt only if the crew could have avoided
  it. Otherwise the crew exchanges task cards as the situation requires, or redeals (R p13).
- MUST: if an impossible combination is forced onto different seats, return the most recently
  revealed of the conflicting tasks and replace it with another of the same difficulty. R p14's
  example: "win the first trick" and "win the first two tricks" with too few tasks for one seat to
  hold both. If one seat could take both, nothing is replaced.
- MUST: some submarine tasks are impossible for certain deals whoever takes them; they are named on
  the cards or in the rulebook. Redeal without recording an attempt (R p14, p17). The list is in
  [MISSION_MODEL](MISSION_MODEL.md#deal-exceptions).
- MUST: an avoidable bad assignment is a failed attempt (R p13 gives an example).
- MUST NOT: nobody, including the software, tells the crew during play that the mission is
  already lost on the basis of hidden cards (R p13).
- AMBIGUITY C20: R does not spell out the case where the captain is the only seat left for a
  captain-comparison task. See RECONCILIATION Q9 and AVR-239.
- POLICY P06: an attempt is counted when the crew begins play. Setup corrections before that are
  free. A failure during selection that the crew could have avoided is counted.

## R09 Distress signal

Sources: R p14 to p15.

- MUST: optional. After cards and tasks are assigned and before anyone communicates or plays, the
  crew may activate distress for the current mission.
- MUST: on activation every player passes exactly one card to the same neighbour, all left or all
  right. Submarines may not be passed. Either everyone passes or nobody does.
- MUST: distress stays active until the mission is completed. At the start of each later attempt
  the crew may pass again or decline; it stays active either way.
- MUST: the recorded number of attempts for the mission rises by one, once.
- POLICY P07: choices are sealed until everyone has chosen, then exchanged at once.
- BLOCKED C11: distress with two players and Tonoja.

## R10 Two players with Tonoja

Sources: R p21 to p22.

- MUST: set submarine 4 aside. From the other 39 cards lay seven face down in a row and seven face
  up on top of them. Shuffle submarine 4 back in and deal the remaining 26 cards, 13 to each
  player. (The page number glyphs are damaged in text extraction; the count was confirmed against
  the printed page, C01.)
- MUST: the captain is the player holding submarine 4, so always a human.
- MUST: Tonoja is a third crew member with a seat the players choose. Task rules for three seats
  apply.
- MUST: the captain alone decides Tonoja's task choices, passes and card plays. The other player
  may not discuss them.
- MUST: Tonoja plays only face-up cards. A covered card is turned up only after the trick in which
  its covering card was played, never during it.
- POLICY P08: Tonoja follows suit from its face-up cards only. A covered card of the led suit does
  not oblige it.
- Consequence: 13 complete tricks; Tonoja ends with one card.
- BLOCKED C11: Tonoja with distress, shared sonar and volunteer missions.

## What the game cannot enforce

The engine enforces card ownership, suit rules, communication timing, truth and resources, task
ownership, task and mission outcomes, and secrecy of what each client receives. It cannot enforce
silence, spoken hints, or the ban on discussing Tonoja. The client states those rules; it does not
police them. Platform chat is outside the game.
