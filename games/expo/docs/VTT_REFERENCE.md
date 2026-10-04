# EXPO: sources, reference implementation and conflict register

Status: canonical, reconciled 2026-10-03 (AVR-215). This document pins every source, says what was
taken from the reference implementation and what was rewritten, and holds the conflict register.
Rules are in [RULES_SPEC](RULES_SPEC.md); mission and task semantics in
[MISSION_MODEL](MISSION_MODEL.md).

## Pins

| Source | Identity | Verification |
|---|---|---|
| R, rulebook | PDF, 24 pages, imprint 691869-02-200121; SHA-256 `de4b8d4be29d4f769919f7c2602afdb6947e9bfe4cd20ceb1ba302f8278239b7` | read in full for this reconciliation (text extraction; damaged number glyphs on p21 checked against the page image) |
| L, logbook material | PDF print of a third-party web page, 18 pages; SHA-256 `77b80f1cd2e80e913a1bb7f647588fe094a725f57e2e16ddb44fc134acb53338` | read in full; **not** the publisher's logbook |
| V, reference | `ArnoldSmith86/virtualtabletop`, commit `03c41d80588b1552d22d8d4ce46b1376718d1cfb`, path `library/games/The Team II` | the four local snapshot files have the same git blob ids as upstream at that commit (table below), so the local copy is byte-identical |

| Snapshot | Mode (from its deal routine) | git blob id (local = upstream) | SHA-256 |
|---|---|---|---|
| `0.json` | two humans plus dummy columns | `032ea0e124638790430ede8dae9fe49d4cb2cca6` | `08e1e82ff1e1009978a302561019c70e57bd45fe7324f33358caf062a1cba63f` |
| `1.json` | three humans | `4a8e08afd05f92489f95f8dbf975a89a42d00c57` | `8ae9ab09e4afbffdcd8935a017b9036af5a11be82ffd4ea63644a368f95d462b` |
| `2.json` | four humans | `755823b335deb1b32e0d736619de62df21aece30` | `89873065496448c09d4282a767aaefcd18061d9c9053565dd39eac992ffd48b7` |
| `3.json` | five humans | `7e0d0989bc5e6622917b68f9f58ba987f1274146` | `464a55e3b23da0467271d7038bbb30484c9569a4dd516ea36053eb4315ffc962` |

R, L and the reference's files are not committed here. The repository is public; R and L are the
publisher's and a third party's material, and the reference's artwork has no established reuse
permission. Maintainers keep local copies in an ignored folder (`games/The Crew II/`, see
`.gitignore`). Anyone can re-verify V from the upstream commit; R and L can be re-verified only by
someone holding files with the hashes above (AVR-244).

## What the reference is

A manual digital tabletop: widgets, holders, drag and drop, buttons that deal and move cards. It
has no turn validator, no follow-suit check, no task evaluator and no result logic. Players move
cards and flip task cards themselves. Findings below come from reading its JSON, not from running
it.

Relevant structures (in `2.json`; the other snapshots differ only by player count):

- Playing deck: 40 card types labelled b/g/y/r 1 to 9 and a 1 to 4. `r` (red) is the rulebook's
  pink; `a` (black, "rocket") is submarine.
- `taskDeck.cardTypes`: 96 task definitions with `difficulty3/4/5`, a short text, up to three
  values, an optional footnote and CSS for the card picture.
- `missions`: `diff` (target per mission), `comm` (1 currents, 2 rapture, 3 random), `discuss`
  (free selection), `special` (prose for missions 6, 8, 10, 12, 13, 19, 21, 23, 27, 32), `timed`
  (duration, volunteers, untimed communication, untimed difficulty for 14, 15, 16, 26).
- Deal button: 14/13/13 with a random extra-card seat, 10 each, 8 each; the two-human snapshot
  reserves submarine 4, lays seven two-card columns and deals 13 each.
- Task button: a greedy scan by difficulty with a recursive reshuffle when it falls short.
- Prediction input: a free number 0 to 13 with a player-chosen "private" box. Timer: free entry.

## Reuse and rewrite

