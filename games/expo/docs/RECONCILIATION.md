# EXPO: reconciliation of sources, specification, implementation and tests

Status: canonical, reconciled 2026-10-03 (AVR-215). EXPO was implemented and merged before its
specification was reviewed. This document is the audit that followed: for every meaningful rule or
behaviour it compares the canonical source, the specification, the code and the tests, and gives
the result one of six classes. It is the place to look for "is the code right?".

Classes:

| Class | Meaning |
|---|---|
| MATCH | the code does what the canonical source says |
| POLICY | no source decides it; an Avrana digital policy is in force (audited below) |
| DEFECT | the code is wrong against a source or against its own contract; has an issue |
| AMBIGUITY | the sources do not settle it; an owner question is recorded, nothing was guessed |
| STALE | the earlier, uncommitted specification was wrong or out of date; corrected here |
| DEFERRED | specified or desirable, not built; nothing claims it works |

Source notation and conflict numbers: [VTT_REFERENCE](VTT_REFERENCE.md). Tests named here exist in
`tests/test_expo.py`, `tests/test_expo_party.py` and `tests/test_expo_contract.py`;
`tests/test_expo_docs.py` fails if a name stops existing.

## Summary

- The card rules, deal, captain, trick resolution, communication truth and timing, selection and
  pass rule, task evaluators, mission targets and modifiers of the 24 enabled missions match R
  and L.
- Seven defects are recorded (E-D1 to E-D7). Two affect play and need an owner decision on the
  remedy: selection can stall (AVR-239) and a table cannot be ended while someone is away
  (AVR-240).
- Twenty-three digital policies are in force. Four are contested by the conflict register and need
  confirmation (AVR-243).
- Eight missions and five tasks stay blocked on source material (AVR-244).
- The earlier specification was wrong or stale in eleven places (E-S1 to E-S11).

## Rule-by-rule comparison

### Base rules

