# Defect log

**Roles.** Herui directs the project. Claude implemented and tested the changes in this PR. Codex independently reviewed the baseline source; Herui passed those findings on in the task brief.

**Evidence rule.** A defect counts as *reproduced* only when an executable check shows it on the baseline code. A defect counts as *fixed* only when a test on the new code shows the corrected behaviour.

Baseline = `main` at `5ac2c35eb61ff21746ab9252eeddffe3aeefad3a`. Reproduction: `scripts/repro_baseline_defects.py`, run against a worktree of that commit with Groq replaced by a scripted stub. Output is in [`evidence/baseline-defects.txt`](evidence/baseline-defects.txt): **13/13 reproduced**.

## Baseline defects (reported by Codex source review; reproduced by Claude)

| ID | Defect (baseline behaviour) | Reproduction output | Fix | Proof on new code |
|---|---|---|---|---|
| D1 | `POST /api/approvals/{id}/decide` returned `200 "Decision recorded"` for an id that does not exist, without resuming anything and with no run or revision scope | `status=200 ... 'Decision recorded'` | Endpoint retired (410). Decisions go to `/api/runs/{run_id}/decisions` with proposal id, revision, sha256 and an idempotency key, validated in one transaction | `test_retired_endpoints_are_closed_and_change_nothing`, `test_ac6_*`, `test_ac4_*` |
| D2 | WebSocket `approval_decision` was a second, unvalidated approval path | `ws reply={'type': 'approval_resolved', ...}` | WebSocket is read-only; commands get `unsupported_message` | `test_websocket_is_read_only_and_validates_input` |
| D2b | Malformed JSON over the WebSocket crashed the handler | `JSONDecodeError` | Size limit, JSON and shape validation; errors are returned as messages | same test |
| D3 | A "pending" approval was not a pause: the graph synthesized the final brief in the same call | `pending=1 final_message_prefix='FINAL BRIEF'` | `interrupt()` at `approval_gate` with SqliteSaver; the action runs only after a recorded approve | `test_ac1_gate_holds_action_at_zero_until_exact_approval` |
| D4 | Planner `requires_human_approval=true` could yield zero approvals and still finalize | `pending=[] finalized='FINAL BRIEF'` | The gate is code policy by workflow type (`policy.GATED_WORKFLOWS`); model flags are ignored | `test_planner_llm_flag_is_not_the_gate`, `test_ac12_injection_in_request_and_planner_output_cannot_bypass_gate` |
| D5 | `_group_by_phase` failed open: cycles and dangling dependencies executed every step | `cycle phases=[['strategy','creative']]` | `contracts.Plan` validates a bounded DAG and fails closed | `test_invalid_plan_dag_fails_closed_without_execution[*]` (7 cases) |
| D6 | A failed agent was reported to the UI as `completed`, and synthesis continued | `ui statuses=['running','completed'] trace_success=False` | A failure raises `StepFailed`; status `failed` with code; dependents never run; no proposal | `test_ac8_persistent_fault_fails_bounded_and_honest[*]` |
| D7 | Malformed planner JSON silently ran an unapproved `insight` task | `agents executed=['insight']` | Bounded retries, then `failed` / `malformed_output`; nothing runs | `test_planner_failure_does_not_fall_back_to_unapproved_work` |
| D8 | Invalid agent JSON (`_parse_error`) counted as success | `success=True output_keys=['_parse_error','raw_response']` | Per-agent strict contracts plus semantic checks | `test_agent_malformed_or_wrong_schema_is_failure_not_success[*]` |
| D8b | Valid JSON of the wrong shape (a list) counted as success | `success=True output=['a','list',...]` | as D8 | same |
| D9 | Dashboard numbers were constants (12 campaigns, 48 clients, 2,850,000 spend, ROAS 2.8, 3 pending) | `stats={... 12, 48, 2850000, 2.8, 3}` | Aggregates are read from the store and labelled simulated | `test_dashboard_counts_come_from_the_store` (after approve, reject, restart and cancel) |
| D10 | Graph compiled without a checkpointer: nothing to resume after a restart | `graph.checkpointer=None` | `SqliteSaver`, stable `thread_id`, `durability="sync"` | `test_ac2_restart_while_pending_then_exact_approval_resumes_same_run` |
| D11 | `approval_decisions` was declared and never read | 2 occurrences (declare + init) | Decisions are durable rows that drive `Command(resume=...)` | `test_ac10_crash_after_decision_recorded_before_graph_resume` |

