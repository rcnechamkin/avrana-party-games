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
`tests/test_expo.py`, `tests/test_expo_party.py`, `tests/test_expo_contract.py`,
`tests/test_expo_coverage.py` and `tests/test_expo_persistence.py`;
`tests/test_expo_docs.py` fails if a name stops existing.

## Summary

- The card rules, deal, captain, trick resolution, communication truth and timing, selection and
  pass rule, task evaluators, mission targets and modifiers of the 24 enabled missions match R
  and L.
- Nine defects were recorded (E-D1 to E-D7 by the reconciliation, E-D8 by AVR-247, E-D9 by probing during its review). Six are fixed: E-D9, the table freeze from one malformed crew decision (AVR-264), E-D1, the selection stall
  (AVR-239), E-D3 and E-D4, late completion of the window tasks and currents visibility
  (AVR-241), and E-D5 and E-D7, the content hash scope and the timed clock (AVR-242). E-D6 was
  settled by amending the contract (AVR-242). Of the two that remain, one affects play and needs
  an owner decision on the remedy: a table cannot be ended while someone is away (AVR-240).
- Twenty-three digital policies are in force. The owner decided the open ones on 2026-10-04
  (AVR-243, questions Q1 to Q8 below). Four decisions change behaviour. All four are implemented:
  single-card communication (AVR-248), the task `5with7` (AVR-249), one shared sonar token for
  two players (AVR-250) and the captain's authority in missions 10 and 13 (AVR-251). One more
  needs a further decision: AVR-252.
- Eight missions and four tasks stay blocked on source material (AVR-244).
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
| E-M10 | Declaration must be the true highest, only or lowest; no submarines (R p6). A single card is "only" (C10) | `rules.assertions` | `test_communication_conditions_resource_and_immutable_meaning`, `test_every_offered_declaration_is_true_and_single_cards_are_always_only` | MATCH |
| E-M11 | Shown card stays in hand; declaration never changes; reminder leaves when played; token stays spent (R p6 to p7) | exposure record with `active` | `test_an_exposed_card_stays_in_hand_follows_suit_and_its_token_is_never_restored` | MATCH |
| E-M12 | Draw tasks to the exact total, skipping cards that would exceed it (R p8) | `_generate` | `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH; skip order: `test_task_drawing_skips_a_card_that_would_exceed_the_total_and_keeps_scanning` |
| E-M13 | Captain first, clockwise, one task per turn (R p9) | `allocation_ring`, `selector` | `test_difficulty_generation_and_no_pass_in_second_circuit`, `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M14 | Pass only when fewer tasks than seats at the start, and all tasks placed in one circuit (R p9) | `pass_task` | `test_pass_capacity_and_captain_comparison`, `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH |
| E-M15 | Captain may not take a captain-comparison task (R p18), in every allocation mode | `eligible`, `_assign`, `_proposal` | `test_pass_capacity_and_captain_comparison`, `test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain` | MATCH |
| E-M16 | Mission succeeds when all tasks are complete, fails as soon as one cannot be (R p10 to p11) | `_outcome` | `test_full_seeded_games_only_use_legal_actions`, `test_every_enabled_task_has_deterministic_success_fixture` | MATCH. Early success when the last open task completes: `test_closing_the_window_on_the_last_open_task_wins_the_mission_at_once` |
| E-M17 | Impossible forced pair is repaired by an equal-difficulty replacement; not when one seat could hold both (R p14) | `_repair_tasks` | `test_explicit_feasibility_and_used_deck_replenishment` | MATCH |
| E-M18 | Named submarine alignments are redealt free (R p14, p17; V footnotes) | `_deal_exception`, `prepare` | `test_named_submarine_alignments_are_deal_exceptions`, `test_a_deal_exception_is_redealt_before_the_attempt_is_counted` | MATCH |
| E-M19 | Retry redeals; tasks kept or redrawn (R p11) | `retry` decision, `prepare(keep)` | `test_explicit_feasibility_and_used_deck_replenishment`, `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` | MATCH |
| E-M20 | Distress: before any communication; everyone passes one non-submarine the same way; stays active; one extra recorded attempt (R p14 to p15) | `distress` decision, `pass_card`, `_finish` log | `test_distress_sealed_exchange_and_persistence`, `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` | MATCH |
| E-M21 | Two players: 13/13 and seven two-card columns; captain is human and controls the dummy; only face-up cards; reveal after the trick (R p21 to p22) | `_deal`, `controller`, `playable`, `_play` | `test_deals_conserve_and_captain`, `test_tonoja_control_visibility_and_delayed_reveal`, `test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them` | MATCH |
| E-M22 | Missions may be played in any order (R p3) | `next` accepts any enabled mission | `test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it` (next), `test_forged_next_mission_is_a_transactional_rejection` | MATCH; out of order: `test_the_next_mission_may_be_any_enabled_mission_in_any_order` |

### Missions and modifiers

| Entry | Rule (source) | Implementation | Tests | Class |
|---|---|---|---|---|
| E-M30 | Targets of missions 1, 2, 5 to 11, 13, 16 to 18, 21 to 25, 27 to 31 (L; R p8 for mission 5) | `content.TARGETS` | `test_difficulty_generation_and_no_pass_in_second_circuit`, `tests/test_expo_docs.py` | MATCH |
| E-M31 | Currents: declaration hidden from the crew (R p19, L M9) | `view` strips `assertion` | `test_currents_masks_assertion_and_shared_pool_is_atomic`, `test_currents_hides_a_declaration_from_every_viewer_but_its_author` | MATCH |
| E-M32 | Rapture: pool of seats minus two; several uses allowed (R p19 to p20, L M11) | `shared`, `communicate` | `test_currents_masks_assertion_and_shared_pool_is_atomic`, `test_the_shared_pool_for_three_to_five_players_is_unchanged`; two humans and the dummy, one token: `test_either_human_may_spend_the_shared_token_and_then_nobody_can_communicate` | MATCH |
| E-M33 | Terrain: color card before the deal, 1-3 / 4-6 / 7-9, submarine redrawn, per attempt (R p20) | `prepare` | `test_terrain_card_maps_to_the_communication_mode_and_returns_to_the_deck`, `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M34 | Mission 6: one seat takes all, chosen together (L M6) | allocation `one` | `test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain` | MATCH |
| E-M35 | Missions 10, 13: captain takes all or passes all to a willing member; then sonar only before the first trick (L) | `captain_one`, `before_first_only` | `test_single_owner_delegation_free_allocation_and_volunteers`, `test_only_the_captain_may_offer_the_tasks_in_missions_ten_and_thirteen` | MATCH |
| E-M36 | Free selection (R p21; L M17, M28 to M31, continuation) | allocation `free` | `test_single_owner_delegation_free_allocation_and_volunteers` | MATCH |
| E-M37 | Mission 25: captain skipped, gets no task (L M25) | `skip_captain` | `test_skip_captain_and_terrain_draws_are_frozen_on_restore` | MATCH |
| E-M38 | Mission 16: one volunteer, asked once each clockwise, captain last, forced when the rest are needed; 150 s or no communication (R p20, L M16) | `volunteer`, `content.mission` | `test_single_owner_delegation_free_allocation_and_volunteers`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | MATCH for allocation; clock start is P10 |
| E-M39 | Mission 8 and 21: never two more 9s (1s) than anyone (L M8, M21) | `_outcome` balance | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_rank_balance_allows_a_difference_of_one_and_ignores_submarine_one` | MATCH |
| E-M40 | Mission 23: first-trick winner always strictly ahead; no sonar before trick 2 (L M23) | `_outcome`, `communication_options` | `test_modifiers_balance_first_winner_final_card_and_timer` | MATCH |
| E-M41 | Mission 27: yellow 5 is the last card of the last trick; not the unplayed card (L M27) | `_outcome` | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_final_yellow5_cannot_succeed_as_surplus_card`, `test_yellow_five_as_the_last_card_of_the_last_trick_succeeds` | MATCH |
| E-M42 | Mission 32: four named tasks, selected clockwise (L M32) | `fixed` | `tests/test_expo_docs.py`, `test_mission_thirty_two_deals_its_four_named_tasks_and_plays_to_a_result` | MATCH |
| E-M43 | Continuation from difficulty 18, plus one each time, free selection (L epilogue) | missions 33 to 50 | `test_difficulty_generation_and_no_pass_in_second_circuit` | MATCH up to 35; cap is P11 |
| E-M44 | Real-time expiry fails the mission (R p20) | `observe_time` | `test_modifiers_balance_first_winner_final_card_and_timer`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | MATCH |

