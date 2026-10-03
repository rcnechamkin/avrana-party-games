# EXPO: missions, tasks and modifiers

Status: canonical, reconciled 2026-10-03 (AVR-215). Base rules are in [RULES_SPEC](RULES_SPEC.md)
and are not repeated here. Everything in this document is mission- or task-specific and is layered
on top of the base rules as typed data. Source notation (R, L, V) and conflict numbers (C) are
defined in [VTT_REFERENCE](VTT_REFERENCE.md).

The mission table and the task catalog below are checked against the code by
`tests/test_expo_docs.py`. If a definition changes, this document must change in the same commit.

## How base rules and modifiers are separated

| Layer | Where it lives | May it change card legality? |
|---|---|---|
| Base rules R01 to R10 | `games/expo/rules.py` (deck, follow suit, winner, truthful declarations) and the play and selection flow in `games/expo/engine.py` | this is card legality |
| Task definitions | data in `games/expo/content/tasks.json`, evaluated by `games/expo/tasks.py` | never |
| Mission definitions | `games/expo/content.py` (`mission()`): target, allocation, communication, objective, seconds, volunteers | never (mission 12, the only candidate, is blocked) |

A mission is a small record. The engine reads its fields; no mission has its own code path in the
card rules. Tasks are evaluated from the history of resolved tricks only.

## Mission definition

| Field | Values | Meaning |
|---|---|---|
| `target` | integer | total task difficulty to draw; 0 with no fixed tasks means the mission has an objective instead |
| `fixed` | list of task ids | exact tasks to use instead of drawing (mission 32) |
| `allocation` | `normal`, `one`, `captain_one`, `free`, `skip_captain`, `volunteer` | how tasks reach their owners |
| `communication` | `normal`, `currents`, `rapture`, `terrain`, `none` | sonar rules for the attempt |
| `objective` | none, `balance9`, `balance1`, `first_winner`, `final_yellow5` | a crew-wide condition judged over the whole deal |
| `seconds` | none or integer | real-time limit |
| `volunteers` | 0, 1 | how many seats take all tasks in a volunteer mission |

## Allocation modes

| Mode | Rule | Source |
|---|---|---|
| `normal` | R06: captain first, clockwise, one task per turn | R p9 |
| `one` | the crew decides together on one seat that takes every task | L M6 |
| `captain_one` | the captain takes every task, or offers them all to one willing crew member; if they are passed on, sonar may be used only before the first trick | L M10, M13 |
| `free` | the crew discusses and assigns freely; uneven is allowed; one seat may take all | R p21, L M17, M28 to M31, continuation |
| `skip_captain` | clockwise selection, but the captain is skipped and gets no task; the captain still opens the first trick | L M25 |
| `volunteer` | the captain asks each seat once, clockwise, ending with the captain; only yes or no; the first yes takes every task; if the remaining seats are exactly as many as are still needed, they must take them | R p20 |

In every mode the captain-comparison restriction of R06 applies to whoever would own the task.

Decided 2026-10-04 and not built yet (AVR-251): in `captain_one` the captain's choice to keep the
tasks needs nobody's approval, and an offer needs only the recipient's consent.

POLICY P09: `one`, `captain_one` and `free` assignments take effect when every seated human
confirms the proposal. In `free`, tasks are proposed and confirmed one at a time.

## Communication modes

| Mode | Rule | Source |
|---|---|---|
| `normal` | R05 | R p5 to p7 |
| `currents` | R05, but the declaration (highest, only, lowest) is not revealed to the crew; the card and the spent token are | R p19, L M9 |
| `rapture` | no personal tokens; a shared pool of crew seats minus two; any player may use one, several times if tokens remain; when the pool is empty nobody may communicate | R p19 to p20, L M11 |
| `terrain` | before dealing, draw a color card at random (redraw a submarine): rank 1 to 3 normal, 4 to 6 currents, 7 to 9 rapture; return the drawn cards before dealing; drawn again for every attempt | R p20 |
| `none` | no communication | L M16 untimed |

Extra timing restrictions: mission 23 allows no communication before the second trick (L M23);
`captain_one` after delegation allows it only before the first trick.

## Objectives

