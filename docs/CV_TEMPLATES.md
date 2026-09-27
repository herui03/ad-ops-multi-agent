# CV bullet templates (conditional)

**Use a bullet only if all of these are true:**

1. You can explain the mechanism in your own words: see the 15 questions in `INTERVIEW_GUIDE_zh.md`.
2. You have personally reproduced the numbers on your own machine: `pytest -q -rs`, `python scripts/run_eval.py`, and the E2E run or at least the demo in `DEMO_SCRIPT.md`.
3. The wording states the collaboration honestly. Herui directed the project; Claude (an AI coding assistant) implemented and tested it; Codex reviewed the source. If you did not write the code, do not say you did.

Do not add numbers that are not in `docs/ACCEPTANCE.md` or `docs/EVALUATION.md`. Do not call it a production system or a client or employer deployment. Do not call the developer tests user acceptance.

## Templates

**Project line**
> Ad Ops Approval Gate: portfolio prototype of a simulated advertising-operations workflow (LangGraph, FastAPI, React, SQLite). github.com/herui03/ad-ops-multi-agent

**Bullets.** Pick 2–3 and fill the brackets truthfully:

- [Directed / Specified and reviewed] the rebuild of a multi-agent ad-ops prototype around a durable human approval gate: LangGraph `interrupt()` with a SQLite checkpointer. Simulated actions run only after an approver decision on the exact proposal revision and hash, and pending runs survive process restarts.
- [Specified / Reviewed] reliability controls: atomic, idempotent decisions (concurrent clicks and duplicate keys produce one action); stale-revision and cross-run rejection; bounded retries and timeouts; explicit failure, cancel and recovery paths. Covered by 96 automated tests (including barrier-forced cancel and recovery races) and a 16-check Chromium E2E run that kills and restarts the real server.
- [Reproduced and documented] 13 defects in the original prototype (non-pausing approvals, a WebSocket approval bypass, a fail-open plan DAG, parse errors counted as success, hard-coded dashboard numbers) with an executable reproduction script, each mapped to a fixing test.
- [Designed / Evaluated] an extractive retrieval layer with hash-verifiable citations, abstention, conflict reporting and prompt-injection exclusion. Held-out evaluation: 19/23 in round 1; after conservative support and conflict guards, 21/24 on newly written held-out cases, with the remaining unsafe answer documented. No language-model quality is claimed.

**If asked "what was your part?"** Answer precisely. For example: "I defined the requirements and acceptance cases and reviewed the results. An AI assistant wrote the code under my direction, a second AI tool reviewed it independently, and I reproduced the tests myself." Use this only if it is true.

## Chinese version (中文简历条目模板，同样有条件)

- [主导/定义并验收] 将多智能体广告运营原型重构为可靠的人工审批流程：LangGraph `interrupt()` + SQLite checkpointer。只有审批人对具体修订版和哈希做出批准后，才会执行模拟动作；待审批的 run 可以跨进程重启恢复。
- [定义/审阅] 可靠性机制：原子、幂等的审批（并发点击和重复键只产生一个动作）、过期修订和跨 run 拒绝、有上限的重试和超时、显式的失败、取消和恢复路径。由 96 个自动化测试（包括用 barrier 强制复现的取消和恢复竞态）和 16 项 Chromium 端到端检查覆盖。
- [复现并记录] 原型中的 13 个缺陷，写了可执行的复现脚本，每个缺陷都对应一个修复测试。
- [设计/评估] 带哈希可验证引用的抽取式检索，支持拒答、冲突报告和注入排除；第一轮自建 held-out 19/23；加上保守的支持度和冲突护栏后，新写的 held-out 用例 21/24，剩下的不安全失败如实记录；未评估 LLM 质量。
