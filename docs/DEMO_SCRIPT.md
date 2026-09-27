# 3-minute demo script

**Setup (before the call).** Run `./scripts/start.sh`, open http://127.0.0.1:8000, and move old data aside with `python scripts/reset_demo_data.py --confirm`. Keep a second terminal ready to stop and start the server. Everything runs offline in demo mode.

| Time | Do | Say |
|---|---|---|
| 0:00 | Point at the amber **DEMO** badge and the banner | "This is a simulated ad-ops workflow: fictional clients, a sandbox ledger, no ad platform, no spend. The demo provider is deterministic rules, not a language model; that makes the reliability behaviour reproducible." |
| 0:15 | As **Requester (alice)**, click *Campaign (approvable)* → Submit | "The planner's output is validated as a DAG before anything runs. Four agents run one checkpointed step at a time." |
| 0:35 | Show the proposal card: revision, id, sha256, and **checkpoint next = approval_gate** | "This is a real pause. LangGraph's `interrupt()` is holding the run in a SQLite checkpoint. Nothing is waiting in memory, and the action count is zero." |
| 0:50 | Still as alice, click **Approve** → red 403 | "Roles are enforced on the server. They are a demo dropdown, not a login, and the UI says so." |
| 1:00 | In the terminal, press **Ctrl+C** to stop the server, then start it again. The socket shows *reconnecting*, then *live* | "Restart while pending. Same run, same thread id, still awaiting approval." |
| 1:20 | Switch to **Approver (bob)** and double-click **Approve** | "The double click sends the same idempotency key, so the server replays the first response. One decision, one simulated action. The approval is tied to this exact revision and hash." |
| 1:40 | Click *Campaign with a blocked claim* → Submit → as bob, Approve → 422. Open *Request a revision*, remove `cr_b2`, send, then approve revision 2 | "A rule engine blocks 'best'. The finding cites a real corpus chunk with its hash. Approving revision 1 is now impossible: it's stale." |
| 2:10 | Click *Conflicting sources* → Submit | "Answers are verbatim quotes with resolvable citations. Here two fictional sources disagree, so it reports the conflict instead of picking one. It also abstains when evidence is thin." |
| 2:30 | Open the fault injection panel, choose *provider error* → Submit → failed → as bob, **Recover** | "Failures are bounded (two attempts) and honest: status failed, with an error code and nothing synthesized. Recover resumes from the last checkpoint without re-running finished steps." |
| 2:50 | Dashboard tab | "These counts come from the store, not constants. Limits: single process, demo roles aren't auth, lexical retrieval scored 19 of 23 on my held-out set, and there's no real ad integration." |

Optional crash drill (+1 min): start with `DEMO_CRASH_POINT=after_commit ./scripts/start.sh`, approve a pending run (the process exits), restart normally, then Recover. The UI shows "Replay detected … not re-executed", and the action count is still 1.