## Content and claims

| ID | Issue | Reported by | Fix |
|---|---|---|---|
| A1 | Mock placement labels ("Moments Feed", "Channels Feed", "Official Account Banner", "Mini Programs"), a green brand colour, and a "super-app with 1B+ MAU" prompt claim could imply affiliation with a real platform. The MAU figure had no source in the repo. | Claude (earlier README pass in this session); requirement restated in Herui's brief | Replaced with neutral generic placements, the fictional "SimAds sandbox", fictional clients (Harbourlight Hotel, NovaByte) and a neutral palette. Held-out case U4 checks the system abstains on the MAU question. |
| A2 | The baseline README said the workflow "pauses for approval". It did not (D3). | Claude (commit `37d9338`) | Corrected then; now true and tested. |
| A3 | Regulation and platform summaries could read as authoritative | Herui's brief | Every corpus document carries `kind` (fictional-policy / fictional-brand / unverified-summary / unverified-vendor-note) and `trust`; the UI and answers show them. |

## Found by Claude during implementation

| ID | Found by | Defect | Status |
|---|---|---|---|
| C1 | `test_ac14_full_demo_runs_without_key_or_network` | The demo planner treated "Who must approve a campaign launch?" as work, because the words *campaign* and *launch* matched | Fixed: questions are classified by form; only imperative or "can you …" requests count as work |
| C2 | First E2E run (8 of 14 checks failed) | Test-harness bug: `submit()` read the previous `?run=` from the URL, so checks ran against the wrong run. The UI itself was correct (screenshots showed the right states). | Fixed in `e2e/run_e2e.mjs`: wait for a new run id |
| C3 | E2E console check | Browser logs deliberate 403/422 refusals and connection errors during a deliberate server crash as console errors | Classified by window (deliberate negative step / server down). Unexpected errors: 0 of 9 logged |
| C4 | Screenshot review (390 px) | On mobile the selected run and its approval card were below the full runs list | Fixed: the run detail is ordered first on small screens (`21-mobile-approved.png`) |
| C5 | Held-out eval, first run | Grounding misses: S4 (wrong chunk ranked first → abstained), **U5 (answered an unanswerable question with an irrelevant CAP-code quote)**, C4 (missed a tagged conflict), I4 (injected text in the question diluted matching → abstained) | Was open at `c149c38`; addressed in review round 5 (R5-03 below). The frozen 19/23 report is kept unchanged. |
| C6 | E2E re-run from a clean export of `d92a676` (13/14) | Test-harness race: the first check read the mode badge before `/api/meta` returned, so it saw the placeholder "…" | Fixed: the check waits for the badge text. The E2E was re-run 3 times afterwards (see ACCEPTANCE.md) |
| C7 | Design review | A timed-out provider call cannot be killed in Python | Documented limitation; the live provider's HTTP timeout ends the call |

## Review round 5: Codex review of `c149c38`

Codex reviewed the pushed source and reported candidates R5-01 to R5-03. Claude wrote race tests with deterministic barriers (threading Events and Barriers placed at exact code points, no sleeps) in `tests/test_review_r5.py`. Claude ran the same file against the **old** code first:

* Old code: **8 failed, 2 passed** — [evidence/review-r5-old-c149c38.txt](evidence/review-r5-old-c149c38.txt). The 2 that passed are guard tests for behaviour that was already correct and must stay so.
* Fixed code: **10/10 passed**, plus 25 repeated runs with no failures — [evidence/review-r5-fixed.txt](evidence/review-r5-fixed.txt).

| ID | Old behaviour at `c149c38` (reproduced) | Fix | Test |
|---|---|---|---|
| R5-01a | A cancel accepted while the planner was running still ended the question run as `completed` | Terminal writes go through `Store.finish`, which ends the run `cancelled` if a cancel was accepted first. Cancel and finish serialize on the write lock | `test_r5_01_cancel_during_question_planner_is_not_completed` |
| R5-01b | Same for the last step of a deliverable-only (pitch) run | same | `test_r5_01_cancel_during_last_step_of_deliverable_is_not_completed` |
| R5-01c | **A cancel accepted between `build_proposal` and `interrupt()` left the run `awaiting_approval` with `cancel_requested=1`; a later approve then EXECUTED the simulated action** (probe in the old-code evidence: `approve after accepted cancel: 200 status completed simulated actions 1`) | `Store.settle_gate`: when the graph pauses and a cancel was accepted, record a system `cancel` decision and resume into the cancel branch; the run never shows as awaiting approval | `test_r5_01_cancel_between_proposal_and_interrupt_never_executes` |
| R5-01d | The simulator did not re-check the run's state | Inside the ledger transaction the simulator refuses unless the run is `resuming` or `running` without an accepted cancel (`run_cancelled` / `gate_violation`) | `test_r5_01_simulator_refuses_a_cancelled_run` |
| R5-01e | After a crash after the commit (run `interrupted`), cancel returned 200 and marked the run `cancelled`, hiding a committed action | Cancel refuses with `409 action_already_committed` (listing the action ids); Recover reconciles instead. Cancelling a run with a recorded but unexecuted approve voids the proposal and records that | `test_r5_01_cancel_after_committed_action_is_refused_not_hidden`, `test_r5_01_cancel_after_recorded_but_unexecuted_approve_stays_cancelled`; E2E check "cancel refused once a simulated action is committed" |
| R5-02a | Two concurrent Recover calls on a failed run both returned 202; `Store.transition` let the second through because current == target, so the same `recover_count` scheduled duplicate work | `Store.claim_recovery` checks eligibility and bumps `recover_count` in one write transaction; the second caller gets 409 | `test_r5_02_concurrent_recover_claims_once` |
| R5-02b | `transition` accepted current == target for any caller (invalid transitions passed silently) | Strict by default; `idempotent=True` only for the graph's own replayable terminal writes | `test_r5_02_transition_is_strict_unless_marked_idempotent` |
| R5-02c | Recovering a run whose checkpoint had already finished returned early and left it `running` | `_reconcile_finished` derives the terminal status from the checkpoint and the ledger, or fails explicitly with `inconsistent_state` | `test_r5_02_recover_on_finished_checkpoint_does_not_leave_run_running` |
| R5-03 | Grounding shipped U5 (unrelated confident answer) and C4 (missed conflict) as documented failures | General guards, none keyed to case ids or wording: (1) the **quoted sentences** must contain ≥30% of the question's terms, not just the chunk or heading; otherwise abstain and show `candidate_evidence` labelled "not an answer"; (2) topic conflicts are checked across the **whole corpus**, not only retrieved chunks; (3) instruction-like sentences in the question are ignored and reported. The frozen 19/23 report stays; the 23 cases are now a **regression** set (22/23). **New** held-out cases written after freezing the answerer: **21/24**, including one remaining unsupported answer (N-U7) | `test_r5_03_*`; [EVALUATION.md](EVALUATION.md) |

## Not independently verified

Earlier commits in this repository are authored by the `herui03` account. This log does not verify who wrote them. Nothing here was reviewed by an external stakeholder: developer tests are not user acceptance testing.