| Entry | Rule (source) | Implementation | Tests | Class |
|---|---|---|---|---|
| E-M01 | 40 cards; deal 14/13/13, 10, 8; all dealt (R p2, p7) | `rules.DECK`, `Engine._deal` | `test_deals_conserve_and_captain` | MATCH |
| E-M02 | Three-seat extra card is never played; 13 tricks (R p7) | `planned = 40 // seats`; play stops at `planned` | `test_deals_conserve_and_captain`, `test_full_seeded_games_only_use_legal_actions` | MATCH |
| E-M03 | Captain is the holder of submarine 4 (R p9) | `_deal` | `test_deals_conserve_and_captain` | MATCH |
| E-M04 | Captain opens the first trick; each winner opens the next; clockwise, one card each (R p9, p11) | `prepare`, `_play`, `Engine.check` | `test_captain_opens_the_first_trick_and_each_winner_opens_the_next` | MATCH |
| E-M05 | Follow the led suit if held, submarine leads included; void may play anything; no duty to win or trump (R p3 to p5) | `rules.legal_cards`, `_play` | `test_immutable_suit_rules_and_trumps`, `test_follow_suit_rejection_and_current_trick_order` | MATCH |
| E-M06 | Highest submarine wins, else highest of the led suit (R p4) | `rules.winner` | `test_winner_matches_independent_oracle` | MATCH |
| E-M07 | Legal plays that lose are accepted (R p11) | no task filter in `_play`; evaluation after | `test_full_seeded_games_only_use_legal_actions`, `test_a_named_card_captured_by_someone_else_fails_at_once` | MATCH |
| E-M08 | Only the latest won trick may be seen (R p4) | `view` sends `last_trick` only | `test_privacy_differential_and_snapshot_json_replay` | MATCH |
| E-M09 | One token per player per attempt; only before a trick; only after tasks are distributed (R p5) | `communication_options` requires `before_trick` | `test_communication_conditions_resource_and_immutable_meaning`, `test_communication_is_refused_before_the_crew_begins_and_for_non_crew`, `test_sonar_is_available_again_on_the_next_attempt` | MATCH |
| E-M10 | Declaration must be the true highest, only or lowest; no submarines (R p6) | `rules.assertions` | `test_communication_conditions_resource_and_immutable_meaning` | MATCH |
| E-M11 | Shown card stays in hand; declaration never changes; reminder leaves when played; token stays spent (R p6 to p7) | exposure record with `active` | `test_an_exposed_card_stays_in_hand_follows_suit_and_its_token_is_never_restored` | MATCH |
| E-M12 | Draw tasks to the exact total, skipping cards that would exceed it (R p8) | `_generate` | `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH (order of skipping not tested, AVR-247) |
| E-M13 | Captain first, clockwise, one task per turn (R p9) | `allocation_ring`, `selector` | `test_difficulty_generation_and_no_pass_in_second_circuit`, `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M14 | Pass only when fewer tasks than seats at the start, and all tasks placed in one circuit (R p9) | `pass_task` | `test_pass_capacity_and_captain_comparison`, `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH |
| E-M15 | Captain may not take a captain-comparison task (R p18), in every allocation mode | `eligible`, `_assign`, `_proposal` | `test_pass_capacity_and_captain_comparison`, `test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain` | MATCH (but see E-D1) |
| E-M16 | Mission succeeds when all tasks are complete, fails as soon as one cannot be (R p10 to p11) | `_outcome` | `test_full_seeded_games_only_use_legal_actions`, `test_every_enabled_task_has_deterministic_success_fixture` | MATCH, with E-D3 |
| E-M17 | Impossible forced pair is repaired by an equal-difficulty replacement; not when one seat could hold both (R p14) | `_repair_tasks` | `test_explicit_feasibility_and_used_deck_replenishment` | MATCH |
| E-M18 | Named submarine alignments are redealt free (R p14, p17; V footnotes) | `_deal_exception`, `prepare` | `test_named_submarine_alignments_are_deal_exceptions`, `test_a_deal_exception_is_redealt_before_the_attempt_is_counted` | MATCH |
| E-M19 | Retry redeals; tasks kept or redrawn (R p11) | `retry` decision, `prepare(keep)` | `test_explicit_feasibility_and_used_deck_replenishment`, `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` | MATCH |
| E-M20 | Distress: before any communication; everyone passes one non-submarine the same way; stays active; one extra recorded attempt (R p14 to p15) | `distress` decision, `pass_card`, `_finish` log | `test_distress_sealed_exchange_and_persistence`, `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` | MATCH |
| E-M21 | Two players: 13/13 and seven two-card columns; captain is human and controls the dummy; only face-up cards; reveal after the trick (R p21 to p22) | `_deal`, `controller`, `playable`, `_play` | `test_deals_conserve_and_captain`, `test_tonoja_control_visibility_and_delayed_reveal`, `test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them` | MATCH |
| E-M22 | Missions may be played in any order (R p3) | `next` accepts any enabled mission | `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` (next), `test_forged_next_mission_is_a_transactional_rejection` | MATCH (an out-of-order choice is not tested, AVR-247) |

### Missions and modifiers

| Entry | Rule (source) | Implementation | Tests | Class |
|---|---|---|---|---|
| E-M30 | Targets of missions 1, 2, 5 to 11, 13, 16 to 18, 21 to 25, 27 to 31 (L; R p8 for mission 5) | `content.TARGETS` | `test_difficulty_generation_and_no_pass_in_second_circuit`, `tests/test_expo_docs.py` | MATCH |
| E-M31 | Currents: declaration hidden from the crew (R p19, L M9) | `view` strips `assertion` | `test_currents_masks_assertion_and_shared_pool_is_atomic` | MATCH, with E-D4 |
| E-M32 | Rapture: pool of seats minus two; several uses allowed (R p19 to p20, L M11) | `shared`, `communicate` | `test_currents_masks_assertion_and_shared_pool_is_atomic` | MATCH |
| E-M33 | Terrain: color card before the deal, 1-3 / 4-6 / 7-9, submarine redrawn, per attempt (R p20) | `prepare` | `test_terrain_card_maps_to_the_communication_mode_and_returns_to_the_deck`, `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M34 | Mission 6: one seat takes all, chosen together (L M6) | allocation `one` | `test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain` | MATCH |
| E-M35 | Missions 10, 13: captain takes all or passes all to a willing member; then sonar only before the first trick (L) | `captain_one`, `before_first_only` | `test_single_owner_delegation_free_allocation_and_volunteers`, `test_only_the_captain_may_offer_the_tasks_in_missions_ten_and_thirteen` | MATCH |
| E-M36 | Free selection (R p21; L M17, M28 to M31, continuation) | allocation `free` | `test_single_owner_delegation_free_allocation_and_volunteers` | MATCH |
| E-M37 | Mission 25: captain skipped, gets no task (L M25) | `skip_captain` | `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M38 | Mission 16: one volunteer, asked once each clockwise, captain last, forced when the rest are needed; 150 s or no communication (R p20, L M16) | `volunteer`, `content.mission` | `test_single_owner_delegation_free_allocation_and_volunteers`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | MATCH for allocation; clock start is P10 |
| E-M39 | Mission 8 and 21: never two more 9s (1s) than anyone (L M8, M21) | `_outcome` balance | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_rank_balance_allows_a_difference_of_one_and_ignores_submarine_one` | MATCH |
| E-M40 | Mission 23: first-trick winner always strictly ahead; no sonar before trick 2 (L M23) | `_outcome`, `communication_options` | `test_modifiers_balance_first_winner_final_card_and_timer` | MATCH |
| E-M41 | Mission 27: yellow 5 is the last card of the last trick; not the unplayed card (L M27) | `_outcome` | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_final_yellow5_cannot_succeed_as_surplus_card`, `test_yellow_five_as_the_last_card_of_the_last_trick_succeeds` | MATCH |
| E-M42 | Mission 32: four named tasks, selected clockwise (L M32) | `fixed` | `tests/test_expo_docs.py` | MATCH (no play-through test, AVR-247) |
| E-M43 | Continuation from difficulty 18, plus one each time, free selection (L epilogue) | missions 33 to 50 | `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH up to 35; cap is P11 |
| E-M44 | Real-time expiry fails the mission (R p20) | `observe_time` | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | MATCH |

