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
- Twelve defects were recorded (E-D1 to E-D7 by the reconciliation, E-D8 by AVR-247, E-D9 and E-D10 by probing during its review, E-D11 by the review of AVR-264, E-D12 by the review of AVR-268). Nine are fixed: E-D12, request ids that made a snapshot too large to read back (AVR-273), E-D11, a request id that stopped a stored table (AVR-268), E-D10, a task dealt twice after mission 32 (AVR-265), E-D9, the table freeze from one malformed crew decision (AVR-264), E-D1, the selection stall
  (AVR-239), E-D3 and E-D4, late completion of the window tasks and currents visibility
  (AVR-241), and E-D5 and E-D7, the content hash scope and the timed clock (AVR-242). E-D6 was
  settled by amending the contract (AVR-242). Of the two that remain, one affects play and needs
  an owner decision on the remedy: a table cannot be ended while someone is away (AVR-240).
- Twenty-three digital policies are in force. The owner decided the open ones on 2026-10-04
  (AVR-243, questions Q1 to Q8 below). Four decisions change behaviour. All four are implemented:
  single-card communication (AVR-248), the task `5with7` (AVR-249), one shared sonar token for
  two players (AVR-250) and the captain's authority in missions 10 and 13 (AVR-251). A fifth,
  routine progression, was decided on 2026-10-04 and is built for Party rounds: the Party Host
  owns Begin, Retry and Next (AVR-252, with AVR-275).
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
| E-D7 | **Fixed 2026-10-04.** Was: the deadline was a wall-clock moment, so a backward clock step granted time, on restore and (found while fixing it) on a live table with no restart at all. Now: the deadline runs on the monotonic clock; a restored timed attempt continues only on the same boot (by the kernel's boot identity) with both clocks agreeing about how long the server was down, and otherwise ends as a counted failure with its own reason, written to the snapshot. A reboot therefore always ends a running timed attempt | state contract; the appliance has no real-time clock | `test_a_timed_mission_runs_on_the_monotonic_clock_and_browsers_get_a_wall_clock_moment`, `test_a_wall_clock_step_during_a_live_timed_mission_neither_grants_nor_takes_time`, `test_a_restart_on_the_same_boot_continues_the_deadline_and_charges_the_downtime`, `test_a_timed_table_restored_after_its_deadline_has_already_failed`, `test_a_timed_table_restored_under_a_clock_that_cannot_be_trusted_ends_and_never_gains_time`, `test_a_timed_snapshot_without_a_clock_record_ends_the_attempt`, `test_a_host_that_never_could_name_its_boot_ends_the_attempt_on_every_restart`, `test_a_saved_deadline_later_than_a_full_timer_is_not_resumed`, `test_an_end_that_could_not_be_written_is_judged_again_and_a_reboot_still_ends_it`, `test_a_snapshot_with_a_deadline_beside_a_result_is_refused_not_raised`, `test_a_snapshot_with_a_deadline_on_an_untimed_mission_is_refused`, `test_clocks_that_agree_within_two_seconds_on_the_same_boot_are_trusted`, `test_a_failed_write_after_a_wall_clock_step_leaves_the_shared_timer_on_the_true_deadline`, `test_a_table_with_no_running_deadline_restores_whatever_the_clocks_say`, `test_on_the_real_clocks_the_shared_timer_and_the_browsers_get_the_same_150_seconds`, `test_the_engine_expires_only_a_running_deadline` | AVR-242 |
| E-D8 | The reason shown on an unavailable control is not the server's rejection in six places. Two state something untrue: a color card in the distress exchange after the player's own choice is sealed reads "Submarines cannot be passed", and a card that follows suit reads "You must follow the opening suit." while a crew decision is pending (the captain's off-suit Tonoja card reads "Only the captain plays for Tonoja."). Four are a second wording of the same fact: a card before the crew begins, "Take this task" for another seat and for the captain on a comparison task, "Offer all tasks" for a non-captain. The server refuses every one of these requests and nothing changes | action contract ("the client can disable it with the right reason") | `test_defect_the_reason_shown_before_play_begins_is_the_servers_rejection`; the playtest asserts the refusals | AVR-263 |
| E-D9 | **Fixed 2026-10-04.** Was: a crew decision was checked for its keys but not for the type of every value. In missions 6, 10 and 13 the `task` of an `assign` decision was never read, so any JSON value was stored in the pending decision and sent to every viewer; a value nested about 500 lists deep (one socket message) then made every view, snapshot and command raise, and one seated player could freeze the table. Now: every field of a crew decision must be a plain value of its own type and, where all tasks go together, `task` must be `all`; anything else is rejected before it is stored or remembered | action contract (a rejected request changes nothing) | `test_an_assign_field_of_the_wrong_type_is_refused_in_every_allocation_mode`, `test_every_other_decision_field_of_the_wrong_type_is_refused`, `test_where_all_tasks_go_together_the_task_field_is_the_word_all`, `test_the_request_that_froze_the_table_is_refused_and_the_table_plays_on` | AVR-264 |
| E-D10 | **Fixed 2026-10-04.** Was: mission 32 took its four named tasks without removing them from the task deck; after it ended they were in the used pile too, and once the deck was refilled from the used pile a later mission could deal the same task twice. Assigning the second copy overwrote the first copy's owner, so one task disappeared and the mission was easier than its difficulty. Now: a fixed mission takes its tasks out of the deck and the used pile, and the engine's invariant refuses any state with a task id twice in a pile or in two piles | no source involved: a task card cannot be in two piles | `test_no_task_is_dealt_twice_in_the_missions_after_mission_thirty_two`, `test_no_task_is_dealt_twice_for_any_crew_size`, `test_retries_before_and_after_mission_thirty_two_keep_every_task_in_one_place`, `test_mission_thirty_two_takes_its_four_tasks_out_of_the_deck_and_the_used_pile`, `test_a_table_that_opens_on_mission_thirty_two_deals_its_four_tasks`, `test_the_reported_table_reaches_mission_forty_seven_with_distinct_tasks`, `test_a_snapshot_with_a_task_in_two_places_is_refused` | AVR-265 |
| E-D11 | **Fixed 2026-10-04.** Was: a request id was checked only for its length; one that cannot be written as UTF-8 (a lone surrogate) on an otherwise legal command was accepted and remembered, the snapshot write then raised, and every later command on a table with a snapshot file raised too. Now: a request id is 1 to 80 printable ASCII characters, and a snapshot that cannot be written as text is a failed write: the command is rolled back and answered `storage` | action contract (a rejected request changes nothing); state contract (a failed write rolls back) | `test_a_request_id_that_is_not_plain_printable_text_is_refused`, `test_a_plain_request_id_is_still_accepted`, `test_an_unstorable_request_id_leaves_a_stored_table_saving_and_answering`, `test_a_snapshot_that_cannot_be_written_as_text_is_a_storage_failure_not_a_crash`, `test_the_store_reports_any_snapshot_it_cannot_write_as_a_failed_write` | AVR-268 |
| E-D12 | **Fixed 2026-10-04.** Was: a request id could be any printable ASCII, and an accepted id is written into the snapshot twice, the second time inside a string, where a quotation mark takes four bytes. Two seats alternating a proposal to end and its refusal with ids of 80 quotation marks passed the 4,000,000 bytes the server reads after about 6,900 accepted commands, short of the 10,000 an attempt allows. The table kept playing and a restart refused its file. Now: a request id is 1 to 80 letters, digits and `-`, which makes the same run of 10,000 a file of 2,744,892 bytes, and 3,069,966 bytes with the largest command a seat can have accepted (both measured); and the store never writes a file over the limit it reads with: that command is rolled back and answered `storage` | state contract (a table with a snapshot file survives a restart; a failed write rolls back) | `test_a_request_id_is_letters_digits_and_hyphens_only`, `test_two_seats_filling_the_request_memory_leave_a_file_the_server_reads_back`, `test_a_command_whose_snapshot_would_pass_the_size_limit_is_rolled_back_and_the_table_restarts`, `test_the_store_counts_the_bytes_of_the_file_against_the_limit_it_reads_with` | AVR-273 |

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
| P09 | Begin, distress, collective assignment, retry, next and end need every seated human's confirmation | R says "decide together" | `test_distress_sealed_exchange_and_persistence`, `test_ending_the_table_is_abandoned`, `test_every_other_crew_decision_still_needs_every_seated_human` | decided 2026-10-04 (Q8): unanimity stays for strategic decisions; missions 10 and 13 follow the source instead (AVR-251, built 2026-10-04); in a Party round the Party Host commits Begin, Retry and Next and ends EXPO (AVR-252, built 2026-10-04 with AVR-275: `test_the_host_begins_at_once_and_nobody_votes`, `test_no_other_crew_member_can_move_the_table_on`); a standalone table keeps unanimity for them |
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
| E-X1 | Presentation and causality events from the two draft presentation specifications (who triggered a failure, "impossible" state, synchronized events, cinematic client) | **Engine half built 2026-10-04 (AVR-246)**: semantic events, failure causality, objective states, a resolving phase; the drafts are committed as non-canonical files. The client half (anything shown, heard or felt from them) is DEFERRED, AVR-267. What is and is not built: [the AVR-246 report](#avr-246-2026-10-04) |
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
| Begin in the timed mission | lifecycle with a strategic prerequisite | owner, 2026-10-04: starting the clock does not create a crew vote | AVR-252, built for Party rounds |
| Begin in an untimed mission | lifecycle with a distress prerequisite | owner, 2026-10-04: the host starts, and the crew must still be able to ask for distress first | AVR-252, built for Party rounds; the size of that opportunity is open (AVR-275 report) |
| Retry, with the same or new tasks | lifecycle | R p11: you can choose; owner, 2026-10-04: the host chooses | AVR-252, built for Party rounds |
| Next mission | lifecycle | owner, 2026-10-04: the host advances | AVR-252, built for Party rounds |
| End table | administrative | owner, 2026-10-03: Party Host | built for Party rounds (the Party's own end); away handling AVR-240 |

Decided by the owner on 2026-10-04 (AVR-252): in a Party round the Party Host commits the
lifecycle rows and nobody votes; the host cannot skip a prerequisite the rules set; strategic
rows are unchanged. A standalone table, and a Party that does not name its host, keep unanimity
for them as a local fallback. No command is accepted while a seated player is away (AVR-240),
the host's included; the Party's own end is the one thing that still works then.

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
whether a causality record is wanted in results. **Decided 2026-10-04:** commit both as
non-canonical design and product references; a causality record is wanted. Built:
[the AVR-246 report](#avr-246-2026-10-04).

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

A reboot always ends a running timed attempt as a counted failure and is never resumed: the
owner's decision of 2026-10-04, recorded on AVR-242. Nothing on an appliance without a real-time
clock says how long it was off. The mission is 150 seconds and the crew may retry. The same
decision settled request memory as accepted requests only.

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
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_persistence.py tests/test_expo_docs.py` | 543 passed, 2 skipped, 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 2,067 passed, 4 skipped, 2 expected failures, 0 failed, with `main` merged in (`365c4bc`) |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json`, `npm run check:syntax` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome | passed once each at 2, 3, 4 and 5 humans (default mission, untimed), on `b1e43e8` and again after `main` was merged in (`365c4bc`) |

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
stops a standalone table with a snapshot file from saving or answering (AVR-268, since fixed
as E-D11). E-D9 is
therefore fixed for crew decisions; it does not claim that no single request can stop a table.
The other finding was a wording error in ACTIONS, corrected.

Not covered: real phones, the appliance, a Party-launched round, the playtest on Linux.

### AVR-265, 2026-10-04

After mission 32 a later mission could deal the same task twice (E-D10). Changed:
`games/expo/engine.py`, `tests/test_expo_deck.py` (new), fixtures in four existing test files,
`tests/test_expo_docs.py` and these documents. No client, adapter, shared session, protocol or
provider file changed.

- **Cause.** Mission 32 took its four named tasks without removing them from the task deck. When
  it ended they went to the used pile as well, and when the deck was refilled from the used pile
  an id was in it twice. `Engine.check` compared sets and did not notice.
- **Fix.** A fixed mission takes its tasks out of the deck and the used pile, like a drawn card.
  `Engine.check` now refuses a deck, used pile or selection that holds an id twice, an id in the
  deck and in another pile, or an id in the used pile and in a mission still in play. The rule is
  in [GAME_STATE](GAME_STATE.md).
- **A snapshot written before the fix.** One taken during or after mission 32, on a table that
  reached it from another mission, holds the four tasks in two places. It is refused on restore
  with the usual recovery message, whether or not a duplicate was ever dealt.
- **Fixtures.** About twenty existing tests lay tasks out by hand and left the same cards in the
  deck. They now take them out (`place` in `tests/test_expo.py`). No assertion was changed.

Each test of the first version was run against the code before the fix: 300 of 301 failed. The
one that passed opens a table on mission 32, which was never affected. After it:

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_persistence.py tests/test_expo_input.py tests/test_expo_deck.py tests/test_expo_docs.py` | 996 passed, 2 skipped, 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 2,502 passed, 4 skipped, 2 expected failures, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome | passed once each at 2, 3, 4 and 5 humans (default mission) and mission 25 (3 humans) |

Not covered: real phones, the appliance, a Party-launched round, the playtest on Linux. No
browser run plays mission 32 followed by enough missions to refill the deck; the engine tests do,
for 200 seeds at three players and 20 each at two, four and five.

A random walk over 120 tables (about 108,000 accepted and 3.8 million rejected commands, the
invariants checked after every step) met no failed invariant and no error other than a rejection.

The independent review passed the change with minor findings. Its own walks (about 130,000
accepted commands with a restore after every step, and 1,200 tables of retries and next missions)
found no state the invariant refuses in legitimate play; the same walk on the engine before the
fix found 79,642. Ten faults put back into the engine were each caught by the new tests. On its
findings the invariant now also covers the pool and refuses a disabled task in any pile, and the
note on old snapshots above was corrected. It found one defect that is older than this change
and not fixed here: a next mission or a retry with new tasks is sometimes refused because a
replacement task is looked for in the deck only (AVR-270).

### AVR-268, 2026-10-04

A request id that could not be written to the snapshot file stopped a standalone table (E-D11).
Changed: `games/expo/engine.py`, `games/expo/storage.py`, `tests/test_expo_input.py`,
`tests/test_expo_docs.py` and these documents. No client, adapter, shared session, protocol or
provider file changed.

- **Cause.** A request id was checked only for being 1 to 80 characters. An accepted id is kept
  in the request memory, which is part of the snapshot. An id with a lone surrogate (a half of a character pair,
  which JSON can carry) was accepted and remembered; writing the snapshot as UTF-8 then raised, and so did
  every later command, after changing the table in memory. `ExpoSession.game_action` handles a
  failed write only as `OSError`.
- **Fix, in two places.** The engine accepts a request id of printable ASCII only (the client
  sends a UUID); anything else is `payload` and nothing is stored. The snapshot store reports a
  snapshot it cannot write as text as a failed write, so the command is rolled back and answered
  `storage`, whatever value caused it. A player name comes from the platform, not from EXPO; the
  second test covers a name the file cannot hold.
- **Scope.** A Party round and a table without a snapshot file were never affected.

Each new test was run against the code before the fix: 17 of 21 failed (the four that passed
check that ordinary ids are still accepted). With the engine check alone, the storage test still
failed. After both:

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_coverage.py tests/test_expo_persistence.py tests/test_expo_input.py tests/test_expo_deck.py tests/test_expo_docs.py` | 1,024 passed, 2 skipped, 2 expected failures (E-D2, E-D8) |
| `pytest` (whole repository, with a sibling Party checkout present) | 2,548 passed, 4 skipped, 2 expected failures, 0 failed |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json` | all passed |
| `tests/playtest_expo.mjs`, headless Chrome | passed once each at 2, 3, 4 and 5 humans (default mission) |

The independent review passed the change with findings, none Important. Its hostile run (4,696
requests on a stored table and 617 tables with hostile names, settings and tokens) left every
table saving, answering and restarting. One finding was inside this change, an untested arm of
the store's failure handling; it has a test now. Recorded and not fixed here:

- Two cooperating seats can still make a snapshot too large to read back, with about 7,000
  accepted commands whose request ids are all quotation marks (each is escaped twice in the
  file). The table keeps playing and is lost only at a restart. Filed as AVR-273 and since
  fixed as E-D12.
- An integer of more than 4,300 digits raises out of `Engine.apply`. A socket cannot deliver one
  (the JSON reader refuses it); state and file are unchanged.

The counts above include `main` and the later AVR-242 commit merged in. The playtest was run
before that merge and not repeated.

Not covered: a live socket carrying the request (the tests call the adapter), real phones, the
appliance, a Party-launched round, the playtest on Linux.

Later the same day the branch was brought up to `main` with the one-viewport and Party Host
work (AVR-275, AVR-252, AVR-266). The fix did not change. The new tests were run again without
it: with the engine check taken out 16 of the 27 failed, with the store's handling taken out 6
did. With both in place, `pytest tests/test_expo_*.py` gave 926 passed, 2 skipped, 2 expected
failures (Windows 11). The whole repository and the playtests were not run again.

### AVR-273, 2026-10-04

Request ids could make a snapshot file larger than the server reads back (E-D12). Built on the
AVR-268 branch. Changed: `games/expo/engine.py` (the form of a request id),
`games/expo/storage.py` (the size limit), `tests/test_expo_input.py`, one line each in
`tests/test_expo_authority.py`, `tests/test_expo_coverage.py` and `tests/test_expo_docs.py`,
and these documents. No client, adapter, shared session, protocol or provider file changed,
and the snapshot format is still version 1.

- **Cause.** The file is refused above 4,000,000 bytes when it is read; nothing limited it when
  it was written. An accepted request id is in the file twice, as part of a key and inside the
  remembered message, which is itself a string: there a quotation mark or a backslash takes
  four bytes. With ids of 80 quotation marks one remembered command took about 580 bytes, and
  10,000 are allowed in an attempt.
- **Fix, in two places.** A request id is 1 to 80 characters, each an ASCII letter, a digit or
  `-`; this replaces the printable ASCII of AVR-268. None of these characters is escaped. The
  store makes the bytes of the file first, counts them against the one limit that reading uses
  (`MAX_SNAPSHOT_BYTES`), and refuses a larger file as a failed write before a temporary file
  exists. The adapter already rolls a failed write back and answers `storage`. The file is
  still written to a temporary file, flushed, synced and moved into place.
- **What sends a request id.** The page (`crypto.randomUUID()`), the two browser playtests (the
  same) and the tests. Two test helpers wrote ids with a full stop or an underscore and were
  changed. The Party sends none: its host action has no `request` ([ACTIONS](ACTIONS.md)).
- **Not done, on purpose.** The request memory is not compacted or hashed and the snapshot
  format did not change. A snapshot written before this change with other characters in its
  request memory is still restored; such an id can no longer be sent, so it can no longer be
  repeated either.
- **At the limit.** A table whose file would pass the limit refuses every command that makes it
  larger, the same way a full disk does; it stays as it was and restarts. Request ids cannot
  get a table there (see the numbers below). The one known way is a large file written before
  this change; what that means for an operator is in
  [GAME_STATE](GAME_STATE.md#restoration-after-a-server-restart).

Measured on this branch (Windows 11), two seats alternating a proposal to end and its refusal,
every id 80 characters:

| Run | Result |
|---|---|
| 10,000 commands, ids of letters and digits (this branch) | all accepted; the file is 2,744,892 bytes; the next command is refused by the request limit; a restart restores the table with all 10,000 remembered |
| the same with the largest proposal a seat can have accepted: mission 17, a task with the longest id (23 characters) offered to Tonoja, declined (this branch; this is what the test runs) | all accepted; the file is 3,069,966 bytes; the same refusal and restart |
| ids of quotation marks on the AVR-268 branch, before this change | the file was 4,056,834 bytes at 7,000 commands (the run saved every 250th, and the save before was under the limit); a restart refused it |

Each new test was run without each half of the fix. With the AVR-268 form of the id put back,
10 of the 14 id cases failed (the other four were refused before too). With the size check
taken out of the store, both size tests failed. The full run of 10,000 passes with or without
the fix, because ids of letters and digits never made a file too large: it is there to fail if
the request memory ever grows. It is the slow test of the file, 36 to 45 s here: every command
copies the whole request memory for its rollback, in the engine, which this change did not
touch.

The size of a full request memory was also calculated, by writing 10,000 entries in the
engine's own format (checked equal to the request memory of 20 real commands) and adding the
11,056 bytes of the rest of the file:

| Request memory of 10,000, two seats, every id 80 characters | File, bytes |
|---|---|
| propose to end, decline | 2,744,946 (measured: 2,744,892) |
| propose distress, decline (needs three humans; calculated with two seat ids) | 2,899,946 |
| offer a 23-character task to Tonoja, decline | 3,069,946 (measured: 3,069,966) |
| the same with attempt 9,999, seat ids of four characters and revisions from 1,000,000 | 3,181,056 |
| 10,000 such offers and no refusals (not reachable: an offer waits for its answer) | 3,489,946 |

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo_*.py` (before the review's findings) | 945 passed, 2 skipped, 2 expected failures, in 94 s |
| `pytest tests/test_expo.py` (before the review's findings) | 140 passed |
| `pytest tests/test_expo_input.py tests/test_expo_docs.py tests/test_expo_persistence.py` (after them) | 298 passed in 49 s; the full run took 42 s of it |
| `ops/check_docs.py`, `tests/test_no_private_data.py`, `ops/export_avrana_catalog.py --check provider/catalog.json` | all passed |

Not run: the whole repository, the browser playtests (their page code did not change; it sends
a UUID), the Party cross-repo tests, anything on Linux, a real phone, the appliance.

The independent review passed the change with findings, none Important, all taken:

- The size first given for a full request memory was that of the issue's run, which is not the
  largest. The test now runs the largest accepted command and the numbers above replace it.
- The test's comment said it was kept to seconds; it takes most of a minute, and says so now.
- What a table at the size limit means for an operator was not written down. It is in
  [GAME_STATE](GAME_STATE.md#restoration-after-a-server-restart) now, after a probe on a table whose
  limit was brought down: the proposal to end was accepted, every answer to it was refused
  with `storage`, and a restart restored the table with the proposal still pending.
- Two wording and source nits, corrected.

### AVR-275, AVR-252 and AVR-266, 2026-10-04

The phone client was rebuilt around one viewport, and a Party round got its two authorities.
Changed: `games/expo/web/` (all three files), `games/expo/game.py`, `games/expo/engine.py`
(one added command, no rule changed), `core/net.py`, `core/session.py`, `web/hubnet.js`,
`core/party_protocol.py` and its vectors (re-vendored), the provider contract digests, two
playtests, `tests/test_expo_authority.py` (new) and these documents. Needs avrana-party's host
claim and host question (ADR 0006, amendment 2026-10-04) to be deployed for the host rules to
apply; without them a Party round falls back to crew votes, transitionally and visibly, except
that no seat ends it from inside.

- **One viewport (AVR-275).** The page no longer scrolls. From top to bottom: the bar (table
  menu, title, help), the status line, the mission and trick counter, two objective lines, the
  crew strip, the stage, four tabs, the hand, the dock. Only the stage flexes. The stage shows
  the trick during play, with a place for every seat and the trick that just ended until the
  next card; before play it shows the one thing waiting (task selection, predictions, the
  pre-mission panel, the distress exchange); a pending crew decision replaces it. Crew detail,
  full tasks, sonar and the latest trick are sheets over the board. Short screens drop
  decoration, not information, down to 360 x 600.
- **The result takes over (AVR-275).** A mission result covers the board for every viewer:
  outcome, the engine's reason, any task the engine marked failed with its owner, and the last
  resolved trick. None of that is inferred by the page. The result can be put away to look at
  the table and then holds the dock until shown again. The triggering play is not shown because
  the engine does not report one yet (E-X1, AVR-246); a `cause` string is displayed when it does.
- **Host and captain (AVR-252).** In [ACTIONS](ACTIONS.md#crew-decisions) and
  [GAME_STATE](GAME_STATE.md#party-rounds). The engine gained `Engine.lifecycle`, which commits
  Begin, Retry or Next for whoever the adapter authorized and reuses the proposal checks, so the
  prerequisites are the same sentences as before. `Engine.apply` is unchanged.
- **Pending decisions on a phone (AVR-266).** The decision is in the stage, inside the viewport
  with the hand; the status line announces it; a disabled control's reason is text beside it.
- **Home (AVR-275).** The masthead no longer links to `/` (the retired LAN Games hub), and the
  title is no longer a link (it dropped `?avrana=1`, after which the page behaved as a
  standalone LAN game). The table menu offers the Party Host "End EXPO for everyone" (the
  Party's own end), tells everyone else who can, and outside a Party round links only to the
  Party Home the integration script names. The service worker that still precaches the hub at
  `/` is AVR-274 and was not touched: an integrated page already bypasses it.
- **Card play changed shape.** A tap chooses a card and the dock's button plays it. This is a
  presentation choice against mis-taps on 44 px cards, not a rule: no legal card is warned about.

**Two merges, not one.** The work above merged as avrana-party-games#44 (at 1d2e602) before
the owner's decisions below were built. Everything from here to the results table is the
follow-up PR on top of `main`. Between the two merges `main` vendors a session protocol
(avrana-party 0892729) that is on neither Party's `main` nor its final branch, so the paired
contract check fails for `main` until avrana-party#75 and the follow-up are both merged.
Nothing is deployed from that interval.

Owner decisions of 2026-10-04 on what that left open, and what was built for each:

- **The host claim is accepted; a former host must have nothing to spend.** Built: the game
  server asks the Party at every host action whether that participant is its host now
  (avrana-party ADR 0006, amendment 2026-10-04). Tickets kept from before a succession still
  say `host: true` and are refused at once. Party Core stays the only place the host exists.
- **Distress gets a protected opportunity, not a vote.** Built: the host's Begin is closed for
  4 s after the tasks are settled where distress is available; a pending request keeps it
  closed; nobody confirms anything to start ([ACTIONS](ACTIONS.md#crew-decisions)).
- **An away seat keeps blocking Begin, Retry and Next** this sprint (AVR-240). Unchanged. The
  Party Host can always end EXPO from the Party; tested with a seat away.

Hardening pass, same day:

- **Authority words.** "Party Host" is never shortened to "Host" on the page and never used for
  what the crew or the Captain decides. The dock names its two zones "Party Host (table
  control)" and "Captain" or "Crew member (your role in the game)"; the table menu lists Party
  Host, Crew and Captain with what each decides. The host's badge needs a seat whose name is
  the host's alone (the Party gives the page a name, not a seat).
- **Host capability.** Begin, Retry and Next only; everything else through that message is
  refused (`test_the_host_gets_begin_retry_and_next_and_nothing_else`).
- **Reloads.** Tested in the browser during a pending decision, a partly played trick and a
  result, for the host and for a crew member, and for both phones after a succession. The page
  now reads the Party's view again on its own tick, because after a reload that view can arrive
  after the table's state and not every path announces it.
- **iOS viewport.** The body is pinned (`position:fixed; inset:0`, `overscroll-behavior:none`)
  because iOS Safari scrolls a body that is only `overflow:hidden`; the app is `100dvh` with a
  `100vh` fallback, capped by the body; left and right safe-area insets are honoured as well as
  top and bottom; inner scrollers contain their overscroll; the board under a sheet or a result
  is `inert`. Inspected and tested in desktop Chrome with touch emulation. **Not verified on an
  iPhone.**
- **Fullest board.** Asserted with 14-character names, a long sentence on eight tasks and a
  14-card hand, at every phone size.
- **Touch targets.** Every control is at least 44 px tall and 40 px wide at every tested size
  (a hand of seven shares 360 px). Short screens take the room from the trick.
- **Focus.** A sheet and the result hold the keyboard and screen reader (inert board, Tab
  cycle); closing gives focus back to what opened it; putting the result away moves focus to
  the one dock button that brings it back, which says what it leads to.
- **No host claim.** Marked transitional in the view, the page and the server log.

Still open:

- **Recovery from an away seat** (AVR-240).
- **Mission, timed mode and Tonoja's seat** cannot be chosen in a Party round (AVR-245). The
  host's Next is the only way to another mission.
- **Causality in the result** (AVR-246) and **the service worker** (AVR-274).
- **Turning `HOST_CLAIM_TRANSITION` off.** Not part of the first deployment. Order agreed with
  the owner: avrana-party#75 merges, then this repository's hardening PR; both are deployed
  together; a real-phone test on the appliance confirms the Party Host claim works in
  production; only then a small follow-up sets the flag False. Until then a rollback of either
  service leaves tables playable.
- **Not AVR-267.** No art, animation, audio or event-driven presentation was added.

| Check | Result (Windows 11) |
|---|---|
| `pytest -q` (whole repository) | 2565 passed, 4 skipped, 2 xfailed |
| `tests/test_expo_authority.py` | 42 passed |
| `node tests/hubnet_party_ticket_test.mjs` | 46 of 46 |
| `node tests/playtest_expo.mjs`, 2, 3, 4 and 5 humans | PASS each, five phone sizes from 360 x 600 to 412 x 915 |
| `node tests/playtest_expo_party.mjs`, 2, 3, 4 and 5 seated | PASS each |
| `node tests/playtest_expo_party.mjs`, 3 seated and a watching host | PASS |
| `EXPO_PARTY=old node tests/playtest_expo_party.mjs` (no host claim) | PASS |
| `ops/check_docs.py`, `ops/check_static.sh`, `tests/test_no_private_data.py`, catalog export check | OK |
| Party `tools/contract_check.py --games` against this branch | compatible |
| A real phone | not run |

### AVR-246, 2026-10-04

Entry E-X1: the engine now reports what happened and why an attempt failed, and holds the table
for a moment between tricks. Contract:
[GAME_STATE](GAME_STATE.md#semantic-events-failure-causality-and-the-resolving-phase). Changed:
`games/expo/engine.py`, `games/expo/tasks.py`, `games/expo/game.py`,
`tests/test_expo_events.py` (new), two test helpers, these documents, and the two drafts added as
non-canonical files. Not changed: the client, `core/`, the provider contract, the catalog, the
snapshot format number.

**Owner decisions carried out (Q12).** Both draft presentation specifications are committed
beside the canonical documents, each under a banner that says it is non-canonical and loses to
the code and the canonical documents; `tests/test_expo_docs.py` enforces the banner, the manifest
class and that every file in `docs/` is on one list or the other. A causality record is wanted
and is built.

**Built.**

- Semantic events in eleven families, numbered for the life of the table, in a fixed order,
  identical for the same seed and commands, with no presentation instruction in them.
- A bounded log (240 events) in the state and the snapshot; a viewer is sent the events of the
  latest resolved trick and after, of the attempt in play, as copies; a currents declaration only
  in its author's events.
- Failure causality: objective, kind of failure, triggering seat and card where that is a fact,
  affected seat, the committed action, the cards, the trick, the mission context.
- Objective states PENDING, ACTIVE, COMPLETED, FAILED and IMPOSSIBLE beside the unchanged
  `status`.
- The resolving phase: a mark in the state, a refusal for every seat, a server settle that the
  adapter calls after 0.8 s, on a late command, or at once on a restore. A timed mission's clock
  runs through it and its deadline does not move (owner decision, 2026-10-05; see "Owner
  decision" below). As first written this entry did the opposite: the clock stood and the hold
  was credited to the deadline. This is the one place the change touches a number the rules
  care about: the attempt is 150 seconds on the clock, and the holds are inside them.
- `tasks.judge`, which labels a failure the evaluator already found. Two comparisons were made
  **by hand; neither is in the repository** and neither can be rerun from it. The author
  compared it with the evaluator before the change on 5.7 million judgements of all 96 task
  definitions on random tables: every status was the same. The independent reviewer reported,
  separately: 1.92 million judge-against-evaluate comparisons equal; the engine before the
  change and this one driven through 196 games and 69,584 commands with no divergence;
  snapshots readable in both directions; 15 of 15 of the reviewer's own faults caught. What the
  repository keeps is `test_the_failure_kind_is_a_label_and_never_changes_a_task_status`.

**Not built, on purpose.**

- **No client work.** The page draws exactly what it drew: it does not read `events`, `cause`,
  `resolving` or a task's `state`. During the hold it shows the resolved trick and the sentence
  "The trick is being resolved." beside disabled cards, because that is the view's reason. The
  result does not show the cause yet (the page shows `result.cause` only if it is a string; the
  engine's cause is a record beside the result). Presenting any of this is AVR-267.
- **No presentation timing in events.** The drafts ask for a scheduled presentation time on
  events. Only one moment exists: `resolving.until`, added by the adapter to the view.
- **No director, no fiction, no cinematic templates, no assists**, no audio or haptics.
- **No earlier mission end.** The product contract allows ending a mission once impossibility is
  proven "where consistent with the rules". Nothing was added: `IMPOSSIBLE` names the failures
  the evaluators already detected.
- **No full-attempt debrief to clients.** The log holds the whole attempt; a viewer is sent only
  the latest trick, also after the result, because R04 lets only the last trick be looked at
  again. Sending more after a mission ends is a product decision that was not made (below).
- **Events for selection, prediction, the distress exchange, a seat going away and the end of a
  table** do not exist.

**Differences from the drafts.** Names and shapes are the engine's own (`trigger_seat`, not
`triggerPlayerId`; suit:rank cards; `phase` and `stage` unchanged). `RESOLVING` is a mark beside
the phase, not a phase value, and there is no `COMPLETE` status after it. The drafts' example
calls a named card won by another player "failed"; the engine calls that `IMPOSSIBLE`, as the
draft's own state model defines it. The drafts' objective constructors, legality response shape
and performance tiers were not implemented and are not planned by this entry.

**For the owner.**

1. May a client be sent the whole attempt's events once the mission has a result (a debrief or a
   replay)? Now: no, the latest trick only.
2. `RESOLVE_HOLD` is 0.8 s, from the draft's "under one second". It is one constant in
   `games/expo/game.py`; changing it changes no rule. Its length is still the owner's to
   confirm. What a timed mission's clock does during it is **decided** (2026-10-05, below): it
   runs, so in timed mission 16 the holds take up to about ten of the crew's 150 seconds.
3. The triggering seat is the trick's winner. That is an attribution of the deciding card, not
   of fault; a presentation that blames a player on it should know that.
4. The drafts as committed: the example players' first names were replaced by the repository's
   stand-in names (Alice, Bob, Carol), 30 and 7 occurrences, and a banner was added. The title
   "The Team II" was left as written; it is the reference tabletop's name, which
   [VTT_REFERENCE](VTT_REFERENCE.md) already uses, not the publisher's.

**Owner decision, 2026-10-05 (recorded on AVR-246).** "Timed missions do **not** gain time
during the 0.8 s resolving hold. The mission clock continues to run on monotonic elapsed time
while presentation/resolving temporarily prevents the next action. Implementation should
preserve a clean trick-resolution boundary, but that boundary must not extend the mission
deadline. If a deadline expires during resolving, finish resolving the already-committed trick,
then evaluate expiry before opening another actionable turn."

What changed for it, in `games/expo/engine.py` and `games/expo/game.py`:

- `Engine.settle(credit)` is `Engine.settle(now)`. It never changes `expiry`. With the caller's
  clock at or past the deadline it clears the resolving mark and ends the attempt by time
  (`Engine.expire`, the same result and cause as every timeout) and emits no `TURN_STARTED`;
  otherwise it opens the winner's turn as before. The engine still keeps no clock: `now` is
  the adapter's monotonic reading, as it is for `observe_time`.
- `Engine.observe_time` still records nothing while a trick is resolving, now for a different
  reason: the committed trick is settled first, and `settle(now)` judges the deadline.
- The adapter no longer computes a credit; it passes its clock to `settle`. The session's one
  timer still waits for the end of the hold, where the deadline is judged in the same step.
  The view's `expiry` is the deadline itself during a hold: the adjustment of commit 1abc97d
  (deadline plus hold) is removed, and with it the limit it documented.
- A restore settles with the clock when the clock can be trusted, and ends the timed attempt
  before settling when it cannot, so neither path opens a turn on a table that has run out.
- Untimed tables: no value differs. `settle` reads `now` only when there is a deadline.

Not changed, and still the owner's: whether a client may be sent the whole attempt's events
after a result (1), the length of the hold (2), the attribution of the triggering seat (3), the
drafts' example names (4).

A consequence to know: the hold is not cut short by the deadline. A timeout that falls inside
a hold is recorded when the hold ends, up to 0.8 s after the deadline (the decision's "finish
resolving the already-committed trick, then evaluate expiry"). No seat can act in that time,
and a client's countdown reads zero while `resolving` is still set.

Tests: the timed and resolving cases in `tests/test_expo_events.py` were rewritten. Four tests
were removed outright with the behaviour they asserted (they are in the history at 1abc97d and
are not cited by name here, because no such test exists now): the clock standing during a hold
with the hold credited, the hold and the deadline sharing one timer with the hold credited, the
view never showing a deadline the hold would move, and a hold spanning the old deadline never
shown as expired. Two were replaced by named counterparts: the one on what a settle may credit
by `test_a_settle_with_no_usable_clock_settles_the_trick_and_judges_no_deadline`, and the one
on what a lost timer credits by `test_a_lost_timer_gives_a_timed_table_no_time`.
Seventeen of the new cases fail on the code before this decision (checked by running the file
against the engine and the adapter of commit 1abc97d). The engine-level case
`test_the_deadline_of_a_timed_mission_is_the_same_after_any_number_of_holds` does not, because
the old `settle` ignored a credit over 60 seconds; the adapter-level
`test_a_timed_mission_lasts_exactly_its_configured_seconds_however_many_tricks_were_held`
covers the same claim and does fail on it. Neither browser playtest was run for this change.

**Not verified.** The author did not run the two browser playtests (the orchestrator did,
afterwards: see the table), and no phone has shown the hold. Both scripts read whose turn it is and then expect a legal card, which
a resolving table does not offer, so their wait for a settled table now also waits for
`resolving` to clear (one condition each, `tests/playtest_expo.mjs` and
`tests/playtest_expo_party.mjs`). That edit passes a syntax check and has not been run. The
timer path itself is tested through real sockets
(`test_real_phones_are_held_after_a_trick_and_released_by_the_servers_own_timer`).

| Check | Result (Windows 11) |
|---|---|
| `pytest tests/test_expo_events.py` | 77 passed (72 before the review repairs) |
| twenty-two faults put into the engine and the adapter, one at a time (the author's claim: done by hand, the faults and the script are not in the repository) | each caught by `tests/test_expo_events.py` |
| the reviewer's figures above (reported by the independent reviewer, also not in the repository) | as stated there |
| `tests/playtest_expo.mjs` with 3 and 2 humans, `tests/playtest_expo_party.mjs` (run by the orchestrator at 84e179b, not by the author) | PASS each |
| a snapshot written by this build, read by the build before it (and the reverse) | restored and played on, both ways |
| `pytest tests/test_expo.py tests/test_expo_*.py` (every EXPO test file) | 1113 passed, 2 skipped (distress with two players, C11), 2 expected failures (E-D2, E-D8) at 84e179b; the review repairs add five tests |
| `ops/check_docs.py`, `ops/check_static.sh`, `tests/test_no_private_data.py`, catalog export check | OK |
| `pytest -q` (whole repository), the cross-repository tests, the two browser playtests, a real phone | not run for this change |
| after the owner decision of 2026-10-05, on `main` at 9f9aa41 merged in: `pytest tests/test_expo.py tests/test_expo_*.py` | 1168 passed, 2 skipped, 2 expected failures; `tests/test_expo_events.py` 100 passed (with the early-timer repair and its two tests); the four checks of the row above OK; browser playtests and the whole repository not run |
