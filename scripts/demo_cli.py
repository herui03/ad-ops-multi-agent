"""Terminal walkthrough of the whole flow in demo mode (no browser, no key, no network).

    python scripts/demo_cli.py            # uses a throwaway data dir under ./data/cli-demo
    python scripts/demo_cli.py --keep     # keep the data dir so you can inspect it afterwards

Prints each durable ID so you can match them against the API/UI.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.orchestrator import WorkflowRunner  # noqa: E402
from backend.config import ROOT, Settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    data = ROOT / "data" / "cli-demo"
    shutil.rmtree(data, ignore_errors=True)
    s = Settings(data_dir=data, llm_provider="demo", _env_file=None)
    r = WorkflowRunner(s)
    print(f"provider: {r.provider.label}\n")
    run = r.create_run("Plan a year-end campaign for Harbourlight Hotel with a S$80,000 budget",
                       actor="alice", role="requester")
    run = r.wait(run["run_id"])
    d = r.run_detail(run["run_id"])
    p = d["proposals"][-1]
    print(f"run {run['run_id']} (thread {run['thread_id']}) -> {run['status']}")
    print(f"proposal {p['proposal_id']} rev {p['revision']} sha256 {p['sha256'][:16]}... amount "
          f"{p['payload']['amount']:,.0f} SGD; approvable={p['payload']['policy']['approvable']}")
    print(f"checkpoint next nodes: {d['checkpoint']['next_nodes']}; simulated actions so far: {len(d['actions'])}\n")
    res = r.decide(run["run_id"], proposal_id=p["proposal_id"], revision=p["revision"], proposal_sha256=p["sha256"],
                   decision="approve", comment="approved in CLI demo", changes=None,
                   idempotency_key=f"cli-{uuid.uuid4().hex}", actor="bob", role="approver")
    print(f"approve -> {res['run']['status']}: {res['run']['result']['summary']}")
    q = r.wait(r.create_run("Who must approve a campaign launch?", actor="alice", role="requester")["run_id"])
    print(f"\nquestion run {q['run_id']} -> {q['result']['answer']['outcome']}: {q['result']['answer']['answer_text']}")
    r.close()
    if not args.keep:
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