### Tasks

| Entry | Rule (source) | Tests | Class |
|---|---|---|---|
| E-M50 | 96 ids and 288 difficulty values equal the reference (V) | `tests/test_expo_docs.py` pins the documented table to the data; the comparison with V was run by hand on 2026-10-03 | MATCH |
| E-M51 | Named-card, final-trick, exact and at-least counts, exclusions, first/last/only tricks, trick totals, runs, comparisons, sums, parity, equal colors, each color, all of a color, never-lead (R p16 to p19) | `test_every_enabled_task_has_deterministic_success_fixture` (one success and one failure per enabled task), `test_exact_atleast_exclusions_and_final_semantics`, `test_sum_threshold_boundaries_and_submarine_exclusion`, `test_a_named_card_captured_by_someone_else_fails_at_once`, `test_win_with_uses_the_owners_own_winning_card`, `test_exact_streak_fails_once_the_wins_are_split_and_at_least_streak_allows_more`, `test_equal_counts_need_at_least_one_of_each_and_never_lead_fails_on_the_lead_itself` | MATCH for the families R describes |
| E-M52 | Public and secret predictions, fixed before play (R p18) | `test_prediction_zero_is_locked_and_secret_is_private` | MATCH; range and immutability are P05 |
| E-A01 | 91 enabled tasks rest on the reference's decoding, not on verified card faces (C18) | as E-M51 | AMBIGUITY for `sumAbove` (upper thresholds), `black1`, `black2` ("win only"), `exactly2trickInARow`, `majority`, `never_streak` (Q4) |

## Defects

Each has a strict expected-failure test where one can be written. The test asserts the intended
behaviour, fails today, and breaks the suite when the defect is fixed, forcing this entry to be
updated.

