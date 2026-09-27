# Ad Ops Approval Gate: one-page summary

In advertising operations, a client request becomes a media plan, ad copy and a policy check, and a manager approves before any budget is committed. AI agents can draft that package quickly. The harder part is making sure nothing acts without a real sign-off, and nothing acts twice.

This project is an AI-workflow architecture prototype built around that sign-off. A LangGraph workflow routes the request through specialist agents, then **stops at an approval gate**. A simulated action runs only after an approver accepts the exact version they reviewed, and the pause survives server restarts. In the tests, double clicks, outdated versions and crashes near the action did not produce a second or unapproved action in the local simulated ledger.

By default the agents' drafts come from deterministic rules, so the whole workflow runs offline with no API key. An optional live LLM provider is wired in but has not been evaluated.

## Example

1. A requester asks: *"Plan a year-end campaign for Harbourlight Hotel with a S$80,000 budget."*
2. Four agents (insight → strategy → creative → compliance) draft the plan, saving progress after each step.
3. The result is a proposal with an id, a revision number and a fingerprint (sha256). The run pauses; nothing has executed.
4. A different person with the approver role approves that revision, and exactly one simulated action is recorded.
5. Ad copy that breaks a policy rule (for example "best harbour view") is blocked until the proposal is revised.

![Proposal waiting for approval](screenshots/01-awaiting-approval.png)

| One simulated action after approval | Crash recovered without a duplicate |
|---|---|
| ![approved](screenshots/03-approved-simulated-action.png) | ![recovered](screenshots/11-recovered-replay-detected.png) |

## Capabilities

- Multi-agent planning with validated steps and structured outputs
- Durable human approval with role checks and version pinning
- Failure handling: timeouts, bounded retries, recovery from saved progress, safe cancellation
- Policy lookup with cited source excerpts, abstention and conflict reporting
- Web UI with live status, decision history, CSV/JSON export and a mobile layout

## Technology

Python · FastAPI · LangGraph (SQLite checkpointer) · SQLite · React + Vite + Tailwind · pytest · Playwright/Chromium · GitHub Actions

## Try it

Run `./scripts/start.sh` and open http://127.0.0.1:8000. No API key is needed. The 3-minute walkthrough is in [DEMO_SCRIPT.md](DEMO_SCRIPT.md); the screenshots are in [screenshots/](screenshots/).

## Validation

- 114 automated backend tests pass; 1 optional live-LLM test is skipped without an API key.
- 16/16 browser checks against a real server process, including killing and restarting it.
- 13 defects in the original prototype were reproduced and each fixed with a test ([DEFECT_LOG.md](DEFECT_LOG.md)).
- Policy-lookup method, frozen held-out results and later regression checks: [EVALUATION.md](EVALUATION.md).

## Scope and limits

- The ad platform, clients, campaign figures and policies are fictional or mock data; the regulation and platform-policy notes are unverified summaries of public sources. No real integration, no spend.
- Demo roles are not a login; the app is meant to run locally as a single process.
- Drafts come from deterministic rules by default; the optional live LLM has not been run or evaluated.
- Policy lookup is keyword-based and returns excerpts for human review.
- Tests are developer-run in a Linux container; macOS is untested.