| Objective | Condition | Fails when | Source |
|---|---|---|---|
| `balance9` | no seat ever has won two more color 9s than any other seat | after any trick, highest count minus lowest count is 2 or more | L M8 |
| `balance1` | the same for color 1s; submarine 1 is not a color 1 | as above | L M21 (and see C06) |
| `first_winner` | whoever wins the first trick always has strictly more tricks than every other seat | after any trick another seat has as many or more | L M23 |
| `final_yellow5` | yellow 5 is the last card played in the last trick | it is played earlier or in another position, or it is the three-seat unplayed card | L M27 |

Objectives are judged after each resolved trick over all seats, Tonoja included, and need the
whole deal: a mission with an objective cannot succeed before the final trick.

## Real-time missions

R p20: after the tasks are assigned the crew starts a timer; nobody plays or communicates before
it starts; if time runs out before the mission is completed it fails. Playing without the timer is
allowed and then brings a communication restriction or a higher difficulty, as the mission states.
Missions 14, 15, 16 need one volunteer; mission 26 needs two.

CONFIRMED C13 (owner, 2026-10-04): R starts the timer "after assigning the tasks". A digital table also has predictions
and the distress decision before play. POLICY P10 starts the clock when the crew unanimously
begins. Only mission 16 is enabled.

## Mission table

`status` is `enabled` or `blocked Cnn`. Two-player availability is narrower, see below.
Missions 33 to 50 are the continuation (L epilogue): target = mission number minus 15, `free`
allocation, `normal` communication, no objective (POLICY P11 caps it at 50; confirmed 2026-10-04
as an Avrana product limit, not a source rule).

<!-- mission-table:start -->
| Mission | Target | Allocation | Communication | Objective | Status | Source |
|---|---|---|---|---|---|---|
| 1 | 1 | normal | normal | - | enabled | L M1 |
| 2 | 2 | normal | normal | - | enabled | L M2 |
| 3 | 4 | - | - | - | blocked C02 | L M3 says 4, V says 3 |
| 4 | 4 | - | - | - | blocked C03 | L gives no value, V says 4 |
| 5 | 5 | normal | normal | - | enabled | L M5, R p8 example |
| 6 | 5 | one | normal | - | enabled | L M6 |
| 7 | 6 | normal | normal | - | enabled | L M7 |
| 8 | 0 | normal | normal | balance9 | enabled | L M8 |
| 9 | 7 | normal | currents | - | enabled | L M9 |
| 10 | 4 | captain_one | normal | - | enabled | L M10 |
| 11 | 8 | normal | rapture | - | enabled | L M11 |
| 12 | 0 | - | - | - | blocked C12 | L M12 |
| 13 | 5 | captain_one | normal | - | enabled | L M13 |
| 14 | 6 | - | - | - | blocked C03 | L gives no value, V says 6 |
| 15 | 6 | - | - | - | blocked C03 | L gives no value, V says 6 |
| 16 | 6 | volunteer | none | - | enabled | L M16, R p20 |
| 17 | 9 | free | normal | - | enabled | L M17 |
| 18 | 9 | normal | normal | - | enabled | L M18 |
| 19 | 9 | - | - | - | blocked C08 | L M19 |
| 20 | 10 | - | - | - | blocked C06 | L M20 |
| 21 | 0 | normal | terrain | balance1 | enabled | L M21 |
| 22 | 11 | normal | terrain | - | enabled | L M22 |
| 23 | 0 | normal | terrain | first_winner | enabled | L M23 |
| 24 | 12 | normal | terrain | - | enabled | L M24 |
| 25 | 12 | skip_captain | terrain | - | enabled | L M25 |
| 26 | 10 | - | - | - | blocked C07 | L M26 |
| 27 | 0 | normal | terrain | final_yellow5 | enabled | L M27 |
| 28 | 14 | free | normal | - | enabled | L M28 |
| 29 | 15 | free | normal | - | enabled | L M29 |
| 30 | 16 | free | normal | - | enabled | L M30 |
| 31 | 17 | free | normal | - | enabled | L M31 |
| 32 | 0 | normal | normal | - | enabled | L M32, four fixed tasks |
<!-- mission-table:end -->

Notes on the table:

- For blocked missions the target is the value the code holds, which is not authoritative, and
  the other columns are empty: their special rules (12 no pink or submarine lead; 14, 15, 26 real
  time with volunteers; 19 hardest task to the captain; 20 terrain) are **not implemented**. Only
  the refusal with its conflict code is.
