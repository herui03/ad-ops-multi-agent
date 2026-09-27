# Acceptance results

All results come from runs by Claude in the development container on 2026-09-27.

| Suite | Command | Result | Evidence |
|---|---|---|---|
| Backend tests | `python -m pytest -v -rs` (Python 3.12.3, clean venv) | **96 passed, 1 skipped** | [evidence/pytest-py312.txt](evidence/pytest-py312.txt) |
| Browser E2E | `node e2e/run_e2e.mjs` (real uvicorn process, Chromium) | **16/16 checks in 3 consecutive runs** after review round 5 (before that: 14/14; one earlier run was 13/14 because of a harness race, since fixed; see DEFECT_LOG C6 and [repeat-runs.txt](evidence/e2e/repeat-runs.txt)) | [evidence/e2e/results.json](evidence/e2e/results.json), [screenshots](screenshots/), [recorded replay](replay/index.html) |
| Grounding eval | `python scripts/run_eval.py` | Round 1: **19/23** held-out (frozen). Round 5: **21/24** on new held-out cases written after freezing the answerer ([report](evidence/eval-heldout-r5-first-run.md)); round-1 set as regression 22/23 |
| Review round 5 | `pytest tests/test_review_r5.py` on old `c149c38` and on the fix | old **8 failed / 2 passed**, fixed **10/10**; 25 repeats with 0 failures | [old](evidence/review-r5-old-c149c38.txt), [fixed](evidence/review-r5-fixed.txt) | [evidence/eval-heldout.md](evidence/eval-heldout.md) |
| Repeatability | 25 repeated runs of the concurrency, restart and cancel tests | 0 failing runs | [evidence/stress-repeat.txt](evidence/stress-repeat.txt) |

The one skipped test is the live-provider test. It reports **NOT RUN: GROQ_API_KEY not set**. No live language-model behaviour was tested, and nothing here is a model-quality or accuracy figure.

These are developer tests. They are not user acceptance testing by any stakeholder.

