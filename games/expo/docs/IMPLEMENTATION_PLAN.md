# EXPO: implementation plan, test matrix and next work

Status: canonical, reconciled 2026-10-03 (AVR-215). The plan was meant to precede the code; the
code came first. This document therefore records the architecture as built, the state of each
planned milestone, the deterministic test matrix with what each row actually has, and the ordered
work that remains. Linear owns scheduling; issue numbers here are pointers, not a queue.

Contracts: [RULES_SPEC](RULES_SPEC.md), [GAME_STATE](GAME_STATE.md), [ACTIONS](ACTIONS.md),
[MISSION_MODEL](MISSION_MODEL.md), [VTT_REFERENCE](VTT_REFERENCE.md). Audit:
[RECONCILIATION](RECONCILIATION.md).

## Architecture as built

EXPO is one LAN Games module: a package under `games/expo/`, one entry in `games/registry.py`, a
vanilla browser client using the shared kit, and tests. It follows `ADDING_A_GAME.md` and
`provider/README.md`.

| Concern | Decision | Reason |
|---|---|---|
| Authority | a synchronous engine with no UI, socket, file or clock dependency; time and randomness are arguments | the rules must be testable without a server, and the client must never be trusted |
| Base rules versus missions | card rules in `rules.py`; missions and tasks are data read by generic code | AVR-215 requires the separation; no mission has its own code path in card legality |
| Reference data | task ids and difficulties copied; semantics decoded by hand into typed parameters; widgets, routines and art discarded | the reference is a manual tabletop, not an engine ([VTT_REFERENCE](VTT_REFERENCE.md#reuse-and-rewrite)) |
| Transactions | every command validates, mutates a copy-on-failure state, checks invariants, and either commits or restores state and random generator | rejected commands must change nothing |
| Privacy | the engine builds each viewer's payload; hidden state is never serialised to a client | hands are secret |
| Lifecycle | the adapter overrides the shared session where a cooperative campaign needs it: seats are held, "again" cannot reset a live table, a mission result is a game phase | the shared defaults would discard a table |
| Persistence | optional single-file snapshot at the adapter boundary | the shared session has no store; the engine stays IO-free |
| Party | `expo` is a first-party id; `core/party_session.GAMES` admits signed rosters and tickets; the outcome is `completed` or `abandoned` | Party ADR 0006, 0010, 0011 |
| Not built | bots, a TV view, presentation events, campaign history | out of scope or deferred (E-X1, E-X6, E-X7) |

Party ADR 0014 retires LAN Games modules as the path for new native games. EXPO exists as a module
today; moving it to an isolated process is platform work with its own issue, and nothing in the
engine depends on the module host.

## Milestones

| # | Milestone (as planned) | State on 2026-10-03 |
|---|---|---|
| 1 | Source reconciliation and content audit | Done for the supplied sources by this reconciliation. Eight missions and five tasks remain blocked on material nobody has supplied (AVR-244). Four policies await confirmation (AVR-243) |
| 2 | Pure engine | Built. One defect affects play (E-D2); E-D1 was fixed on 2026-10-04 (AVR-239) |
| 3 | Task and mission evaluators | Built for 91 tasks and 24 numbered missions plus the continuation. One timing defect (E-D3) |
| 4 | Session adapter and reliability | Built. Persistence shortfalls E-D5 to E-D7 |
| 5 | Phone client | Built and playable; draft presentation specs not implemented (E-X1). No dedicated TV view |
| 6 | Integration | Registered, catalogued, Party contract and grant merged. Not deployed; no appliance key; no real-phone acceptance |

## Verification commands

From the repository root (PowerShell shown; the commands are the same elsewhere):

```
python -m pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py -q
python -m pytest -q
python ops/check_docs.py
python tests/test_no_private_data.py
python ops/export_avrana_catalog.py --check provider/catalog.json
node --check games/expo/web/client.js
```

Browser playtest (needs a running dev server and Chrome; never the live service):

```
$env:LANGAMES_PORT='8196'; python server.py
$env:EXPO_HUMANS='3'; node tests/playtest_expo.mjs http://127.0.0.1:8196
```

## Deterministic test matrix

One row per major rule. Columns answer the six questions AVR-215 asks. "Reconnect / restore" says
whether the rule's state survives a reconnect and a snapshot restore and whether that is tested.
Coverage verdict: **full** (positive, illegal and boundary paths tested), **partial** (named gap),
**missing**. Remaining gaps are collected in AVR-247. Every test name below exists;
`tests/test_expo_docs.py` enforces that.

| ID | Rule | Positive path | Illegal path | Boundaries and player counts | Reconnect / restore | Mission interaction | Coverage |
|---|---|---|---|---|---|---|---|
| T01 | Deal (R01) | `test_deals_conserve_and_captain` | conservation enforced by `Engine.check`; a tampered snapshot is refused in `test_privacy_differential_and_snapshot_json_replay` | 2, 3, 4, 5 players; 12 seeds each; deterministic repeat | hands restored exactly: `test_atomic_store_session_restart_and_fail_closed` | terrain draw precedes the deal: `test_terrain_card_maps_to_the_communication_mode_and_returns_to_the_deck` | full |
| T02 | Captain (R02) | `test_deals_conserve_and_captain` | forged `set_captain`: `test_hostile_payloads_do_not_mutate` | every count; two players always human | captain is state, restored | skip-captain: `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | partial: the three-seat extra card being submarine 4 is not forced in a fixture |
| T03 | Turn order (R02) | `test_captain_opens_the_first_trick_and_each_winner_opens_the_next` | wrong seat: `test_rejected_actions_are_transactional_and_duplicates_idempotent` | 2 to 5 players | mid-trick order is an invariant checked on restore | | full |
| T04 | Follow a color (R03) | `test_immutable_suit_rules_and_trumps` | `test_follow_suit_rejection_and_current_trick_order` | void may discard or trump | | | full |
| T05 | Follow a submarine lead (R03) | `test_immutable_suit_rules_and_trumps` | same | void plays any color | | | full |
| T06 | Winner (R04) | `test_winner_matches_independent_oracle` (3,000 random tricks against an independent oracle) | not applicable | 3, 4, 5 cards; several submarines | recorded winner re-verified on restore | | full |
| T07 | Communication truth (R05) | `test_communication_conditions_resource_and_immutable_meaning` | interior card and submarine refused, same test | single card accepts all three (P03) | | | full for today's policy |
| T08 | Shown card stays owned (R05) | `test_an_exposed_card_stays_in_hand_follows_suit_and_its_token_is_never_restored` | second use refused | meaning not revised when the hand changes | exposure and spent token are state: `test_a_dropped_crew_member_returns_by_fresh_ticket_to_the_same_seat_and_hand` covers hand only | | partial: restore of an active exposure not asserted |
| T09 | Communication timing (R05) | as T07 | mid-trick and before begin: `test_communication_conditions_resource_and_immutable_meaning`, `test_communication_is_refused_before_the_crew_begins_and_for_non_crew` | | | mission 23: `test_modifiers_balance_first_winner_final_card_and_timer` | partial: delegated "before the first trick only" has no direct test |
| T10 | Resources by mode | `test_currents_masks_assertion_and_shared_pool_is_atomic`, `test_sonar_is_available_again_on_the_next_attempt` | empty pool, same test | pool exhaustion | | currents, rapture | partial: two requests for the last token at one revision not tested |
| T11 | Terrain | `test_terrain_card_maps_to_the_communication_mode_and_returns_to_the_deck` | not applicable | all three modes reached; no submarine | `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | missions 21 to 25, 27 | full |
| T12 | Exact task draw (R06) | `test_difficulty_generation_and_no_pass_in_second_circuit` | unreachable target is a setup error (not tested) | 2 to 5 players, eleven missions; replenishment: `test_explicit_feasibility_and_used_deck_replenishment` | deck order is state | continuation 33, 50 | partial: skip order against a fixed permutation; unreachable target |
| T13 | Selection and pass (R06) | `test_pass_capacity_and_captain_comparison` | `test_difficulty_generation_and_no_pass_in_second_circuit` | fewer than, equal to, more than seats | cursor is state: `test_storage_failure_rejects_action_without_losing_table` | | full |
| T14 | Owner eligibility (R06) | `test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain` | normal, one, free, volunteer: also `test_pass_capacity_and_captain_comparison`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | forced case (C20): unavoidable draw repaired, `test_defect_unavoidable_captain_comparison_draw_does_not_stall_selection`, `test_an_unavoidable_comparison_draw_replaces_the_most_recently_revealed_task`, `test_an_avoidable_comparison_draw_is_left_alone`; avoidable mistake is a counted failure, `test_defect_captain_left_with_a_comparison_task_ends_the_attempt_instead_of_stalling`, `test_a_comparison_task_left_for_the_captain_is_a_counted_failure_with_a_reason`; 3, 4, 5 seats and two players | restore refuses an ineligible owner (`Engine.check`) | missions 6, 10, 13, 16, 17 | partial: `captain_one` with an ineligible captain not tested |
| T15 | Named-card tasks (R07) | `test_every_enabled_task_has_deterministic_success_fixture` | `test_a_named_card_captured_by_someone_else_fails_at_once` | cards won in different tricks | tasks and history are state | | full |
| T16 | Exact and at-least counts | `test_exact_atleast_exclusions_and_final_semantics` | exceeding an exact count fails | reaching an exact count stays pending | | | partial: unreachable-count bound not tested per task |
| T17 | Exclusions and "only" tricks | `test_exact_atleast_exclusions_and_final_semantics` | forbidden card, extra trick | window tasks: **defect E-D3**, `test_defect_none_of_the_first_three_tricks_completes_after_trick_three` | | | partial |
| T18 | Runs | `test_exact_streak_fails_once_the_wins_are_split_and_at_least_streak_allows_more` | split wins, too many wins | at-least allows more (R p17) | | mission 32 uses both | full |
| T19 | First, last, final-trick tasks | `test_every_enabled_task_has_deterministic_success_fixture` | `test_exact_atleast_exclusions_and_final_semantics` (card used early) | last = planned trick | | | partial: planned 10 and 8 not exercised for "last" |
| T20 | Trick comparisons | `test_every_enabled_task_has_deterministic_success_fixture` | same (failure fixture) | ties | | | partial: ties and "equal to captain" boundaries |
| T21 | Sums and parity | `test_sum_threshold_boundaries_and_submarine_exclusion` | boundary equals threshold fails; submarine disqualifies | 3, 4, 5 seats | | | full for `sumBelow`, `sumAbove`, parity; `value22or23` has the generic pair only |
| T22 | Win-with | `test_win_with_uses_the_owners_own_winning_card` | wrong instrument, target lost | `6with6` distinct card: blocked | | | full for enabled tasks |
| T23 | Color tasks | `test_every_enabled_task_has_deterministic_success_fixture` | `test_equal_counts_need_at_least_one_of_each_and_never_lead_fails_on_the_lead_itself` | zero each is not equal | | | partial: `each_color`, `all_color` failure only at end |
| T24 | Never-lead tasks | generic fixture | `test_equal_counts_need_at_least_one_of_each_and_never_lead_fails_on_the_lead_itself` | another seat's lead is irrelevant | | | full |
| T25 | Feasibility (R08) | `test_explicit_feasibility_and_used_deck_replenishment`, `test_named_submarine_alignments_are_deal_exceptions`, `test_a_deal_exception_is_redealt_before_the_attempt_is_counted` | no repair when one seat can hold both | every listed alignment and a near miss | | | full for the three recognised cases (fixed-trick pair, submarine alignments, captain comparison: `test_the_comparison_repair_is_deterministic_and_survives_a_snapshot`) |
| T26 | Distress (R09) | `test_distress_sealed_exchange_and_persistence` | submarine refused: `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it`; two players: `test_two_humans_cannot_use_distress_or_shared_sonar_or_volunteer_missions` | left and right; decline on a later attempt | sealed choices are state; not asserted across a restore | surcharge once; cleared by a new mission | partial: restore mid-exchange |
| T27 | Mission outcome (R07) | `test_full_seeded_games_only_use_legal_actions` | failure precedes success | no-task missions need their objective | result is state: `test_closed_snapshot_restores_shared_lobby_reset_and_rejects_corrupt_phase` | | partial: early success with all tasks complete has no direct assertion |
| T28 | Rank balance (missions 8, 21) | `test_rank_balance_allows_a_difference_of_one_and_ignores_submarine_one` | `test_modifiers_balance_first_winner_final_card_and_timer` | difference 1 legal, 2 fails; submarine 1 ignored | | includes the dummy (P23, untested) | partial |
| T29 | Mission 23 | `test_modifiers_balance_first_winner_final_card_and_timer` | tie fails | no sonar before trick 2 | | | partial: strict lead maintained over a full deal not played |
| T30 | Mission 27 | `test_yellow_five_as_the_last_card_of_the_last_trick_succeeds` | early play: `test_modifiers_balance_first_winner_final_card_and_timer`; unplayed: `test_final_yellow5_cannot_succeed_as_surplus_card` | wrong position in the last trick | | | full |
| T31 | Allocation modifiers | `test_single_owner_delegation_free_allocation_and_volunteers`, `test_only_the_captain_may_offer_the_tasks_in_missions_ten_and_thirteen` | non-captain offer refused | uneven free allocation | | missions 6, 10, 13, 17, 25 | partial: mission 19 blocked; mission 6 with the dummy as recipient |
| T32 | Real time | `test_timed_start_barrier_and_volunteer_eligibility_failure` | play at the deadline fails the mission | just before, at, after: `test_modifiers_balance_first_winner_final_card_and_timer` | runs while away: `test_a_timed_mission_expires_while_a_player_is_away`; restore after expiry not tested (E-D7) | mission 16 | partial |
| T33 | Volunteers | `test_single_owner_delegation_free_allocation_and_volunteers` | forced yes | captain last | | ineligible volunteer: `test_timed_start_barrier_and_volunteer_eligibility_failure` | full for one volunteer; two volunteers blocked |
| T34 | Two players (R10) | `test_tonoja_control_visibility_and_delayed_reveal`, `test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them` | non-captain cannot play the dummy | 13 tricks; reveal after the trick | columns are state | refusals: `test_two_humans_cannot_use_distress_or_shared_sonar_or_volunteer_missions` | full |
| T35 | Retry, next, log | `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` | `test_forged_next_mission_is_a_transactional_rejection` | keep and redraw | log is state | | partial: out-of-order next; redraw contents |
| T36 | Privacy | `test_privacy_differential_and_snapshot_json_replay`, `test_prediction_zero_is_locked_and_secret_is_private`, `test_distress_sealed_exchange_and_persistence` | watcher and spectator views: `test_five_human_table_accepts_public_watcher_without_seating`, `test_a_spectator_ticket_watches_the_table_without_a_hand`, `test_nobody_else_sees_or_takes_an_empty_seat` | | | currents: `test_currents_masks_assertion_and_shared_pool_is_atomic` | partial: one phase and one viewer pair for the differential |
| T37 | Hostile input | `test_hostile_payloads_do_not_mutate` | booleans as numbers: `test_blocked_content_and_types` | | | | full |
| T38 | Repeats and staleness | `test_rejected_actions_are_transactional_and_duplicates_idempotent` | reused id with another payload; `test_a_rejected_request_is_not_remembered_and_an_accepted_one_is` | | request memory is state | | partial: two commands at one revision through the lock |
| T39 | Reconnect | `test_session_reconnect_all_away_and_again_cannot_erase`, `test_a_dropped_crew_member_returns_by_fresh_ticket_to_the_same_seat_and_hand` | another credential cannot take the seat: `test_nobody_else_sees_or_takes_an_empty_seat` | all away | same seat, hand, table | ending while away: **defect E-D2**, `test_defect_a_table_can_be_ended_while_a_seated_player_is_away` | partial: allocation phase only |
| T40 | Restart | `test_atomic_store_session_restart_and_fail_closed`, `test_closed_snapshot_restores_shared_lobby_reset_and_rejects_corrupt_phase` | corrupt file, forged phase, other content: `test_a_snapshot_from_other_content_or_rules_is_refused`; write failure: `test_storage_failure_rejects_action_without_losing_table` | | byte-identical replay: `test_privacy_differential_and_snapshot_json_replay` | Party rounds do not persist: `test_a_party_round_never_inherits_or_writes_a_standalone_snapshot` | partial: mid-trick, mid-exchange, timed (E-D5, E-D7) |
| T41 | Platform lifecycle | `test_ending_the_table_is_abandoned`, `test_ending_the_table_after_a_decided_mission_is_completed` | "again" cannot reset: `test_session_reconnect_all_away_and_again_cannot_erase` | | | Party roster: `test_the_roster_seats_the_crew_under_party_names`, `test_expo_is_a_party_session_game`, `test_a_party_round_locks_settings_so_the_table_opens_on_mission_one` | full |
| T42 | Catalog and blocked content | `test_blocked_content_and_types` | blocked missions refuse to start | 96 ids, 91 enabled | | documents equal data: `tests/test_expo_docs.py` | full |
| T43 | Client | `tests/playtest_expo.mjs` (2 to 5 browsers: a live mission, a forged request, masked frames, reload, four widths) | forged request refused | 360, 390, 820, 1440 px | reload mid-table | | partial: runs by hand, not in CI; disabled-control reasons not asserted against server messages |

## What to implement next

In order. Each item has its issue; none is started by this document.

1. **Owner decisions.** AVR-243 was answered on 2026-10-04. Still open: the questions inside
   AVR-240, AVR-245 and AVR-252.
   **Decided behaviour changes from AVR-243**, each small and independent: a single card is
   communicated only as "only" (AVR-248); enable `5with7` (AVR-249); one shared sonar token for
   two players (AVR-250); captain's authority in missions 10 and 13 (AVR-251).
2. ~~Selection stall (AVR-239, E-D1)~~: done 2026-10-04.
3. **Ending a table while a player is away** (AVR-240, E-D2), together with the rule for routine
   progression decisions (AVR-252).
4. **Task completion timing and currents visibility** (AVR-241, E-D3, E-D4). No decision needed.
5. **Test gaps** (AVR-247). Before any content is enabled.
6. **Persistence hardening** (AVR-242, E-D5 to E-D7). Only matters where the snapshot file is used.
7. **Blocked content** (AVR-244). Each mission or task is enabled only with source evidence or an
   owner ruling, a fixture per definition, and an update to the register.
8. **Party-round setup** (AVR-245) and **presentation contract** (AVR-246).

Not on this list and not authorised by it: deployment, appliance keys, real-phone acceptance.

## Rules for changing EXPO from here

- A rule change starts in [RULES_SPEC](RULES_SPEC.md) or [MISSION_MODEL](MISSION_MODEL.md) with its
  source, then the code, then the tests, in one pull request.
- Resolving a conflict edits its row in [VTT_REFERENCE](VTT_REFERENCE.md) with the evidence and
  date. Rows are never deleted.
- Fixing a defect removes its `xfail` marker and updates its row in
  [RECONCILIATION](RECONCILIATION.md).
- Enabling content needs a success and a failure fixture for that definition.
- The mission table and task catalog in these documents are tested against the code; change them
  together.