- Mission 16: the row is the untimed variant. With the table's `timed` setting on, mission 16 has
  `seconds` 150 and `normal` communication (L M16).
- Mission 32 uses exactly `0tricks`, `exactly3trickInARow`, `2tricksInARow`, `firstAndLastTrick`,
  selected clockwise as usual (L M32).
- The tutorial deal in R p12 (one task of difficulty 1) is not a separate entry; mission 1 has the
  same target and selection.

### Two players

With two humans and Tonoja the following are refused (BLOCKED C11): every `terrain` and `rapture`
mission (11, 21 to 25, 27), the `volunteer` mission (16), and distress in any mission. Missions
1, 2, 5 to 10, 13, 17, 18, 28 to 32 and the continuation are offered. Mission 8 counts Tonoja in
the balance (confirmed, Q6).

Decided 2026-10-04 and not built yet (AVR-250): shared sonar is allowed for two players with one
token, which will open missions 11, 21 to 25 and 27. Distress and the volunteer mission stay
refused for two players.

## Task definition

Each entry of `content/tasks.json`:

| Field | Meaning |
|---|---|
| `id` | the reference's card type id, kept for traceability (uses the reference's color words: `red` is pink, `black` is submarine) |
| `difficulty` | `{"3","4","5"}` by crew seats |
| `family`, `params` | the evaluator and its typed parameters |
| `text`, `text_by_crew` | Avrana's own wording shown to players |
| `enabled`, `blocked` | availability and the conflict that blocks it |
| `source`, `referenceFootnote` | provenance in the reference |

Task status is `pending`, `satisfied` or `failed`, and never goes backwards within an attempt.

## Task families

`n` is the owner's trick count, `end` means all planned tricks are resolved. "Early" means the
task can be satisfied before the end.

| Family | Satisfied | Failed | Early | Source |
|---|---|---|---|---|
| `capture` (cards) | owner has won every listed card, in any tricks | another seat wins a listed card; or not all won at end | yes | R p16 |
| `capture_final` (card) | owner wins the final trick and it contains the card | the card is played in any other trick or won by someone else; unplayed at end | at the final trick | R p16 |
| `count` exact (selector, k) | at end, owner has won exactly k matching cards | more than k; or fewer than k remain winnable; with `required`, that card must be among them and fails if another seat wins it; with `per_suit`, exactly k of each listed suit | no | R p17 |
| `count` at least (selector, k) | owner has won k or more | fewer than k remain winnable | yes | R p17 |
| `forbidden` (selector) | at end, owner has won no matching card | owner wins one | no | R p17 |
| `win_with` (instrument, target) | owner wins a trick with their own card matching the instrument, and (if a target is given) the trick contains a different card matching the target | a named target card is won any other way; no such trick by end | yes | R p17 |
| `indices` (required, forbidden, only) | owner wins every required trick; with `only`, no others; with `forbidden`, none of those | a required trick is won by another seat; a forbidden one is won; with `only`, any other win | required only: yes; a forbidden window: when the window closes | R p17 |
| `tricks` (k or prediction) | at end, n equals k | n exceeds k; or n plus remaining tricks is below k | no | R p17 to p18 |
| `streak` (k) | owner has won k consecutive tricks; more wins are fine | no such run by end | yes | R p17 |
| `exact_streak` (k) | at end, n equals k and they were consecutive | n exceeds k; wins are split; k unreachable | no | L M32, V |
| `never_streak` (k) | at end, owner never won k in a row | owner wins k in a row | no | V |
| `compare` (op, other) | at end, n is strictly less than, strictly more than, or equal to the trick count of every other seat, or of the captain | relation false at end | no | R p18 |
| `majority` | n exceeds half the planned tricks | not reached by end | yes | V |
| `value` (op, threshold or values) | owner wins a trick with no submarine whose ranks sum below, above, or to a listed value, or are all below or all above the threshold | no such trick by end | yes | R p18 |
| `parity` | owner wins a trick with no submarine and only odd, or only even, ranks | none by end | yes | R p19 |
| `equal_trick` (two colors) | owner wins a trick with equally many of both colors, at least one each | none by end | yes | R p18 |
| `equal` (two colors) | at end, owner has won equally many of both colors, at least one each | otherwise | no | R p18 |
| `greater` (two colors) | BLOCKED C05 | | | R p18 |
| `each_color` | owner has won at least one card of each color | not reached by end | yes | R p19 |
| `all_color` | owner has won all nine cards of one color | not reached by end | yes | R p19 |
| `no_lead` (colors) | at end, owner never opened a trick with a listed color | owner opens a trick with one; the play is legal and the task fails | no | R p19 |