| # | Acceptance case | Automated tests (tests/…) | Browser evidence | Result |
|---|---|---|---|---|
| 1 | Gate → action count 0 until the exact proposal is approved | `test_gate.py::test_ac1_gate_holds_action_at_zero_until_exact_approval`, `::test_simulator_refuses_without_recorded_approval` | E2E "gate pauses with zero actions" · `01-awaiting-approval.png` | pass |
| 2 | Pending → restart → exact approval → action 1, same run | `test_restart.py::test_ac2_restart_while_pending_then_exact_approval_resumes_same_run` | E2E "pending run survives process kill…" (SIGKILL of uvicorn) · `07`, `08` | pass |
| 3 | Reject → action 0, terminal | `test_gate.py::test_ac3_reject_is_terminal_and_executes_nothing` | E2E "reject is terminal" · `04-rejected.png` | pass |
| 4 | Duplicate decision executes once; conflicting replay rejected; concurrent clicks | `test_gate.py::test_ac4_duplicate_same_key_replays_and_conflicting_payload_rejected`, `::test_ac4_concurrent_clicks_execute_once` (8 threads), `::test_ac4_concurrent_same_key_double_submit` (6 threads) | E2E double-click approve → 1 decision, 1 action · `03` | pass |
| 5 | Revise → stale approval fails | `test_gate.py::test_ac5_revise_makes_old_revision_stale`, `::test_ac5_blocking_compliance_cannot_be_approved_until_revised`, `::test_hard_budget_cap_is_a_blocker` | E2E "blocked proposal refused, revision 2 approved" · `05`, `06` | pass |
| 6 | Cross-run / unknown ids fail without changing either run | `test_gate.py::test_ac6_cross_run_and_unknown_ids_fail_without_side_effects` | — | pass |
| 7 | Invalid demo role denied server-side | `test_gate.py::test_ac7_roles_enforced_server_side` | E2E "wrong demo role is refused by the server" · `02-role-denied.png` | pass |
| 8 | Timeout / malformed / wrong schema / provider failure → bounded, honest error; recovery | `test_faults.py::test_ac8_persistent_fault_fails_bounded_and_honest[timeout,provider_error,malformed_json,wrong_schema]`, `::test_ac8_recover_after_failure_repeats_only_the_failed_step`, `::test_transient_fault_is_retried_within_budget`, `::test_agent_malformed_or_wrong_schema_is_failure_not_success[*]`, `::test_provider_error_text_is_redacted`, `test_providers.py::*` | E2E "provider failure is explicit; recover resumes to the gate" · `12`, `13` | pass |
| 9 | Cancel, repeat cancel, late approve → stays cancelled | `test_gate.py::test_ac9_cancel_repeat_and_late_approve_stay_cancelled`, `::test_ac9_cancel_while_running_is_cooperative`, `test_review_r5.py::test_r5_01_*` (planner, last step, before-interrupt window, simulator recheck, committed action refused, unexecuted approve voided) | E2E "cancel refused once a simulated action is committed" · `10b` | pass |
| 10 | Crash near the action: replay protection / reconciliation boundary | `test_review_r5.py::test_r5_02_*` (concurrent Recover claims once; finished checkpoint reconciled), `test_restart.py::test_ac10_crash_after_commit_is_reconciled_not_reexecuted`, `::test_ac10_crash_before_commit_rolls_back_then_executes_once`, `::test_ac10_crash_after_decision_recorded_before_graph_resume`, `::test_crash_mid_agents_resumes_from_last_checkpoint_without_rerunning_done_steps` | E2E real process exit (code 70) after the ledger commit → interrupted → Recover → "replay detected", 1 action · `09`, `10`, `11` | pass (boundary and remaining risks: ARCHITECTURE.md) |
| 11 | Valid citations, abstention, conflicts | `test_grounding.py::test_ac11_dev_cases[*]`, `::test_r5_03_*`, `::test_corpus_integrity_and_labels`, `::test_answers_are_verbatim_quotes_only`, `::test_question_run_goes_through_workflow_and_is_labelled` | E2E "grounded answer / conflict / abstain" and "candidate evidence" · `14`, `15`, `16`, `16b` | pass on dev cases; new held-out **21/24** with one unsafe answer (N-U7), see EVALUATION.md |
| 12 | Source / request injection cannot bypass the gate | `test_gate.py::test_ac12_injection_in_request_and_planner_output_cannot_bypass_gate`, `::test_ac12_compliance_citing_injected_source_is_rejected`, `test_grounding.py::test_ac12_injected_source_is_excluded_from_evidence` | — | pass |
| 13 | Safe HTML / script / formula display and export | `test_api.py::test_ac13_user_text_is_stored_verbatim_and_exported_safely` | E2E "HTML/script shown as text, no dialog, CSV formula neutralised" · `17` | pass |
| 14 | No-key, no-network demo | `test_api.py::test_ac14_full_demo_runs_without_key_or_network` (socket connect patched to fail), `::test_live_provider_requires_key`, `::test_settings_never_expose_key` | whole E2E run in demo mode | pass |
| 15 | Gold labels excluded from production | `test_grounding.py::test_ac15_production_code_never_references_gold_labels`, `::test_ac15_answerer_does_not_open_eval_files_at_runtime`, `::test_eval_runner_reports_exact_denominators` | — | pass |
| 16 | Input / queue / retry limits | `test_faults.py::test_ac16_input_limits`, `::test_ac16_queue_limit_returns_429_and_releases_slots`, `::test_recovery_budget_is_bounded`, `::test_demo_fault_rejected_for_live_provider` | — | pass |

Additional checks:

- WebSocket: read-only, malformed input, reconnect reads persisted state, and a disconnect does not affect the run (`test_api.py::test_websocket_*`).
- Durable history survives a restart (`test_restart.py::test_durable_history_survives_restart`).
- Mobile at 390 px: no horizontal overflow on three screens, and approve works by tap (E2E, `19`–`21`).
- Console: 9 errors logged in total, all inside deliberate server-down or negative-test windows; 0 unexpected.