| Reference material | Disposition | Where it went |
|---|---|---|
| The 40 card identities | transformed, renamed to pink and submarine | `rules.py` `DECK` |
| 96 task ids and difficulty triplets | transformed unchanged; ids kept for traceability | `content/tasks.json` (`id`, `difficulty`, `source`) |
| Task semantics (short text, values, footnotes, CSS picture) | decoded by hand into typed parameters; never parsed at run time | `content/tasks.json` (`family`, `params`); footnotes kept as `referenceFootnote` |
| Per-count sum thresholds | transformed into per-crew parameters | `sumBelow`, `sumAbove` |
| Footnoted redeal conditions | transformed into explicit card sets | `engine.py` `_deal_exception` |
| Mission maps | used as a cross-check only; L is the higher source | `content.py` |
| Player-facing task wording | rewritten in Avrana's own words | `text`, `text_by_crew` |
| Deal, task draw, taking tricks, predictions, tokens, timer, flipping cards | rewritten as validated engine transitions | `engine.py` |
| Widget coordinates, holders, z-order, drag and drop, CSS, inheritance | not used | |
| Artwork and table background, publisher marketing images | not used, not shipped; the client draws cards in CSS with suit symbols and labels | |
| Help overlays and mission prose | not used | |

Mechanical check performed 2026-10-03: the 96 ids in `content/tasks.json` equal the 96 ids in the
reference, and all 288 difficulty values are equal. The mission targets in `content.py` equal the
reference's `diff` except missions 3 and 26, where L differs and both are blocked (C02, C07).

## Conflict register