Rules that apply to every family:

- Only resolved tricks count, except `no_lead`, which reads the opening card of the trick in
  progress.
- Failure is decided before success on the same event.
- Rank selectors on multi-color tasks match color cards only.
- Sum thresholds depend on crew seats: below 8, 12, 16 (R p18) and above 23, 28, 31 (V only, C18).
- A task whose condition is met and can no longer fail is complete (R p10). The evaluators
  recognise this for the families marked "Early" and for the three window tasks
  (`noneFirst3Tricks`, `noneFirst4Tricks`, `noneFirst5Tricks`), which complete when trick N is
  resolved without a win by their owner. Other reversible tasks (exclusions, exact totals,
  comparisons, "only" tricks) are judged at the end of the deal even where public cards would
  already prove them safe; that is deliberate and deferred, not a defect.

## Deal exceptions

R p14 and p17: for some submarine tasks a particular deal makes the task impossible whoever takes
it. The deal is repeated before the attempt begins and no attempt is recorded.

| Task in the draw | Redeal when one hand holds | Source |
|---|---|---|
| `black1` | submarines 1 and 4, or submarines 1, 2 and 3 | V footnote |
| `black2` | submarines 2 and 4, or submarines 1, 2 and 3 | V footnote |
| `1black` | all four submarines | V footnote |
| `2black` | submarines 2, 3 and 4 | V footnote |
| `3black` | all four submarines | V footnote |
| `red7WithBlack` | all four submarines and pink 7 | R p17 |
| `green9WithBlack` | all four submarines and green 9 | R p17 |

The check looks at every hand, Tonoja's fourteen cards included, because it runs before tasks are
selected.

## Generation, reuse and repair

- Drawing follows R06 exactly.
- POLICY P04 (C09): tasks used by a resolved attempt go to a used pile. Skipped and undrawn tasks
  stay in the deck. If the deck cannot reach the target exactly, the used pile is shuffled back in
  once. If a scan still ends short, the deck is reshuffled and scanned again, at most 200 times;
  no card is lost by a failed scan. A target that cannot be reached at all is a setup error, not a
  mission failure.
- Retry with the same tasks keeps them out of the used pile for that attempt.
- Repair (R08, R p14): in `normal` and `skip_captain` allocation, when there are no more tasks than
  selecting seats (so each seat takes at most one) and two drawn tasks both require the same trick
  (`firstTrick` with `firstTwoTrick`, for example), the later one is replaced by a random task of
  the same difficulty from the deck. With more tasks than seats nothing is replaced.
- Repair for the captain (R08, C20): in `normal` allocation, when the draw has at least as many
  tasks as seats and fewer ordinary tasks than the captain must take (the captain takes every Nth
  task), a captain-comparison task would be forced onto the captain whatever the crew does. The
  most recently revealed comparison task is replaced by a random task of the same difficulty that
  is not a captain comparison, and the replaced task returns to the deck. This can only occur at
  three seats, with three or four tasks that include all three comparison tasks. Both repairs run
  before the deal, so no attempt is counted, and they repeat until neither applies.
- Not a repair: if the draw was fine and the crew leaves a comparison task for the captain's turn,
  the attempt ends as a counted failure (see [ACTIONS](ACTIONS.md#choose_task-task)). A retry with
  the same tasks is offered as after any failure.

## Catalog

96 task definitions, ids and difficulties identical to the reference; 91 enabled, 5 blocked. The
full list with family and status is in
[VTT_REFERENCE](VTT_REFERENCE.md#task-catalog). No complete readable set of the publisher's task
cards was supplied, so the catalog is reference-derived: R corroborates the families and some
individual cards, but not every card face (C18). The owner decided on 2026-10-04 to keep it enabled
where no higher source contradicts it and to record provenance per task: the catalog's Evidence
column marks each task `corroborated`, `reference` or `quarantined`. `5with7` is to be enabled
(AVR-249), which will make 92 enabled.