| Entry | Defect | Evidence | Test | Issue |
|---|---|---|---|---|
| E-D1 | Selection stalls when the captain is the only seat left for a captain-comparison task. Unavoidable for three seats on mission 11 when the draw is the three comparison tasks (2 + 4 + 2 = 8); avoidable whenever one is left for the captain's later pick. Only End table remains | R p18, p9, p13 to p14 (C20) | `test_defect_unavoidable_captain_comparison_draw_does_not_stall_selection`, `test_defect_captain_left_with_a_comparison_task_ends_the_attempt_instead_of_stalling` | AVR-239 (remedy: Q9) |
| E-D2 | No command is accepted while a seat is away, including the End table decision; a standalone table with a missing player is stranded until restart | state contract; no source | `test_defect_a_table_can_be_ended_while_a_seated_player_is_away` | AVR-240 (policy: Q10) |
| E-D3 | `noneFirst3Tricks`, `noneFirst4Tricks`, `noneFirst5Tricks` stay pending after their window. Success is delayed to the last trick; in timed mission 16 that can become a timeout | R p10: complete when met and unable to fail | `test_defect_none_of_the_first_three_tricks_completes_after_trick_three` | AVR-241 |
| E-D4 | In currents the declaration is withheld from its author too; after a reload they cannot see what they declared | action contract | `test_defect_currents_shows_the_communicator_their_own_assertion` | AVR-241 |
| E-D5 | The content hash covers `tasks.json` only. A changed mission table does not invalidate a snapshot unless it is the mission in flight | state contract | none yet | AVR-242 |
| E-D6 | Only accepted requests are remembered; a rejected request id can be reused with another payload | state contract (asked for both) | `test_a_rejected_request_is_not_remembered_and_an_accepted_one_is` pins today's behaviour | AVR-242 |
| E-D7 | A timed snapshot is restored against the wall clock; a backward clock step grants time. The appliance has no real-time clock | state contract | none yet | AVR-242 |

Not a defect, recorded so nobody "fixes" it by guessing: other reversible tasks could be proven
safe early from public cards (a "win no pink" task after all nine pink cards are gone). The
contract permits sound public bounds and forbids hidden-hand reasoning. Today those tasks wait for
the last trick. DEFERRED, noted in AVR-241.

## Digital policy audit

Every policy the game applies where no source decides. "Contested" means the conflict register or
a source's wording makes the choice non-obvious and the owner has not confirmed it.