Every row keeps its original evidence. "Now" is what the code does on 2026-10-03. A row is closed
only by source evidence or a recorded owner decision; closing changes the row, it never deletes it.
Owner questions (Q numbers) are set out in full in
[RECONCILIATION](RECONCILIATION.md#owner-decisions).

| ID | Disagreement or gap | Evidence | Now | Status |
|---|---|---|---|---|
| C01 | Two-player deal: text extraction of R p21 read as 12 cards each | The printed page shows 13 each and 14 for the dummy; V deals 13 | 13/13/14, 13 tricks | **Resolved**: extraction error, not a conflict |
| C02 | Mission 3 target | L M3: 4. V: 3 | mission disabled | Open, needs publisher page (AVR-244) |
| C03 | Missions 4, 14, 15 targets | L gives none. V: 4, 6, 6 | missions disabled | Open (AVR-244) |
| C04 | Mission 16 without the timer | L M16: no communication. V: random communication | no communication | Applied: L outranks V. A publisher page would confirm |
| C05 | "More of one color than another" tasks | R p18 text: more cards of the color "in your hand" at the end. The card picture on the same page: "I will win more". R p16: tasks are completed by winning tricks. V: won cards | two tasks disabled | Open (Q13, AVR-244) |
| C06 | Missions 20 to 22 | L M20's story adds the "never two more 1s" rule; its caption says only 10 and terrain. L M21 and M22 carry the same story text. V puts the 1s rule on mission 21 only, target 0 | mission 20 disabled; 21 has the rule and target 0; 22 has target 11 | Open for 20; 21 and 22 follow their L captions (AVR-244) |
| C07 | Mission 26 timed target | L M26: 10 timed, 12 untimed. V: 12 | mission disabled | Open (AVR-244) |
| C08 | Mission 19, hardest task to the captain | L M19 says the most difficult task. V adds "leftmost" on ties | mission disabled | Open (Q14, AVR-244) |
| C09 | Reusing the task deck | R p8 only suggests reshuffling used tasks when the deck runs low. V reshuffles recursively | bounded scans, automatic replenishment | **Confirmed** by the owner 2026-10-04 (Q3): policy P04 stands |
| C10 | Declaring a single card | R p6 lists highest, only, lowest and requires one to be true; it does not forbid highest or lowest for a single card. R p7's example that a "highest" card may later become the "only" card treats the two as different states, which leans toward "only" for a single card | a single card is accepted only as "only"; two or more cards of a color are never "only" | **Resolved 2026-10-04**: decided by the owner (Q1) and implemented (AVR-248). Before that all three declarations were accepted for a single card |
| C11 | Two players: distress, shared sonar, volunteers | R p21 to p22 treat the dummy as a third crew member and give it no sonar token. The two-player setup does lay out the distress token, so distress is expected to be usable, but how the dummy passes and receives a card is not stated. The shared pool and volunteering are not mentioned. V's two-player snapshot handles none of them | those are refused for two players; mission 8 is offered with the dummy counted | **Decided** by the owner 2026-10-04 (Q6): the dummy is the third crew member for crew-count mechanics. Mission 8 confirmed. Shared sonar gets one token for two players (AVR-250, not yet built). Distress and volunteer missions stay deferred for two players: no mechanism is to be invented |
| C12 | Mission 12 | L M12: no trick may be opened with pink or a submarine. Nothing says whether such a lead is illegal or legal and losing, nor what happens to a leader holding only those | mission disabled | Open (Q15, AVR-244) |
| C13 | When the real-time clock starts | R p20: after the tasks are assigned; no play or communication before it starts | clock starts at the unanimous begin; mission 16 timed is enabled | **Confirmed** by the owner 2026-10-04 (Q2): Begin is the crew starting the timer. The earlier register said timed modes stay blocked; that is superseded |
| C14 | Which unavoidable situations are free | R p13 sidebar: exchange tasks or redeal when a failure could not have been avoided. R p14 names two cases. No full list exists | the two named cases and the captain-comparison case (C20) are handled | Partly applied: no general list exists, each case needs its own evidence |
| C15 | "N tasks" in L | R p8: the number is a total difficulty | treated as difficulty | Applied |
| C16 | Color names | V: red, black, rocket. R: pink, submarine | player-facing names follow R; task ids keep V's words | Applied |
| C17 | Provenance of V and L | V had no recorded upstream; L is a third-party transcription | V is pinned and byte-verified. L unchanged | **V half resolved** 2026-10-03; L half open (AVR-244) |
| C18 | Task faces not independently verified | No readable set of the 96 cards was supplied. R shows examples only | 92 enabled; `4with8` and `6with6` disabled | Open. New evidence: R p17 pictures "win a 5 with a 7", which matches `5with7` as stored; L M32 confirms `exactly3trickInARow` and `2tricksInARow`; R p18 confirms only the lower sum thresholds 8/12/16. **Decided** by the owner 2026-10-04: the reference-derived catalog stays enabled where no higher source contradicts it, with provenance recorded per task (Q4); `5with7` was enabled on 2026-10-04 on the rulebook's text (Q5, AVR-249); `4with8` and `6with6` stay quarantined. Stronger evidence: AVR-244 |
| C19 | Platform lifecycle | The shared session abandons an all-away table, lets "again" skip results, and has no durable store | game-specific overrides; opt-in snapshot file | Applied, with defect E-D2 (AVR-240) |
| C20 | Captain forced onto a captain-comparison task (new 2026-10-03) | R p18: the captain may never choose one. R p9: with as many tasks as seats, nobody may pass. R p13 to p14: unavoidable impossible combinations are repaired by replacing the most recently revealed task; avoidable ones are failed attempts. L and V are silent | an unavoidable draw is repaired before selection by exchanging the most recently revealed comparison task for one of equal difficulty, with no attempt counted; a comparison task the crew leaves for the captain ends the attempt as a counted failure; the captain never passes the task onward | **Resolved 2026-10-04** by owner decision (Q9) and implemented (AVR-239). Before that: selection stalled and only End table remained (defect E-D1) |

Content that is blocked must never be advertised as part of a complete campaign.

## Task catalog

All 96 reference ids, difficulty for 3 / 4 / 5 crew seats, the EXPO evaluator family, status and
evidence. The first four columns are checked against `content/tasks.json` by
`tests/test_expo_docs.py`.

Evidence (owner decision Q4, 2026-10-04) says where the task's wording comes from:

- `corroborated`: the rulebook or the logbook transcription also shows this card's wording. The
  check was made against the PDFs' text layer, not the card pictures, so colors drawn on a card
  are not confirmed by it.
- `reference`: only the pinned reference gives this card's particulars. The rulebook describes
  its family. Enabled because no higher source contradicts it.
- `quarantined`: disabled because of a recorded conflict or missing evidence.

Every difficulty value comes from the reference; the rulebook explains the three-number scheme
and shows no table of values.

<!-- task-catalog:start -->
| Task id | Difficulty 3 / 4 / 5 | Family | Status | Evidence |
|---|---|---|---|---|
| `green6` | 1 / 1 / 1 | `capture` | enabled | reference |
| `yellow1` | 1 / 1 / 1 | `capture` | enabled | reference |
| `red3` | 1 / 1 / 1 | `capture` | enabled | reference |
| `blue4` | 1 / 1 / 1 | `capture` | enabled | reference |
| `black3` | 1 / 1 / 1 | `capture` | enabled | reference |
| `black1` | 3 / 3 / 3 | `count` | enabled | reference |
| `black2` | 3 / 3 / 3 | `count` | enabled | reference |
| `green2lastTrick` | 3 / 4 / 5 | `capture_final` | enabled | reference |
| `2x9` | 2 / 3 / 3 | `count` | enabled | reference |
| `3x6` | 3 / 4 / 4 | `count` | enabled | reference |
| `4x3` | 3 / 4 / 5 | `count` | enabled | reference |
| `4x9` | 4 / 5 / 6 | `count` | enabled | reference |
| `3orMore5` | 3 / 4 / 5 | `count` | enabled | reference |
| `2orMore7` | 2 / 2 / 2 | `count` | enabled | reference |
| `3orMore9` | 3 / 4 / 5 | `count` | enabled | reference |
| `yellow9+blue7` | 2 / 3 / 3 | `capture` | enabled | reference |
| `blue6+yellow7` | 2 / 2 / 3 | `capture` | enabled | reference |
| `red8+blue5` | 2 / 2 / 3 | `capture` | enabled | reference |
| `green5+blue8` | 2 / 2 / 3 | `capture` | enabled | reference |
| `red9+yellow8` | 2 / 2 / 3 | `capture` | enabled | reference |
| `red5+yellow6` | 2 / 2 / 3 | `capture` | enabled | reference |
| `red1+green7` | 2 / 2 / 2 | `capture` | enabled | reference |
| `blue2+blue1+blue3` | 2 / 3 / 3 | `capture` | enabled | reference |
| `yellow4+green3+yellow5` | 3 / 4 / 4 | `capture` | enabled | reference |
| `1red` | 3 / 3 / 4 | `count` | enabled | reference |
| `2blue` | 3 / 4 / 4 | `count` | enabled | reference |
| `2green` | 3 / 4 / 4 | `count` | enabled | reference |
| `1black` | 3 / 3 / 3 | `count` | enabled | reference |
| `2black` | 3 / 3 / 4 | `count` | enabled | reference |
| `3black` | 3 / 4 / 4 | `count` | enabled | reference |
| `5orMoreRed` | 2 / 3 / 3 | `count` | enabled | reference |
| `7orMoreYellow` | 3 / 3 / 3 | `count` | enabled | reference |
| `1red+1green` | 4 / 4 / 4 | `count` | enabled | reference |
| `equalRedYellow` | 4 / 4 / 4 | `equal` | enabled | corroborated (R p18) |
| `moreRedThanGreen` | 1 / 1 / 1 | `greater` | blocked C05 | quarantined |
| `moreYellowThanBlue` | 1 / 1 / 1 | `greater` | blocked C05 | quarantined |
| `eachColor` | 2 / 3 / 4 | `each_color` | enabled | corroborated (R p19) |
| `allOneColor` | 3 / 4 / 5 | `all_color` | enabled | corroborated (R p19) |
| `equalRedBlueInTrick` | 2 / 3 / 3 | `equal_trick` | enabled | corroborated (R p18) |
| `equalGreenYellowInTrick` | 2 / 3 / 3 | `equal_trick` | enabled | reference |
| `red7WithBlack` | 3 / 3 / 3 | `win_with` | enabled | reference |
| `green9WithBlack` | 3 / 3 / 3 | `win_with` | enabled | reference |
| `4with8` | 3 / 4 / 5 | `win_with` | blocked C18 | quarantined |
| `5with7` | 1 / 2 / 2 | `win_with` | enabled | corroborated (R p17) |
| `6with6` | 2 / 3 / 4 | `win_with` | blocked C18 | quarantined |
| `trickWith2` | 3 / 4 / 5 | `win_with` | enabled | corroborated (R p13, p17) |
| `trickWith3` | 3 / 4 / 5 | `win_with` | enabled | reference |
| `trickWith5` | 2 / 3 / 4 | `win_with` | enabled | reference |
| `trickWith6` | 2 / 3 / 3 | `win_with` | enabled | reference |
| `0tricks` | 4 / 3 / 3 | `tricks` | enabled | corroborated (L M32) |
| `exactly1trick` | 3 / 2 / 2 | `tricks` | enabled | reference |
| `exactly2trick` | 2 / 2 / 2 | `tricks` | enabled | reference |
| `exactly4trick` | 2 / 3 / 5 | `tricks` | enabled | reference |
| `exactlyXtrick` | 3 / 2 / 2 | `tricks` | enabled | corroborated (R p18) |
| `exactlyXtrickSecret` | 4 / 3 / 3 | `tricks` | enabled | corroborated (R p18) |
| `exactly2trickInARow` | 3 / 3 / 3 | `exact_streak` | enabled | reference |
| `exactly3trickInARow` | 3 / 3 / 4 | `exact_streak` | enabled | corroborated (L M32) |
| `firstTrick` | 1 / 1 / 1 | `indices` | enabled | corroborated (R p14) |
| `firstTwoTrick` | 1 / 1 / 2 | `indices` | enabled | corroborated (R p10, p14) |
| `firstThreeTrick` | 2 / 3 / 4 | `indices` | enabled | reference |
| `lastTrick` | 2 / 3 / 3 | `indices` | enabled | reference |
| `firstAndLastTrick` | 3 / 4 / 4 | `indices` | enabled | corroborated (L M32) |
| `onlyFirstTrick` | 4 / 3 / 3 | `indices` | enabled | corroborated (R p17) |
| `onlyLastTrick` | 4 / 4 / 4 | `indices` | enabled | reference |
| `2tricksInARow` | 1 / 1 / 1 | `streak` | enabled | corroborated (L M32) |
| `3tricksInARow` | 2 / 3 / 4 | `streak` | enabled | reference |
| `moreThanHalfTricks` | 3 / 4 / 5 | `majority` | enabled | reference |
| `moreTricksThanOthers` | 2 / 3 / 3 | `compare` | enabled | reference |
| `lessTricksThanOthers` | 2 / 2 / 3 | `compare` | enabled | corroborated (R p18) |
| `lessTricksThanCaptain` | 2 / 2 / 2 | `compare` | enabled | reference |
| `equalTricksThanCaptain` | 4 / 3 / 3 | `compare` | enabled | reference |
| `moreTricksThanCaptain` | 2 / 2 / 3 | `compare` | enabled | corroborated (R p18) |
| `onlyOddTrick` | 2 / 4 / 5 | `parity` | enabled | corroborated (R p19) |
| `onlyEvenTrick` | 2 / 5 / 6 | `parity` | enabled | corroborated (R p19) |
| `no1` | 2 / 2 / 2 | `forbidden` | enabled | corroborated (R p10, p17) |
| `no5` | 1 / 2 / 2 | `forbidden` | enabled | reference |
| `no9` | 1 / 1 / 1 | `forbidden` | enabled | reference |
| `no89` | 3 / 3 / 2 | `forbidden` | enabled | reference |
| `no123` | 3 / 3 / 3 | `forbidden` | enabled | reference |
| `noRed` | 2 / 2 / 2 | `forbidden` | enabled | reference |
| `noYellow` | 2 / 2 / 2 | `forbidden` | enabled | reference |
| `noGreen` | 2 / 2 / 2 | `forbidden` | enabled | reference |
| `noRedBlue` | 3 / 3 / 3 | `forbidden` | enabled | reference |
| `noYellowGreen` | 3 / 3 / 3 | `forbidden` | enabled | reference |
| `noBlack` | 1 / 1 / 1 | `forbidden` | enabled | reference |
| `noLeadRedGreen` | 2 / 1 / 1 | `no_lead` | enabled | reference |
| `noLeadRedYellowBlue` | 4 / 3 / 3 | `no_lead` | enabled | reference |
| `noneFirst3Tricks` | 1 / 2 / 2 | `indices` | enabled | reference |
| `noneFirst4Tricks` | 1 / 2 / 3 | `indices` | enabled | reference |
| `noneFirst5Tricks` | 2 / 3 / 3 | `indices` | enabled | reference |
| `neverTwoTricksInARow` | 3 / 2 / 2 | `never_streak` | enabled | reference |
| `allLess7` | 2 / 3 / 3 | `value` | enabled | reference |
| `allGreater5` | 2 / 3 / 4 | `value` | enabled | corroborated (R p18) |
| `value22or23` | 3 / 3 / 4 | `value` | enabled | reference |
| `sumBelow` | 3 / 3 / 4 | `value` | enabled | corroborated (R p18) |
| `sumAbove` | 3 / 3 / 4 | `value` | enabled | reference |
<!-- task-catalog:end -->