### Tasks

| Entry | Rule (source) | Tests | Class |
|---|---|---|---|
| E-M50 | 96 ids and 288 difficulty values equal the reference (V) | `tests/test_expo_docs.py` pins the documented table to the data; the comparison with V was run by hand on 2026-10-03 | MATCH |
| E-M51 | Named-card, final-trick, exact and at-least counts, exclusions, first/last/only tricks, trick totals, runs, comparisons, sums, parity, equal colors, each color, all of a color, never-lead (R p16 to p19) | `test_every_enabled_task_has_deterministic_success_fixture` (one success and one failure per enabled task), `test_exact_atleast_exclusions_and_final_semantics`, `test_sum_threshold_boundaries_and_submarine_exclusion`, `test_a_named_card_captured_by_someone_else_fails_at_once`, `test_win_with_uses_the_owners_own_winning_card`, `test_exact_streak_fails_once_the_wins_are_split_and_at_least_streak_allows_more`, `test_equal_counts_need_at_least_one_of_each_and_never_lead_fails_on_the_lead_itself` | MATCH for the families R describes |
| E-M52 | Public and secret predictions, fixed before play (R p18) | `test_prediction_zero_is_locked_and_secret_is_private` | MATCH; range and immutability are P05 |
| E-A01 | 92 enabled tasks rest on the reference's decoding, not on verified card faces (C18) | as E-M51 | AMBIGUITY for `sumAbove` (upper thresholds), `black1`, `black2` ("win only"), `exactly2trickInARow`, `majority`, `never_streak` (Q4) |

## Defects

Each has a strict expected-failure test where one can be written. The test asserts the intended
behaviour, fails today, and breaks the suite when the defect is fixed, forcing this entry to be
updated.