| ID | Policy | Why a policy | Tests | Owner status |
|---|---|---|---|---|
| P01 | First card of the deal goes to a randomly drawn seat | R only says deal equally | `test_deals_conserve_and_captain` | uncontested |
| P02 | Hand counts and trick counts per seat are public | observable at a table | `test_privacy_differential_and_snapshot_json_replay` | uncontested |
| P03 | A single card of a color may be declared highest, only or lowest | C10 | `test_communication_conditions_resource_and_immutable_meaning` | **contested, Q1** |
| P04 | Used pile, automatic replenishment when the target is unreachable, at most 200 reshuffled scans | C09; R p8 is a suggestion | `test_explicit_feasibility_and_used_deck_replenishment` | **contested, Q3** |
| P05 | A prediction is an integer 0 to planned tricks and cannot be changed | R p18 says only to note it; V allowed edits | `test_prediction_zero_is_locked_and_secret_is_private`, `test_blocked_content_and_types` | uncontested |
| P06 | An attempt is counted at the crew's begin; setup corrections are free; an avoidable selection failure is counted | R p13 gives the principle, not the bookkeeping | `test_a_deal_exception_is_redealt_before_the_attempt_is_counted`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | uncontested |
| P07 | Distress choices are sealed and exchanged at once | R says pass a card; simultaneity avoids leaking | `test_distress_sealed_exchange_and_persistence` | uncontested |
| P08 | The dummy follows suit from its face-up cards only | R p22 says only face-up cards may be played | `test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them` | uncontested |
| P09 | Begin, distress, collective assignment, retry, next and end need every seated human's confirmation | R says "decide together" | `test_distress_sealed_exchange_and_persistence`, `test_ending_the_table_is_abandoned` | Q8 |
| P10 | The real-time clock starts at the unanimous begin, after predictions and the distress decision | C13 | `test_timed_start_barrier_and_volunteer_eligibility_failure` | **contested, Q2** |
| P11 | The continuation stops at mission 50 (difficulty 35) | L sets no limit | `test_difficulty_generation_and_no_pass_in_second_circuit` | Q7 |
| P12 | A seat is held for the whole table; every command pauses while a seated player is away; no autoplay, no bots | no source | `test_session_reconnect_all_away_and_again_cannot_erase`, `test_a_dropped_crew_member_returns_by_fresh_ticket_to_the_same_seat_and_hand` | Q10 (see E-D2) |
| P13 | A real-time deadline keeps running while a player is away | fairness; no source | `test_a_timed_mission_expires_while_a_player_is_away` | uncontested |
| P14 | An unknown credential during a table watches the public view; watchers are bounded; Party spectators get the public view | platform convention | `test_five_human_table_accepts_public_watcher_without_seating`, `test_nobody_else_sees_or_takes_an_empty_seat`, `test_a_spectator_ticket_watches_the_table_without_a_hand` | uncontested |
| P15 | A volunteer who may not own one of the tasks ends the attempt as a counted failure | R p13: avoidable | `test_timed_start_barrier_and_volunteer_eligibility_failure` | uncontested; compare Q9 |
| P16 | The equal-difficulty replacement is drawn at random from the deck and the replaced task returns to it | R p14 says "a different task" | `test_explicit_feasibility_and_used_deck_replenishment` | uncontested |
| P17 | Deal exceptions are checked against every hand, the dummy's included, before selection | R p14: "no matter who takes the task" | `test_named_submarine_alignments_are_deal_exceptions` | uncontested |
| P18 | Commands carry attempt, revision and a request id; identical repeats are no-ops; stale commands are refused | digital necessity | `test_rejected_actions_are_transactional_and_duplicates_idempotent`, `test_hostile_payloads_do_not_mutate` | uncontested |
| P19 | Durable restoration is opt-in, atomic, and fails closed; Party rounds do not use it | platform has no store | `test_atomic_store_session_restart_and_fail_closed`, `test_storage_failure_rejects_action_without_losing_table`, `test_closed_snapshot_restores_shared_lobby_reset_and_rejects_corrupt_phase`, `test_a_party_round_never_inherits_or_writes_a_standalone_snapshot`, `test_a_snapshot_from_other_content_or_rules_is_refused` | uncontested |
| P20 | A secret prediction is revealed to everyone at the mission result | R is silent | `test_prediction_zero_is_locked_and_secret_is_private` (privacy before the result only) | uncontested |
| P21 | Ending the table is `abandoned` unless a mission result already stood, in which case the outcome reported to Party is `completed` | Party protocol vocabulary | `test_ending_the_table_is_abandoned`, `test_ending_the_table_after_a_decided_mission_is_completed` | uncontested |
| P22 | The dummy's seat is a lobby setting, default after both players | R p22: the players decide where it sits | `test_deals_conserve_and_captain` | uncontested standalone; unavailable in Party (Q11) |
| P23 | Mission 8 is offered to two players and counts the dummy in the balance | C11 | none specific | **contested, Q6** |

## Stale or incorrect earlier specification

The six documents written before implementation were never committed. These are the places where
they were wrong or have been overtaken; the committed documents carry the corrections.

| Entry | Earlier statement | Correction |
|---|---|---|
| E-S1 | Two players are dealt 12 cards each (first draft) | 13 each; the extraction misread the page (C01) |
| E-S2 | No upstream URL or revision exists for the reference | Pinned to upstream commit `03c41d8` and byte-verified (C17) |
| E-S3 | Unknown unavoidable task combinations need a recorded administrative ruling | R p13's sidebar gives the general remedy: exchange task cards or redeal. That is the basis of Q9 |
| E-S4 | The exact-run tasks rest on the reference alone | L M32 states "exactly 3 tricks and they will be in a row" |
| E-S5 | Win-with orientation is entirely unverified | R p17 pictures "a 5 with a 7", matching `5with7`; `4with8` and `6with6` remain unverified |
| E-S6 | Proposed wire verbs (`confirm_table_setup`, `nominate_all_tasks`, `vote_abandon`, `inspect_last_trick`, `acknowledge_result`, ...) and phases (`setup`, `feasibility`, `abandoned`) | Never built. [ACTIONS](ACTIONS.md) and [GAME_STATE](GAME_STATE.md) document the real verbs and phases |
| E-S7 | Snapshot field names (`schemaVersion`, `contentHash`, `taskDeckState`, ...) and a `state.py` module | Never built under those names; real keys are in GAME_STATE |
| E-S8 | "No shared core files change"; slug `crewdeepsea` | `core/party_session.py` lists `expo`; `ops/export_avrana_catalog.py` has `FIRST_PARTY`; the slug and Party id are `expo` |
| E-S9 | Timed modes stay blocked until the clock start is approved (C13) | Mission 16 timed shipped enabled. Recorded as contested policy P10, not as approved |
| E-S10 | "Bounded generation returns a setup error with a replenishment proposal" | Replenishment is automatic (P04) |
| E-S11 | A tutorial mission entry | Not a separate entry; mission 1 is equivalent |

