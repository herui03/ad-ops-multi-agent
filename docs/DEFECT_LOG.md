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
| C5 | Held-out eval, first run | Grounding misses: S4 (wrong chunk ranked first → abstained), **U5 (answered an unanswerable question with an irrelevant CAP-code quote)**, C4 (missed a tagged conflict), I4 (injected text in the question diluted matching → abstained) | **Open.** Not tuned away; see EVALUATION.md |
| C6 | E2E re-run from a clean export of `d92a676` (13/14) | Test-harness race: the first check read the mode badge before `/api/meta` returned, so it saw the placeholder "…" | Fixed: the check waits for the badge text. The E2E was re-run 3 times afterwards (see ACCEPTANCE.md) |
| C7 | Design review | A timed-out provider call cannot be killed in Python | Documented limitation; the live provider's HTTP timeout ends the call |

## Not independently verified

Earlier commits in this repository are authored by the `herui03` account. This log does not verify who wrote them. Nothing here was reviewed by an external stakeholder: developer tests are not user acceptance testing.
