# Run and recovery runbook (SOP)

All commands run from the repository root. Default mode is the deterministic demo provider: no API key, no network after installing dependencies. Data lives in `./data/` (`adops.db` = application store, `checkpoints.db` = LangGraph checkpoints). **Starting, stopping and restarting never delete data.**

## 1. Start on a Mac

Prerequisites: Python 3.11+ (3.12 recommended), Node.js 20+.

```bash
brew install python@3.12 node@20        # skip what you already have
git clone https://github.com/herui03/ad-ops-multi-agent.git
cd ad-ops-multi-agent
git checkout claude/wonderful-cerf-efuysu   # until the PR is merged into main
PYTHON=python3.12 ./scripts/start.sh
```

Then open http://127.0.0.1:8000. The script creates `.venv`, installs `requirements.txt`, builds the UI once if `frontend/dist` is missing, and serves API and UI on one port bound to localhost.

This script was run on Linux in the development container. It was not run on a Mac by Claude. If a Mac step fails, run the equivalent manual steps:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
(cd frontend && npm ci && npm run build)
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

UI development with hot reload: run uvicorn as above plus `cd frontend && npm run dev` (http://localhost:5173; `/api` and `/ws` are proxied).

## 2. Quick checks

```bash
pytest -q -rs                    # offline suite; tests/live is SKIPPED (reported NOT RUN) without GROQ_API_KEY
python scripts/demo_cli.py       # whole flow in the terminal, prints every durable id
python scripts/run_eval.py --cases eval/heldout_r5_cases.jsonl --out /tmp/eval-r5   # round-5 held-out grounding eval
NODE_PATH=$(npm root -g) PYTHON=.venv/bin/python node e2e/run_e2e.mjs   # needs playwright + Chromium; build the UI first
```

## 3. Optional live provider

```bash
export LLM_PROVIDER=groq GROQ_API_KEY=...    # never commit keys; .env is git-ignored
./scripts/start.sh
pytest tests/live -m live -rs
```

The UI badge switches to **LIVE provider**. Demo fault injection is refused in live mode. Live runs still stop at the gate and still write only to the simulated ledger. Nothing in this repository has been run against the live provider, and no live results are claimed.

## 4. Operating the approval gate

| Situation | What you see | What to do |
|---|---|---|
| Run shows `awaiting approval` | Proposal card with revision, id, sha256, gate policy | As **Approver (bob)**: Approve, Reject, or *Request a revision*. The requester (alice) cannot decide her own run. |
| Proposal shows **Blocked** | Red policy box: blocking compliance finding, or amount over the hard cap | Approve is refused (422). Revise: remove the flagged creative or lower the budget, then approve the new revision. |
| `409 stale_revision` | Someone revised in the meantime | Reload; decide on the current revision. |
| `409 run_not_awaiting_approval` | Someone else already decided | Nothing to do. The decision history shows who decided and when. |
| Double click / network retry | Same idempotency key | The server replays the first response; no second action. |

## 5. Failure and recovery

| Status | Meaning | Action |
|---|---|---|
| `failed` + `retryable` | A step exhausted its attempts (timeout, provider error, malformed or wrong-schema output) or the plan was invalid. The failed step and its error code are shown. | As approver: **Recover from checkpoint**. Completed steps are not re-run. Limit: `MAX_RECOVERIES` (default 3). |
| `failed`, not retryable | Recovery limit reached, or a non-retryable error such as `decision_mismatch` | Cancel the run and submit a new request. Inspect the event history / export. |
| `interrupted` | The server restarted while the run was queued, running or resuming (`restart_detected` event, with the checkpoint's next node) | Recover. If a decision was recorded before the crash, Recover re-applies it. If the ledger row already exists, you'll see "replay detected" and no second action. |
| `awaiting approval` after a restart | Normal. The checkpoint still holds the interrupt. | Decide as usual. |

Recovery drill (demo mode only). It kills the server once, right after the ledger commit:

```bash
DEMO_CRASH_POINT=after_commit ./scripts/start.sh   # approve any pending run -> process exits (code 70)
./scripts/start.sh                                 # restart without the variable
# UI: the run shows "interrupted" -> Recover -> completed, with "Replay detected ... not re-executed"
```

A marker file `data/.crash_drill_fired` stops the drill from firing twice. Delete it to repeat.

## 6. Cancel

* Awaiting approval: recorded as a `cancel` decision on the current revision. The graph resumes into its `cancelled` branch.
* Queued or running: cooperative. The flag is checked before each step. Status becomes `cancelled` without a proposal.
* Queued or running, and the graph reaches the gate before noticing: the accepted cancel is honoured there. A system cancel decision is recorded; the run ends `cancelled` and never shows as awaiting approval.
* Failed or interrupted, no action committed: becomes `cancelled` immediately. Any recorded but unexecuted approve is voided.
* Failed or interrupted, **a simulated action already committed** (e.g. crash right after the ledger commit): `409 action_already_committed`. Use **Recover** to reconcile the run to `completed`; it cannot be cancelled as if nothing happened.
* While a decision is being applied (`resuming`): `409 run_busy`.
* Repeating a cancel returns `already_cancelled`. A later approve returns `409`, and the run stays cancelled.
* Two people pressing Recover at once: one claim wins; the other gets `409`.

## 7. Exports and audit

`Export JSON` gives the full run: events, steps, proposals, decisions, actions and checkpoint info. `Export CSV` gives one row per event, proposal, decision and action; cells starting with `= + - @` are prefixed with `'` so spreadsheets do not evaluate them. Both are served as attachments with `nosniff`.

## 8. Reset (explicit, separate)

Reset is never automatic. It refuses, and changes nothing, in any of these cases:

* the backend is running: a shared lifetime lock sits next to the data directory at `.<name>.adops.lock`, and reset needs it exclusively;
* the target is the filesystem root, your home directory, the source checkout, or any repository path other than `./data`;
* the target lacks the app's `.adops-data-marker`, or contains anything other than the app's databases, WAL/SHM files and markers.

Aliases (symlinks, `..`) are resolved first. Archives get a unique name down to the microsecond, plus a random suffix, and never nest or overwrite. Linux is tested; macOS is untested.

```bash
python scripts/reset_demo_data.py                     # refuses without --confirm
python scripts/reset_demo_data.py --confirm           # renames ./data to a unique ./data-archive-<UTC µs>-<random>/ (history kept)
python scripts/reset_demo_data.py --confirm --delete  # permanent delete
```

## 9. Things this runbook does not cover

There is no deployment, authentication, multi-worker setup or real ad-platform integration. Keep the server on `127.0.0.1`: the demo roles are not a security boundary.