## Deferred and unsupported

| Entry | What | Status |
|---|---|---|
| E-X1 | Presentation and causality events from the two draft presentation specifications (who triggered a failure, "impossible" state, synchronized events, cinematic client). The drafts are not in the repository | DEFERRED, AVR-246 (Q12) |
| E-X2 | Showing cards won toward an unfinished task (R p16, optional) | DEFERRED |
| E-X3 | Missions 3, 4, 12, 14, 15, 19, 20, 26 and their special rules (lead restriction, hardest-to-captain, two volunteers, other timers) | not implemented; blocked on sources, AVR-244 |
| E-X4 | Tasks `moreRedThanGreen`, `moreYellowThanBlue`, `4with8`, `5with7`, `6with6` | definitions stored, disabled |
| E-X5 | Two players with distress, shared sonar or volunteers | refused, C11 |
| E-X6 | A TV presentation, bots, solo play | not planned in this scope |
| E-X7 | Campaign history across tables | Party owns durable history; EXPO keeps none |
| E-P1 | In a Party round the starting mission, timed mode and the dummy's seat cannot be chosen | AVR-245 (Q11); `test_a_party_round_locks_settings_so_the_table_opens_on_mission_one` |

## Owner decisions

Each is a question that the sources do not answer. Nothing below was decided by the implementation
team; where the code already behaves one way, that is stated as "Now".

**Q1 (C10, AVR-243). May a player's only card of a color be declared highest or lowest?**
Evidence: R p6 lists three conditions and requires one to be met; a single card meets all three
literally; nothing forbids the other two. R p23's tip compares declaring an 8 "lowest" against a 9
"highest" for a two-card holding, which does not bear on a single card. V has no validation.
Now: all three accepted. If restricted to "only": the token carries less ambiguity, and the client
must stop offering two options. If kept: a player can deliberately under-inform.

**Q2 (C13, AVR-243). When does the real-time clock start?**
Evidence: R p20: start the timer after assigning the tasks; no play or communication before it
starts. Now: at the unanimous begin, after predictions and the distress decision. Alternatives:
start when the last task is assigned (predictions and the distress exchange then spend clock time,
closer to the letter); or disable timed play until decided (the earlier register's position).

**Q3 (C09, AVR-243). Is automatic task-deck replenishment acceptable?**
Evidence: R p8 suggests keeping used tasks out until the deck runs low. Now: automatic when the
target is unreachable. Alternative: ask the crew. No effect on rules outcomes.

**Q4 (C18, AVR-243). Keep tasks enabled that rest on the reference alone?**
Evidence: R p18 shows the "sum less than" card with 8/12/16 and says totals can be equal to,
greater than or less than a value. The "greater than" values 23/28/31 appear only in V's three
snapshots. `black1`, `black2` use V's "win only" text. Now: enabled. Alternative: quarantine until
a card face is supplied (AVR-244).

**Q5 (C18, AVR-243). Enable `5with7`?**
Evidence: R p17's picture reads "a 5 with a 7"; V's values are 5 then 7; the stored definition is
"win a trick with a 7 that contains a 5". Now: disabled together with `4with8` and `6with6`, which
have no R evidence.

**Q6 (C11, AVR-243). Two players: which shared mechanics include the dummy?**
Evidence: R p22: treat the dummy as a third crew member for tasks; setup gives a sonar token to
each player only; distress and the shared pool are not mentioned for two. Now: distress, shared
sonar, terrain and volunteer missions refused; mission 8 offered with the dummy counted.
Consequences: allowing distress needs a rule for the dummy's passed card (who chooses, from which
cards); a three-seat shared pool has one token.