| Entry | Defect | Evidence | Test | Issue |
|---|---|---|---|---|
| E-D1 | **Fixed 2026-10-04.** Was: selection stalled when the captain was the only seat left for a captain-comparison task, and only End table remained. Now: a draw that forces one onto the captain is repaired before selection opens (the most recently revealed comparison task is exchanged for another of equal difficulty, no attempt counted); a comparison task that the crew leaves for the captain ends the attempt as a counted failure with a stated reason | R p18, p9, p13 to p14 (C20); owner decision Q9 | `test_defect_unavoidable_captain_comparison_draw_does_not_stall_selection`, `test_defect_captain_left_with_a_comparison_task_ends_the_attempt_instead_of_stalling`, `test_an_unavoidable_comparison_draw_replaces_the_most_recently_revealed_task`, `test_a_comparison_task_left_for_the_captain_is_a_counted_failure_with_a_reason`, `test_an_avoidable_comparison_draw_is_left_alone`, `test_the_comparison_repair_applies_only_to_clockwise_selection_that_includes_the_captain`, `test_the_comparison_repair_is_deterministic_and_survives_a_snapshot`, `test_the_crew_can_retry_after_the_counted_failure_and_assign_the_task_correctly`, `test_selection_never_fails_while_the_next_seat_can_take_or_pass` | AVR-239 |
| E-D2 | No command is accepted while a seat is away, including the End table decision; a standalone table with a missing player is stranded until restart | state contract; no source | `test_defect_a_table_can_be_ended_while_a_seated_player_is_away` | AVR-240 (policy: Q10) |
| E-D3 | **Fixed 2026-10-04.** Was: `noneFirst3Tricks`, `noneFirst4Tricks`, `noneFirst5Tricks` stayed pending after their window, so success waited for the last trick and in timed mission 16 could become a timeout. Now: each is satisfied when trick N resolves without a win by its owner, and the mission succeeds at once if it was the last open task. No other task family completes earlier than before | R p10: complete when met and unable to fail | `test_defect_none_of_the_first_three_tricks_completes_after_trick_three`, `test_a_window_task_is_pending_inside_its_window_and_satisfied_when_it_closes`, `test_only_the_three_window_tasks_complete_early_for_a_seat_that_wins_nothing`, `test_closing_the_window_on_the_last_open_task_wins_the_mission_at_once`, `test_a_window_task_does_not_finish_the_mission_while_another_task_is_open`, `test_a_timed_mission_completed_by_a_window_task_cannot_time_out_afterwards`, `test_a_timed_mission_still_times_out_while_the_window_is_open` | AVR-241 |
| E-D4 | **Fixed 2026-10-04.** Was: in currents the declaration was withheld from its author too. Now: the author's own view carries it, including after a reload or restore; every other player, watcher and Party spectator still does not receive it | action contract; R p19 (the crew must deduce it, the author knows it) | `test_defect_currents_shows_the_communicator_their_own_assertion`, `test_currents_hides_a_declaration_from_every_viewer_but_its_author`, `test_normal_communication_still_shows_the_declaration_to_everyone`, `test_a_watcher_and_another_player_never_get_a_currents_declaration_through_the_session` | AVR-241 |
| E-D5 | **Fixed 2026-10-04.** Was: the content hash covered `tasks.json` only, so a changed mission table did not invalidate a snapshot unless it was the mission in flight. Now: the hash covers the task catalog and every mission definition, untimed and timed, a blocked mission by its reason. The hash value changed once with this fix, so a snapshot written before it is refused with the usual recovery message | state contract | `test_the_content_hash_is_the_hash_of_the_tasks_and_of_every_mission_definition`, `test_any_change_to_the_content_changes_the_hash`, `test_a_changed_modifier_timer_or_fixed_task_list_changes_the_hash`, `test_a_snapshot_taken_before_a_mission_table_change_is_refused_after_it`, `test_an_unchanged_mission_table_still_restores` | AVR-242 |
| E-D6 | **Settled 2026-10-04 by amending the contract; no code change.** Only accepted requests are remembered, and a rejected request id used again is a new request. The earlier draft asked for both to be kept. Keeping rejections adds nothing to idempotency (every state change raises the revision), would forbid resending a request refused only because the disk failed, and would let one seated player fill the capped request memory alone and lock the table. Reasons in [GAME_STATE](GAME_STATE.md#commands-ordering-and-repeats) | state contract (amended) | `test_a_rejected_request_is_not_remembered_and_an_accepted_one_is`, `test_a_flood_of_rejected_requests_is_not_remembered_and_cannot_use_up_the_request_limit`, `test_the_same_rejected_request_sent_again_gets_the_same_answer`, `test_a_rejected_request_id_used_again_is_a_new_request_and_is_remembered_once_accepted`, `test_a_request_refused_only_because_the_disk_failed_succeeds_when_sent_again_unchanged` | AVR-242 |
| E-D7 | **Fixed 2026-10-04.** Was: the deadline was a wall-clock moment, so a backward clock step granted time, on restore and (found while fixing it) on a live table with no restart at all. Now: the deadline runs on the monotonic clock; a restored timed attempt continues only on the same boot (by the kernel's boot identity) with both clocks agreeing about how long the server was down, and otherwise ends as a counted failure with its own reason, written to the snapshot. A reboot therefore always ends a running timed attempt | state contract; the appliance has no real-time clock | `test_a_timed_mission_runs_on_the_monotonic_clock_and_browsers_get_a_wall_clock_moment`, `test_a_wall_clock_step_during_a_live_timed_mission_neither_grants_nor_takes_time`, `test_a_restart_on_the_same_boot_continues_the_deadline_and_charges_the_downtime`, `test_a_timed_table_restored_after_its_deadline_has_already_failed`, `test_a_timed_table_restored_under_a_clock_that_cannot_be_trusted_ends_and_never_gains_time`, `test_a_timed_snapshot_without_a_clock_record_ends_the_attempt`, `test_a_host_that_never_could_name_its_boot_ends_the_attempt_on_every_restart`, `test_a_saved_deadline_later_than_a_full_timer_is_not_resumed`, `test_an_end_that_could_not_be_written_is_judged_again_and_a_reboot_still_ends_it`, `test_a_snapshot_with_a_deadline_beside_a_result_is_refused_not_raised`, `test_clocks_that_agree_within_two_seconds_on_the_same_boot_are_trusted`, `test_a_failed_write_after_a_wall_clock_step_leaves_the_shared_timer_on_the_true_deadline`, `test_a_table_with_no_running_deadline_restores_whatever_the_clocks_say`, `test_on_the_real_clocks_the_shared_timer_and_the_browsers_get_the_same_150_seconds`, `test_the_engine_expires_only_a_running_deadline` | AVR-242 |
| E-D8 | The reason shown on an unavailable control is not the server's rejection in six places. Two state something untrue: a color card in the distress exchange after the player's own choice is sealed reads "Submarines cannot be passed", and a card that follows suit reads "You must follow the opening suit." while a crew decision is pending (the captain's off-suit Tonoja card reads "Only the captain plays for Tonoja."). Four are a second wording of the same fact: a card before the crew begins, "Take this task" for another seat and for the captain on a comparison task, "Offer all tasks" for a non-captain. The server refuses every one of these requests and nothing changes | action contract ("the client can disable it with the right reason") | `test_defect_the_reason_shown_before_play_begins_is_the_servers_rejection`; the playtest asserts the refusals | AVR-263 |
| E-D9 | **Fixed 2026-10-04.** Was: a crew decision was checked for its keys but not for the type of every value. In missions 6, 10 and 13 the `task` of an `assign` decision was never read, so any JSON value was stored in the pending decision and sent to every viewer; a value nested about 500 lists deep (one socket message) then made every view, snapshot and command raise, and one seated player could freeze the table. Now: every field of a crew decision must be a plain value of its own type and, where all tasks go together, `task` must be `all`; anything else is rejected before it is stored or remembered | action contract (a rejected request changes nothing) | `test_an_assign_field_of_the_wrong_type_is_refused_in_every_allocation_mode`, `test_every_other_decision_field_of_the_wrong_type_is_refused`, `test_where_all_tasks_go_together_the_task_field_is_the_word_all`, `test_the_request_that_froze_the_table_is_refused_and_the_table_plays_on` | AVR-264 |

Not a defect, recorded so nobody "fixes" it by guessing: other reversible tasks could be proven
safe early from public cards (a "win no pink" task after all nine pink cards are gone). The
contract permits sound public bounds and forbids hidden-hand reasoning. Today those tasks wait for
the last trick. DEFERRED. AVR-241 deliberately did not generalise early completion beyond the
three window tasks, and a test pins that.

## Digital policy audit

Every policy the game applies where no source decides. "Contested" means the conflict register or
a source's wording makes the choice non-obvious and the owner has not confirmed it.

| ID | Policy | Why a policy | Tests | Owner status |
|---|---|---|---|---|
| P01 | First card of the deal goes to a randomly drawn seat | R only says deal equally | `test_deals_conserve_and_captain` | uncontested |
| P02 | Hand counts and trick counts per seat are public | observable at a table | `test_privacy_differential_and_snapshot_json_replay` | uncontested |
| P03 | A single card of a color may be declared only "only"; "highest" and "lowest" need a second card of that color, and such a holding can never be declared "only". Replaced the earlier policy (all three accepted) on 2026-10-04 | C10 | `test_communication_conditions_resource_and_immutable_meaning`, `test_the_rule_gives_a_single_card_only_and_never_gives_only_to_a_longer_holding`, `test_the_engine_refuses_highest_and_lowest_for_a_single_card_in_every_mode`, `test_two_cards_of_a_color_keep_highest_and_lowest_and_cannot_be_called_only`, `test_an_earlier_highest_declaration_stays_when_the_card_becomes_the_only_one` | decided by the owner 2026-10-04 (Q1); implemented (AVR-248) |
| P04 | Used pile, automatic replenishment when the target is unreachable, at most 200 reshuffled scans | C09; R p8 is a suggestion | `test_explicit_feasibility_and_used_deck_replenishment` | confirmed 2026-10-04 (Q3) |
| P05 | A prediction is an integer 0 to planned tricks and cannot be changed | R p18 says only to note it; V allowed edits | `test_prediction_zero_is_locked_and_secret_is_private`, `test_blocked_content_and_types` | uncontested |
| P06 | An attempt is counted at the crew's begin; setup corrections are free; an avoidable selection failure is counted | R p13 gives the principle, not the bookkeeping | `test_a_deal_exception_is_redealt_before_the_attempt_is_counted`, `test_timed_start_barrier_and_volunteer_eligibility_failure` | uncontested |
| P07 | Distress choices are sealed and exchanged at once | R says pass a card; simultaneity avoids leaking | `test_distress_sealed_exchange_and_persistence` | uncontested |
| P08 | The dummy follows suit from its face-up cards only | R p22 says only face-up cards may be played | `test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them` | uncontested |
| P09 | Begin, distress, collective assignment, retry, next and end need every seated human's confirmation | R says "decide together" | `test_distress_sealed_exchange_and_persistence`, `test_ending_the_table_is_abandoned`, `test_every_other_crew_decision_still_needs_every_seated_human` | decided 2026-10-04 (Q8): unanimity stays for strategic decisions; missions 10 and 13 follow the source instead (AVR-251, built 2026-10-04); routine progression should become less fragile (AVR-252) |
| P10 | The real-time clock starts at the unanimous begin, after predictions and the distress decision | C13 | `test_timed_start_barrier_and_volunteer_eligibility_failure` | confirmed 2026-10-04 (Q2): Begin is the crew starting the timer |
| P11 | The continuation stops at mission 50 (difficulty 35) | L sets no limit | `test_difficulty_generation_and_no_pass_in_second_circuit` | confirmed 2026-10-04 (Q7) as an Avrana product limit, not a source rule |
| P12 | A seat is held for the whole table; every command pauses while a seated player is away; no autoplay, no bots | no source | `test_session_reconnect_all_away_and_again_cannot_erase`, `test_a_dropped_crew_member_returns_by_fresh_ticket_to_the_same_seat_and_hand` | Q10 (see E-D2) |
| P13 | A real-time deadline keeps running while a player is away | fairness; no source | `test_a_timed_mission_expires_while_a_player_is_away` | uncontested |
| P14 | An unknown credential during a table watches the public view; watchers are bounded; Party spectators get the public view | platform convention | `test_five_human_table_accepts_public_watcher_without_seating`, `test_nobody_else_sees_or_takes_an_empty_seat`, `test_a_spectator_ticket_watches_the_table_without_a_hand` | uncontested |
| P15 | A volunteer who may not own one of the tasks ends the attempt as a counted failure | R p13: avoidable | `test_timed_start_barrier_and_volunteer_eligibility_failure` | uncontested; the same rule now covers the captain (Q9) |
| P16 | The equal-difficulty replacement is drawn at random from the deck and the replaced task returns to it | R p14 says "a different task" | `test_explicit_feasibility_and_used_deck_replenishment` | uncontested |
| P17 | Deal exceptions are checked against every hand, the dummy's included, before selection | R p14: "no matter who takes the task" | `test_named_submarine_alignments_are_deal_exceptions` | uncontested |
| P18 | Commands carry attempt, revision and a request id; identical repeats are no-ops; stale commands are refused | digital necessity | `test_rejected_actions_are_transactional_and_duplicates_idempotent`, `test_hostile_payloads_do_not_mutate` | uncontested |
| P19 | Durable restoration is opt-in, atomic, and fails closed; Party rounds do not use it | platform has no store | `test_atomic_store_session_restart_and_fail_closed`, `test_storage_failure_rejects_action_without_losing_table`, `test_closed_snapshot_restores_shared_lobby_reset_and_rejects_corrupt_phase`, `test_a_party_round_never_inherits_or_writes_a_standalone_snapshot`, `test_a_snapshot_from_other_content_or_rules_is_refused` | uncontested |
| P20 | A secret prediction is revealed to everyone at the mission result | R is silent | `test_prediction_zero_is_locked_and_secret_is_private` (privacy before the result only) | uncontested |
| P21 | Ending the table is `abandoned` unless a mission result already stood, in which case the outcome reported to Party is `completed` | Party protocol vocabulary | `test_ending_the_table_is_abandoned`, `test_ending_the_table_after_a_decided_mission_is_completed` | uncontested |
| P22 | The dummy's seat is a lobby setting, default after both players | R p22: the players decide where it sits | `test_deals_conserve_and_captain` | uncontested standalone; unavailable in Party (Q11) |
| P23 | Mission 8 is offered to two players and counts the dummy in the balance | C11 | the same evaluator on mission 21: `test_mission_twenty_one_counts_tonoja_in_the_balance_of_color_ones` | confirmed 2026-10-04 (Q6): the dummy is the third crew member for crew-count mechanics |

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
| E-X4 | Tasks `moreRedThanGreen`, `moreYellowThanBlue`, `4with8`, `6with6` | definitions stored, disabled. `5with7` left this list on 2026-10-04 (Q5, AVR-249) |
| E-X5 | Two players with distress or volunteers | refused. Decided 2026-10-04 (Q6): distress and volunteer missions stay deferred. Shared sonar left this list on 2026-10-04 (AVR-250): one token, humans only |
| E-X6 | A TV presentation, bots, solo play | not planned in this scope |
| E-X7 | Campaign history across tables | Party owns durable history; EXPO keeps none |
| E-P1 | In a Party round the starting mission, timed mode and the dummy's seat cannot be chosen | AVR-245 (Q11); `test_a_party_round_locks_settings_so_the_table_opens_on_mission_one` |

## Owner decisions

Each is a question that the sources do not answer. Nothing below was decided by the implementation
team; where the code already behaves one way, that is stated as "Now".

### Governing principle for this phase: fidelity first

Set by the owner on 2026-10-04. Use as much of the supplied official rules and mission design as
possible. The goal of this phase is to prove that the authoritative engine, rule enforcement,
mission system and player-state handling work against a known ruleset. Where official material
gives an answer, follow it. Where a digital implementation needs a policy the material does not
state, choose the smallest conservative behaviour that preserves the original game's intent, and
label it as an Avrana digital policy. Changing rules, missions, tasks or presentation into
something more distinctly Avrana is a later phase, not this one.

### Decisions of 2026-10-04 (AVR-243)

| Q | Decision | Class | Behaviour change | Issue |
|---|---|---|---|---|
| Q1 | A single card of a color may be communicated only as "only" | source-leaning interpretation | yes | AVR-248, implemented |
| Q2 | Keep: mission 16's clock starts at the crew's unanimous Begin | Avrana policy, confirmed | no | |
| Q3 | Keep automatic task-deck replenishment, no crew confirmation | Avrana policy, confirmed | no | |
| Q4 | Keep the reference-derived catalog enabled where no higher source contradicts it; document provenance | reference-derived, accepted | no | AVR-244 for stronger evidence |
| Q5 | Enable `5with7`; keep `4with8` and `6with6` quarantined | source-backed (text layer) | yes | AVR-249, implemented |
| Q6 | Mission 8 stays for two players with the dummy counted; shared sonar uses one token for two players; distress and volunteer missions stay unavailable for two | source-leaning for the first two; deferred for the rest | yes, shared sonar only | AVR-250, implemented |
| Q7 | Keep the cap at mission 50, difficulty 35 | Avrana product limit | no | |
| Q8 | Follow source-specific authority: in missions 10 and 13 the captain decides and only the recipient consents. Keep unanimity for strategic decisions; routine progression should not be frozen by one player | source-backed for 10 and 13; Avrana policy otherwise | yes, missions 10 and 13 | AVR-251, implemented; AVR-252 for progression |

Until the listed issues are implemented, the code behaves as each question's "Now" line says.

**Q1 (C10, AVR-243). May a player's only card of a color be declared highest or lowest?**
Evidence: R p6 lists three conditions and requires one to be met; a single card meets all three
literally; nothing forbids the other two. Against that, R p7 says a declaration is not moved when
it stops being true and gives the example that the "highest" card may later become the "only"
card of its color. That treats "highest" and "only" as different states of a holding, which
suggests "only" is the declaration meant for a single card (added 2026-10-04; an inference, not
an explicit rule). R p23's tip compares declaring an 8 "lowest" against a 9 "highest" for a
two-card holding, which does not bear on a single card. V has no validation; its help text says
only that the card must satisfy one of the criteria.
Now: all three accepted. If restricted to "only": the token carries less ambiguity, and the client
must stop offering two options. If kept: a player can deliberately under-inform.

**Decision (owner, 2026-10-04):** a player holding exactly one card of a color may communicate it
only as "only", never as "highest" or "lowest". Reason given: it matches prior real-world play and
gives the communication states distinct meanings. Implemented 2026-10-04 (AVR-248):
`rules.assertions` returns only `only` for a single card, in every communication mode, so the
engine refuses the other two with nothing changed. A declaration made earlier is never revised: a
card declared "highest" stays "highest" after it becomes the player's last card of that color
(R p7). The "Now" line above describes the behaviour before this change.

**Q2 (C13, AVR-243). When does the real-time clock start?**
Evidence: R p20: start the timer after assigning the tasks; no play or communication before it
starts. Now: at the unanimous begin, after predictions and the distress decision. Alternatives:
start when the last task is assigned (predictions and the distress exchange then spend clock time,
closer to the letter); or disable timed play until decided (the earlier register's position).

**Decision (owner, 2026-10-04):** keep the current behaviour. Begin is the digital equivalent of
the crew deliberately starting the timer after task assignment. C13 and P10 are confirmed.

**Q3 (C09, AVR-243). Is automatic task-deck replenishment acceptable?**
Evidence: R p8 suggests keeping used tasks out until the deck runs low. Now: automatic when the
target is unreachable. Alternative: ask the crew. No effect on rules outcomes.

**Decision (owner, 2026-10-04):** keep automatic replenishment; do not add a crew confirmation.
C09 and P04 are confirmed.

**Q4 (C18, AVR-243). Keep tasks enabled that rest on the reference alone?**
Evidence: R p18 shows the "sum less than" card with 8/12/16 and says totals can be equal to,
greater than or less than a value, and that values may vary with the number of crew. The
"greater than" values 23/28/31 appear only in V's snapshots (23 for two and three players, 28 for
four, 31 for five). `black1`, `black2` use V's "win only" text. Now: enabled. Alternative:
quarantine until a card face is supplied (AVR-244).
Framing corrected 2026-10-04: this question first named only `sumAbove`, `black1` and `black2`.
That understates the position. R describes task *families* and pictures a few cards; it does not
list the 96 cards. For almost every enabled task the exact card, and every number on it, comes
from V. Tasks whose wording R or L also shows are marked `corroborated` in the task catalog
([VTT_REFERENCE](VTT_REFERENCE.md#task-catalog)): 22 of the 96. For several more, R shows the
family and part of the card (a 7 won with a submarine, a 2 in the final trick, "none of the first
... tricks", the never-lead cards) but the PDF's text layer does not give the color or the number,
so they stay `reference`. Everything else, including `sumAbove`, `value22or23` (22 or 23 at every player count in
V, although R says values may vary), `allLess7`, `exactly2trickInARow`, `neverTwoTricksInARow`
and `moreThanHalfTricks`, is V-only in its particulars. One point in favour of `black1` and
`black2`: V's redeal footnotes for them (same hand holds 1 and 4, or 1, 2 and 3) are impossible
deals only under the "win that submarine and no other" reading, so V is at least self-consistent.
Singling out three tasks for quarantine would be arbitrary; the real choice is whether a
V-derived catalog is acceptable until card faces are supplied.

**Decision (owner, 2026-10-04):** keep the reference-derived catalog enabled where no
higher-authority source contradicts it. Do not disable large parts of it merely because the
supplied official material does not contain every card face. Document provenance in three classes:
officially corroborated, reference-derived, and quarantined or conflicted. That classification is
now the Evidence column of the task catalog. AVR-244 remains the path for replacing
reference-derived assumptions with publisher evidence.

**Q5 (C18, AVR-243). Enable `5with7`?**
Evidence: R p17's card reads "a 5 with a 7"; V's values are 5 then 7; the stored definition is
"win a trick with a 7 that contains a 5". Now: disabled together with `4with8` and `6with6`, which
have no R evidence.
Limits of this evidence (added 2026-10-04): it comes from the PDF's text layer. The card picture
itself was not viewed, so whether the 5 and the 7 are drawn in particular colors is unconfirmed;
the stored definition accepts any colors, as V's does. V uses the same "won card, then winning
card" order for `4with8` (win an 8 with a 4, difficulty 3/4/5) and `6with6`, so R confirming the
order for one card is indirect support for the other two, not proof.

**Decision (owner, 2026-10-04):** enable `5with7`; the rulebook text is sufficient at the current
fidelity stage. Keep `4with8` and `6with6` quarantined until better evidence exists.
Implemented 2026-10-04 (AVR-249): `5with7` is enabled with its stored definition unchanged (the
owner wins a trick with their own color 7 and the trick also contains a color 5, any colors).
Tests: `test_five_with_seven_is_enabled_with_its_stored_definition_and_the_others_stay_off`, `test_winning_a_trick_with_a_seven_that_contains_a_five_satisfies_at_once`, `test_other_ways_of_winning_or_losing_the_trick_do_not_satisfy_five_with_seven`, `test_the_seven_and_the_five_are_always_two_different_cards`, `test_five_with_seven_can_be_drawn_selected_and_completes_a_mission`. The "Now" line above describes the state before this change.

**Q6 (C11, AVR-243). Two players: which shared mechanics include the dummy?**
Evidence: R p22: treat the dummy as a third crew member and decide where it sits; for task cards
the three-crew rules always apply; the captain keeps the duty to "follow any special rules for the
missions". R p21's two-player setup gives one sonar token and one reminder card to each player
only, **and sets out the distress signal token** (corrected 2026-10-04: the earlier text said
distress is not mentioned for two players; the token is part of the two-player setup, so R
expects distress to be usable, and what it does not say is how the dummy passes or receives a
card). The shared pool and volunteering are not mentioned for two. V's two-player snapshot has no
distress, pool or volunteer handling at all. Now: distress, shared sonar, terrain and volunteer
missions refused; mission 8 offered with the dummy counted.
Consequences: allowing distress needs a rule for the dummy's passed card (who chooses, from which
cards); a three-seat shared pool has one token.

**Decision (owner, 2026-10-04):** the dummy counts as the third crew member for crew-count
mechanics.
- Mission 8 stays available for two players with the dummy counted. Confirmed; already built.
- Shared sonar uses one token in a two-player game (three seats minus two). This opens the
  shared-sonar mission and the terrain missions to two players. Implemented 2026-10-04 (AVR-250).
- Distress stays disabled for two players. The rules set out the token but do not define how the
  dummy gives or receives the exchanged card; that mechanic is not to be invented now.
- Volunteer missions stay unavailable for two players unless stronger source material defines how
  the dummy takes part.

Implemented 2026-10-04 (AVR-250): the two-player refusal of `rapture` and `terrain` missions is
removed from `content.catalog` and `Engine.prepare`; nothing else changed, because the pool was
already computed as seats minus two and only seated humans could ever communicate. Missions 11,
21, 22, 23, 24, 25 and 27 are offered to two players. The "Now" line above describes the state
before this change. Tests: `test_two_humans_can_prepare_every_shared_sonar_and_terrain_mission`,
`test_two_humans_on_mission_eleven_begin_with_exactly_one_shared_token`,
`test_either_human_may_spend_the_shared_token_and_then_nobody_can_communicate`,
`test_tonoja_never_communicates_and_the_captain_cannot_communicate_for_it`,
`test_two_humans_cannot_use_distress_or_volunteer_missions`.

Checked while building it, and left as the sources have them (see
[MISSION_MODEL](MISSION_MODEL.md#two-players)): mission 21 counts the dummy in the balance;
mission 23 lets the dummy be the first winner; in mission 25 the captain takes no task and still
chooses the dummy's. Mission 27: yellow 5 can be one of the dummy's fourteen cards, even covered,
and if it is the card the dummy never plays the mission fails at the end of the deal
(`test_mission_twenty_seven_with_tonoja_holding_yellow_five`). UNKNOWN: whether a deal exists
that no play can win. No source gives a redeal or a forced choice for it, so none was added.

**Q7 (AVR-243). Continuation cap.** L sets no limit. Now: 50. Raising it only needs the deck to
reach the total, which is checked.

**Decision (owner, 2026-10-04):** keep the finite cap at mission 50, difficulty 35. It is an
explicit Avrana product limit, not a claim that the source imposes it. An endless or escalating
mode may be explored later as a separate feature and is not to be built now. P11 is confirmed.

**Q8 (AVR-243). Unanimity.** Now: every seated human must confirm each of six decisions. A
majority rule would let a table move on without a slow player.
Evidence differs by decision (corrected 2026-10-04; the earlier text said only "R says decide
together"): distress, R p14 to p15, "decide together"; mission 6, L, "decide together"; free
selection, R p21, discuss and allocate accordingly; retry with the same or new tasks, R p11, "you
can choose"; begin, next mission and end have no source and are digital. **Missions 10 and 13 are
different**: L says the captain assumes all tasks or passes them to a willing crew member. That
is the captain's decision plus the recipient's consent. Today any other player can block either
choice, including the captain simply keeping the tasks, which the source does not allow for.

**Decision (owner, 2026-10-04):** follow source-specific authority where the supplied material
defines it. In missions 10 and 13 the captain may keep the tasks without approval from unrelated
players; passing them on requires the willing recipient; unrelated players have no veto.
Implemented 2026-10-04 (AVR-251), see below. For Avrana's own crew decisions, keep unanimity where the crew genuinely
decides together, and do not use it merely for routine progression or administrative actions where
one disconnected, inactive or stubborn player could freeze the table.

Implemented 2026-10-04 (AVR-251), for allocation mode `captain_one` only. The captain naming
themself assigns the tasks in the same command. The captain naming Tonoja does the same, because
the captain decides for Tonoja (R p22); the hand-over rule for sonar still applies. The captain
naming another human leaves an offer that only that human can accept or decline; anyone else's
answer, the captain's included, is refused with no change. A declined offer leaves the pool intact
and the captain chooses again. Still only the captain may offer, and the owner must be eligible
for every task. Every other crew decision is unchanged. The "Now" and "Today" lines above describe
the state before this change. Tests:
`test_the_captain_keeping_the_tasks_takes_effect_in_the_same_command`,
`test_an_offer_is_accepted_by_the_recipient_alone`,
`test_a_third_player_can_neither_confirm_nor_decline_an_offer`,
`test_a_declined_offer_returns_to_the_captain_with_the_pool_intact`,
`test_tonoja_as_recipient_takes_effect_at_once_because_the_captain_decides_for_it`,
`test_a_non_captain_still_cannot_offer_or_keep_the_tasks`,
`test_every_other_crew_decision_still_needs_every_seated_human`.

Not decided by any source and left as it was: the captain cannot withdraw an offer; it stands
until the recipient answers.

Classification of the crew decisions (all unanimous in the code except missions 10 and 13, since AVR-251):

| Decision | Class | Basis | Follow-up |
|---|---|---|---|
| Activate distress and choose its direction | strategic, unanimous | R p14 to p15: decide together | none |
| Mission 6: which seat takes every task | strategic, unanimous | L M6: decide together | none |
| Free selection: each assignment | strategic, unanimous | R p21: discuss and allocate | none |
| Missions 10 and 13 | source-specific | L: the captain decides, a willing recipient consents | AVR-251, done |
| Begin in the timed mission | strategic, unanimous | it starts the clock (Q2) | none |
| Begin in an untimed mission | progression | no source; it also declines distress for the attempt, so a less fragile rule must still let a player ask for distress first | AVR-252 |
| Retry, with the same or new tasks | progression | R p11: you can choose | AVR-252 |
| Next mission | progression | no source | AVR-252 |
| End table | administrative | no source | AVR-240 |

The rule that should replace unanimity for the progression rows is not chosen. No command is
accepted while a seated player is away, so it cannot be settled apart from AVR-240.

**Q9 (C20, AVR-239). The captain is the only seat left for a captain-comparison task.
DECIDED by the owner, 2026-10-04, and implemented.**
Evidence: R p18 forbids the pick; R p9 forbids the pass when tasks are not fewer than seats; R p14
repairs an impossible forced combination by replacing the most recently revealed task with one of
equal difficulty; R p13 calls an avoidable failure a failed attempt.
Decision: (1) an unavoidable allocation is repaired before selection proceeds by replacing the
most recently revealed incompatible task with another of equal difficulty, and no attempt is
counted; (2) an avoidable allocation mistake ends the attempt as a counted failure with a clear
reason; (3) the captain does not pass the task onward (no source supports it).
What "unavoidable" means in the code: in `normal` allocation the captain takes every Nth task (N
seats) and may not pass once there are at least N tasks. With T tasks of which c are captain
comparisons, the captain must take ceil(T / N) tasks, so the draw is unavoidable exactly when
T >= N and T - c < ceil(T / N). With the three comparison tasks that exist this happens only at
three seats (three humans, or two humans and the dummy), with three or four tasks drawn. That is
wider than first recorded: besides mission 11 (target 8) it reaches any clockwise mission whose
target is 8 plus one more task at three seats, such as missions 18, 22 and 24. In `skip_captain`
the captain takes nothing, and the other allocation modes have no forced order.

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

Remaining ambiguities at that head: conflicts C02, C03, C05 to C13, C18 and C20 in
[VTT_REFERENCE](VTT_REFERENCE.md#conflict-register), and owner questions Q1 to Q15 above.
<!-- report:end -->

### AVR-239, 2026-10-04

The first engine change made under these documents. Scope: `games/expo/engine.py` only
(`_captain_conflict`, `_repair_tasks`, `_selection_blocked`); no content, client or adapter
change; snapshot format and content hash unchanged. Conflict C20 is closed and E-D1 fixed.

| Check | Result |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 215 passed, 3 expected failures (E-D2, E-D3, E-D4) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,593 passed, 1 skipped, 3 expected failures, 0 failed |
| The new AVR-239 tests against the engine before the fix | 11 failed, as they should |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2, 3, 4 and 5 humans | passed |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Not covered: the counted failure and the repaired draw were not exercised through a browser, only
through the engine; the client shows them through the ordinary result panel and task list, which
the playtest does cover for other failures. Real phones and the appliance remain unverified.

### AVR-241, 2026-10-04

Scope: one branch in `games/expo/tasks.py` (window tasks) and one condition in
`Engine.view` in `games/expo/engine.py` (currents). No content, client, adapter, snapshot-format
or content-hash change. E-D3 and E-D4 are fixed.

| Check | Result |
|---|---|
| The two pinned tests against the engine before the fix | both failed (reported as expected failures) |
| The new AVR-241 tests against the engine before the fix | 16 failed, as they should |
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 234 passed, 1 expected failure (E-D2) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,645 passed, 1 expected failure, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2, 3, 4 and 5 humans | passed |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Not covered: neither fix was exercised through a browser. The client already shows whatever
declaration and task status the server sends. Real phones and the appliance remain unverified.

### AVR-248, 2026-10-04

Scope: `rules.assertions` in `games/expo/rules.py`. No engine, content, client, adapter,
snapshot-format or content-hash change. Policy P03 is replaced as the owner decided (Q1, C10).

| Check | Result |
|---|---|
| The new and updated tests against the code before the fix | 8 failed, as they should |
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 244 passed, 1 expected failure (E-D2) |
| Communication, currents, privacy, spectator and watcher tests across the repository | 42 passed |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,662 passed, 1 expected failure, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2, 3, 4 and 5 humans (it communicates one card through the page) | passed |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Not covered: the refusal itself was not exercised through a browser, because the client only
offers the declarations the server lists. Real phones and the appliance remain unverified.

### AVR-249, 2026-10-04

Scope: one entry in `games/expo/content/tasks.json` (`5with7`: `enabled` true, `blocked` removed;
every other byte of the file unchanged). No engine, evaluator, client or adapter change.

Content hash: it changed, as intended, because the hash covers the task file. A table saved by
the opt-in snapshot store before this change carries the old hash and is refused on restore: the
file is left as it was and the lobby shows the recovery message until it is removed
(`test_enabling_the_task_changed_the_content_hash_and_old_snapshots_are_refused`). Tables that
live only in memory are unaffected. Snapshot behaviour itself was not changed.

| Check | Result |
|---|---|
| The new and updated tests against the unchanged content | 6 failed, as they should (the evaluator cases already passed: the stored definition did not change) |
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 260 passed, 1 expected failure (E-D2) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,726 passed, 1 expected failure, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2, 3, 4 and 5 humans | passed |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

One earlier whole-repository run showed 5 failures in `tests/test_party_session_cross_repo.py`.
Those tests read the sibling Party checkout, which was being moved to a newer `main` while that
run was in progress. They passed on the rerun recorded above and do not touch EXPO.

Not covered: the task was not played through a browser. Real phones and the appliance remain
unverified.

### AVR-250, 2026-10-04

Scope: the two-human refusal of `rapture` and `terrain` missions, removed from `catalog` in
`games/expo/content.py` and from `Engine.prepare` in `games/expo/engine.py`. No task content,
client, adapter, snapshot-format or content-hash change. The pool size (seats minus two) and the
rule that only seated humans communicate were already in the engine. The browser playtest gained
an optional `EXPO_MISSION` setting, a check of the shared pool after a communication, and the
captain locking a prediction for the dummy.

| Check | Result |
|---|---|
| The new and updated tests against the engine before the change | 33 failed, as they should |
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 294 passed, 1 expected failure (E-D2) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,772 passed, 1 expected failure, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, two humans on missions 11, 21, 22, 23, 24, 25 and 27 | passed |
| `tests/playtest_expo.mjs`, headless Chrome, 2, 3, 4 and 5 humans on the default mission; 3 and 4 humans on mission 11; 5 humans on mission 24 | passed, see the note below |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Playtest note: repeated runs at four and five humans failed now and then, on a task button or a
legal card the script expected on a page that had not yet drawn the newest state. The playtest as
it stands on `main` fails the same way when repeated, at five humans, so this is a timing fault in
the script and not in this change. A run that fails leaves its standalone table stranded (E-D2),
and every later run against that server then times out until the server is restarted.

Not covered: the browser runs use the first legal card, so they show that the two-player missions
start, communicate and reach a result, not that they can be won. Real phones, the appliance and a
Party-launched round remain unverified.

### AVR-251, 2026-10-04

Scope: allocation mode `captain_one` (missions 10 and 13) in `games/expo/engine.py`, and the
decision panel in `games/expo/web/client.js`. A pending offer carries a `recipient`; no other
state, content, adapter or content-hash change. Every other crew decision is unchanged. The
browser playtest gained an `EXPO_OFFER` setting and plays the `captain_one` missions.

| Check | Result |
|---|---|
| The new and updated tests against the engine before the change | 20 failed, as they should |
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py` | 314 passed, 1 expected failure (E-D2) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,816 passed, 2 skipped, 1 expected failure, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, catalog drift check, `ops/check_static.sh` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, mission 10: keep at 3 and 4 humans, offer at 2, 3 and 5 humans; mission 13: keep at 2 and 3 humans, offer at 3 and 4 humans | passed |
| `tests/playtest_expo.mjs`, default mission at 2, 3, 4 and 5 humans; two humans on missions 11 and 25 | passed, see the note below |
| `ops/test_release_safety.sh` | not run locally (needs rsync; GitHub Actions runs it) |

Notes. One playtest run (two humans, mission 11, straight after a five-human run on the same
server) timed out waiting for the lobby and passed on a fresh server: the playtest timing fault
recorded in AVR-254, not this change. Two earlier whole-repository runs stalled in the Party
session tests while other work was loading the machine and moving the sibling Party checkout;
those tests pass on their own and the run recorded above completed normally.

Not covered: the offer panel was checked in headless Chrome only, where the playtest asserts
that only the recipient's page has the answer buttons. Real phones, the appliance and a
Party-launched round remain unverified.

### AVR-254, 2026-10-04

Scope: `tests/playtest_expo.mjs` only. No engine, content, client or server change.

Cause, confirmed by the fix: the script read whose turn it was from one page and acted on another
page that was a revision behind, or that still showed a reloading player as away (its buttons are
withheld then). The same lag let the closing End decision skip a page, so a run could print PASS
and still leave its table open, which made the next run wait in the lobby. Now the script waits
until every page has drawn the newest revision with nobody away before it reads or acts, checks
that each crew decision took effect, and waits for the table to close. A run that fails ends its
own table before exiting, while its players are still connected; E-D2 itself is unchanged.

| Check | Result (Windows 11, headless Chrome, one server for all runs) |
|---|---|
| 20 consecutive runs at five humans | 20 passed |
| 20 consecutive runs at four humans | 20 passed |
| A run forced to fail mid-round (`EXPO_FORCE_FAIL=1`) at 2, 3, 4 and 5 humans, each followed by a clean run on the same server | each forced run exited 1; each following run passed without a restart |
| 2 and 3 humans, default mission | passed |
| Mission 10 offer at 3 humans, mission 13 offer at 5 humans, two humans on mission 11 | passed |
| `ops/check_static.sh`, `ops/check_docs.py` | passed |

Not covered: Linux. No repeated run has been made there yet. This change adds
`.github/workflows/expo-playtest.yml`, a workflow started by hand only (crew size and number of
runs as inputs; never on push or pull request) that starts one server and repeats the playtest
against it. It can be started only once it is on `main`, so the Linux runs are still to be made.
The notes under AVR-250 and AVR-251 above describe the playtest before this change.

### AVR-247, 2026-10-04

Scope: tests and these documents. `tests/test_expo_coverage.py` is new; `tests/playtest_expo.mjs`
gained the unavailable-control checks; `tests/test_expo_docs.py` reads the new file and knows
E-D8. No engine, content, client or shared platform file changed.

Every matrix row that was partial is closed or says why it cannot be tested
([IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md#deterministic-test-matrix)). What the new tests
establish, none of it by changing behaviour:

- No view changes when what its viewer may not see changes (other hands and covered cards in
  every phase; sealed distress choices, a committed secret prediction and a currents declaration
  wherever one exists): every seat, a watcher, an unknown id and the dummy's name, at 2 to 5 players, and the card under a
  column Tonoja has just played from.
- Two commands built at one revision cannot both be accepted, in the engine and from two real
  sockets; the last shared sonar token asked for twice is spent once.
- A dropped socket returns to the same seat, hand, options and table in all seven phases through
  the real WebSocket endpoint, with a sealed choice, a live exposure and a card on the table.
- A stored table restarts exactly at five points (sealed choice, finished exchange, live exposure,
  mid-trick, result); a failed write at each rejects the command, keeps the table and the file,
  and the same request then succeeds. A timed table restored after its deadline has failed.
- Task drawing against a fixed deck order, an unreachable total, a retry with new tasks, missions
  out of order, mission 6 with the dummy, mission 25 at five seats, mission 32 played through.
- Boundaries for every count task, the trick comparisons and their ties, more than half,
  `value22or23`, the last trick at 13, 10 and 8, and the two color-collection tasks.

The tests were checked against ten deliberate faults in a scratch copy (a sealed choice in the
view, a covered card in a played column's place, a value computed from another hand, no revision
check, no rollback after a failed write, a restore that drops sealed choices, a reconnect that
clears spent tokens, a returning phone sent an empty hand, a secret prediction shown to everyone,
a currents declaration shown to everyone). Each fault fails a test. Three tests did not catch
theirs at first and were tightened; the independent review found the third (the reconnect test
compared a returning phone with its own earlier state).

A random walk outside the suite (120 tables at 2 to 5 players over every enabled mission, about
108,000 accepted and 3.8 million rejected commands, every seat offered every kind of command at
every step) met no stuck table, no invariant failure, no leaked card and no error other than a
rejection, apart from the duplicate task recorded as AVR-265.

One defect was found by these tests and recorded, not fixed: E-D8 (AVR-263), the wording of six
unavailable-control reasons. The server refuses each of those requests. Three more were found by
probing while this work was reviewed, each with its own issue and none pinned here: one malformed
crew-decision request freezes the table (AVR-264); after mission 32 a later mission can deal the
same task twice (AVR-265); on a phone a pending crew decision is off-screen for a player looking
at their hand (AVR-266).

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_docs.py` | 457 passed, 2 skipped (distress is not offered to two players), 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 1,963 passed, 4 skipped, 2 expected failures, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json`, `npm run check:syntax` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome, one server for all runs | 55 of 55 passed in two batches (38 before the review changes, 17 after): 13 at five humans, 13 at four, 8 at three, 8 at two; missions 5, 8, 9, 10 (kept and offered), 11, 13 (kept and offered) and 25; a run forced to fail exited 1 and the next run passed. Every clockwise run checked all five refusals; missions 8, 10 and 13 have no task selection and checked the other three |

Not covered: real phones, the appliance, a Party-launched round, Linux for the playtest. The
restore of a timed table after a backward clock step and a snapshot taken before a mission-table
change are recorded defects (E-D7, E-D5) and belong to AVR-242.

### AVR-242, 2026-10-04

Scope: `games/expo/content.py`, `engine.py`, `game.py`, `tests/test_expo_persistence.py` (new) and
these documents. No client, shared session, protocol or provider file changed. A Party round
still neither restores nor writes a snapshot.

- **Content hash (E-D5).** `content_hash()` hashes the task catalog and every mission definition.
  The value changed once, so a snapshot written before this change is refused, as any other
  content would be.
- **The clock (E-D7).** The adapter gives the engine monotonic seconds and translates the deadline
  to a wall-clock moment only for the view and the shared timer. `Engine.expire` ends a running
  deadline. A snapshot carries the two clocks and the boot identity at the time of writing. Rules in
  [GAME_STATE](GAME_STATE.md#restoration-after-a-server-restart). The live case (a wall-clock step
  with no restart granted time) was found while doing this and has the same remedy.
- **Request memory (E-D6).** No code change. The contract now says accepted requests only, with
  the reasons; tests pin each reason.

One behaviour is stricter than the issue asked for: a reboot always ends a running timed attempt,
because nothing on an appliance without a real-time clock says how long it was off. The mission
is 150 seconds and the crew may retry.

Each test of the first version was run against the code before the change: 39 of the 44 failed.
The five that passed are the request-memory tests, which pin behaviour that did not change.

The independent review found that two clocks alone cannot tell a restart from a reboot whose
clocks line up again (an appliance without a real-time clock starts each boot from the same
saved time), and that an attempt ended on restore was not written down, so a second restart
could find it running. Both gave back time the attempt had already used. The boot identity and
the written end close them, each with a test. It also found the shared timer re-armed from a
stale moment after a failed write following a clock step; fixed, with a test.

A second independent review of that head, against the owner's decision that a reboot always ends
a timed attempt, found no path that resumes one across a reboot and none where a backward clock
step grants time. It found that an integer too large for a float in the clock record crashed the
restore instead of ending the attempt, that a saved deadline was not bounded (a hand-edited
snapshot on the same boot could run without end), and that two claims had no test that could
fail: a host with no boot identity at both ends, and the timed variants in the content hash. A
clock reading must now be a finite number of seconds, a running deadline may not be later than a
full timer from the moment its snapshot was written, and each has a test, checked by putting the
fault back. An end that cannot be written is judged again at the next restart; a reboot ends it
again. A check of those fixes found one more raise of the same kind, a deadline left beside a
mission result in a hand-edited snapshot; the engine's own invariant now refuses a deadline that
is not a number or does not belong to a timed attempt in play.

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_persistence.py tests/test_expo_docs.py` | 542 passed, 2 skipped, 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 2,048 passed, 4 skipped, 2 expected failures, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json`, `npm run check:syntax` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome | passed once each at 2, 3, 4 and 5 humans (default mission, untimed) on the final head |

Not covered: a real reboot, a real clock correction, the appliance, real phones. The clocks and
the boot identity in the tests are set by hand; one test runs on the real clocks without a step.
On a host with no readable boot identity (Windows, where these tests ran) a running timed attempt
never survives a restart. The timed mission is
not reachable from a Party round (E-P1) and the playtest does not play it.

### AVR-264, 2026-10-04

One malformed request from a seated player could freeze a table (E-D9). Changed:
`games/expo/engine.py`, `tests/test_expo_input.py` (new), `tests/test_expo_docs.py` and these
documents. No client, adapter, shared session, protocol or provider file changed.

- **Cause.** `Engine.apply` checked the keys of a crew decision but not the type of every value.
  In missions 6, 10 and 13 the `task` of an `assign` decision was never read, so any JSON value
  was stored in the pending decision. A value nested about 500 lists deep fits in one socket
  message; once stored, copying the state raised `RecursionError` in every view, snapshot and
  command.
- **Fix.** The common check now requires every field of a crew decision to be a plain value of
  its own type, before the request can be stored or remembered. Where all tasks go together the
  `task` field must be the word `all`, which is what the client sends. Field types are stated in
  [ACTIONS](ACTIONS.md).
- **Codes.** A value of the wrong type is now `payload` in every case. Three used to carry a
  more specific code: a non-string `direction` (`direction`), a non-integer `mission`
  (`mission`) and a non-string `owner` (`owner`). Values of the right type keep their codes.

Each new test was run against the code before the fix: all 151 failed, the type cases on the
rejection code or on the stored value, the adapter test on `RecursionError`. After it:

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_persistence.py tests/test_expo_input.py tests/test_expo_docs.py` | 693 passed, 2 skipped, 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 2,199 passed, 4 skipped, 2 expected failures, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json`, `npm run check:syntax` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome | passed once each at 2, 3, 4 and 5 humans (default mission); mission 10 kept and offered (3 humans); mission 13 offered (5 humans) |

The independent review passed the change with two findings. Its hostile run (43,800 malformed
requests over every action, field and allocation mode) found nothing against the fix, and each
of five faults put back into the engine was caught by the new tests. It found one more request
of the same class in another field, not fixed here: a request ID that cannot be written as UTF-8
stops a standalone table with a snapshot file from saving or answering (AVR-268). E-D9 is
therefore fixed for crew decisions; it does not claim that no single request can stop a table.
The other finding was a wording error in ACTIONS, corrected.

Not covered: real phones, the appliance, a Party-launched round, the playtest on Linux.