**Q7 (AVR-243). Continuation cap.** L sets no limit. Now: 50. Raising it only needs the deck to
reach the total, which is checked.

**Q8 (AVR-243). Unanimity.** R says decide together. Now: every seated human must confirm. A
majority rule would let a table move on without a slow player.

**Q9 (C20, AVR-239). The captain is the only seat left for a captain-comparison task.**
Evidence: R p18 forbids the pick; R p9 forbids the pass when tasks are not fewer than seats; R p14
repairs an impossible forced combination by replacing the most recently revealed task with one of
equal difficulty; R p13 calls an avoidable failure a failed attempt. Now: no legal action; only
End table. Proposed: replace before selection in the unavoidable case (no attempt counted); count
a failed attempt in the avoidable case. Alternative for the avoidable case: let the captain pass
and offer the task onward, which no source supports.

**Q10 (AVR-240). Who may end a table while a player is away, and when?**
No source. Now: nobody. Options: the present players at once; the present players after a grace
period; an automatic timeout. BLUFF uses 60 seconds and 5 minutes. The result must be `abandoned`.

**Q11 (AVR-245). Should a Party-launched crew choose its starting mission, timed mode and the
dummy's seat?** Now: fixed at mission 1, untimed, dummy after both players. R p22 makes the
dummy's seat a player choice.

**Q12 (AVR-246). Presentation drafts.** Commit them as non-canonical drafts or keep them out; and
whether a causality record is wanted in results.

**Q13 (C05, AVR-244). "More of one color than another".** R p18's sentence says the cards are "in
your hand" at the end; the card pictures on the same page say "I will win more ... than ..."; R p16
says tasks are completed by winning tricks; V counts won cards. Hands are empty at the end except
the three-seat extra card, so the literal sentence makes the task nearly meaningless. Now: both
tasks disabled.

**Q14 (C08, AVR-244). Mission 19 ties.** L: the most difficult task goes to the captain. V: the
leftmost of the hardest. Unsettled: when several tie, does the captain choose among them, or is
reveal order decisive? Now: mission disabled.

**Q15 (C12, AVR-244). Mission 12.** L: no trick may be opened with pink or a submarine. Unsettled:
is such a lead illegal (the engine would have to refuse it, and needs a rule for a leader holding
only those suits) or legal and mission-losing? R p19's never-lead tasks are the second kind. Now:
mission disabled.

## Implementation report

What was run for this reconciliation, on Windows at the head of the branch that added these
documents. No engine, content or client file changed in that branch.

<!-- report:start -->
Sources read in full: the rulebook (24 pages) and the logbook transcription (18 pages), by text
extraction. The reference's four snapshots were compared with upstream by git blob id and their
task and mission data were compared with `content/tasks.json` and `content.py` by script.

| Check | Result |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 198 passed, 5 expected failures (the pinned defects E-D1 twice, E-D2, E-D3, E-D4) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,576 passed, 1 skipped, 5 expected failures, 0 failed |
| `ops/check_docs.py` | Documentation integrity: OK |
| `tests/test_no_private_data.py` | clean |
| `ops/export_avrana_catalog.py --check provider/catalog.json` | consistent |
| `ops/check_static.sh` (shell and JavaScript syntax, generated art) | passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2 and 4 humans | passed (live mission, forged request, masked frames, reload, four widths) |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Probes run by hand and then turned into tests: every item in the defect table, the deal
exceptions, terrain mapping, mission 27's success path, distress bookkeeping, two-player refusals,
Party-round settings.

Not verified by anyone: play on real phones, the appliance, a Party-launched round end to end
(covered only by the binding-level tests in `tests/test_expo_party.py`), and the publisher's own
logbook or task cards.

Remaining ambiguities: conflicts C02, C03, C05 to C13, C18 and C20 in
[VTT_REFERENCE](VTT_REFERENCE.md#conflict-register), and owner questions Q1 to Q15 above.
<!-- report:end -->
