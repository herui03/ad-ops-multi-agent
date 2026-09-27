"""R5-04: scripts/reset_demo_data.py must be safe against a running server and against wrong targets.

Safety rule for these tests: every reset that could move or delete anything targets ONLY directories
created inside pytest's tmp_path. Root, home and repository refusals are checked by calling the pure
validation function; reset is never invoked on those paths.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.agents.orchestrator import WorkflowRunner
from backend.config import Settings

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "reset_demo_data.py"


def snapshot(d: Path) -> dict[str, str]:
    out = {}
    for p in sorted(d.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(d))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def reset(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT, timeout=60)


def make_data_dir(parent: Path, name: str = "data") -> Path:
    """A real demo data dir created by the app itself (stopped afterwards)."""
    d = parent / name
    r = WorkflowRunner(Settings(data_dir=d, _env_file=None))
    run = r.create_run("Plan a campaign for Harbourlight Hotel with a S$10,000 budget", actor="alice", role="requester")
    r.wait(run["run_id"])
    r.close()
    return d


def siblings(parent: Path) -> set[str]:
    return {p.name for p in parent.iterdir()}


def test_r5_04_reset_refuses_while_server_running_and_changes_nothing(tmp_path):
    d = make_data_dir(tmp_path)
    server = WorkflowRunner(Settings(data_dir=d, _env_file=None))   # a live server holds the data dir
    try:
        run = server.create_run("Plan a campaign for Harbourlight Hotel with a S$12,000 budget", actor="alice",
                                role="requester")
        server.wait(run["run_id"])
        before, names_before = snapshot(d), siblings(tmp_path)
        r = reset("--confirm", "--data-dir", str(d))
        assert r.returncode != 0, f"reset ran while the server was live: {r.stdout}{r.stderr}"
        assert "running" in (r.stdout + r.stderr).lower()
        assert d.is_dir() and snapshot(d) == before and siblings(tmp_path) == names_before
        # the live server still works on the untouched files
        assert server.store.get_run(run["run_id"])["status"] == "awaiting_approval"
    finally:
        server.close()


def test_r5_04_reset_refuses_running_server_via_symlink_alias(tmp_path):
    d = make_data_dir(tmp_path)
    alias = tmp_path / "alias-to-data"
    alias.symlink_to(d, target_is_directory=True)
    (tmp_path / "x").mkdir()          # so that x/../data is a real alternate spelling
    server = WorkflowRunner(Settings(data_dir=d, _env_file=None))
    try:
        before, names_before = snapshot(d), siblings(tmp_path)
        for spelling in (str(alias), str(tmp_path / "." / "data"), str(tmp_path / "x" / ".." / "data")):
            r = reset("--confirm", "--data-dir", spelling)
            assert r.returncode != 0, f"{spelling}: {r.stdout}{r.stderr}"
        assert snapshot(d) == before and siblings(tmp_path) == names_before
    finally:
        server.close()


def test_r5_04_stopped_reset_archives_uniquely_and_keeps_data(tmp_path):
    d = make_data_dir(tmp_path)
    before = snapshot(d)
    r = reset("--confirm", "--data-dir", str(d))
    assert r.returncode == 0, r.stdout + r.stderr
    archives = [p for p in tmp_path.iterdir() if p.name.startswith("data-archive-")]
    assert len(archives) == 1 and not d.exists()
    assert snapshot(archives[0]) == before          # history preserved byte-for-byte


def load_script_module():
    spec = importlib.util.spec_from_file_location("reset_demo_data_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r5_04_same_second_archives_never_nest_or_overwrite(tmp_path, monkeypatch):
    mod = load_script_module()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mod, "datetime", FrozenDatetime)
    first = make_data_dir(tmp_path)
    first_snapshot = snapshot(first)
    monkeypatch.setattr(sys, "argv", ["reset", "--confirm", "--data-dir", str(first)])
    assert mod.main() == 0
    second = make_data_dir(tmp_path)
    second_snapshot = snapshot(second)
    assert second_snapshot != first_snapshot
    monkeypatch.setattr(sys, "argv", ["reset", "--confirm", "--data-dir", str(second)])
    assert mod.main() == 0
    archives = sorted(p for p in tmp_path.iterdir() if p.name.startswith("data-archive-"))
    assert len(archives) == 2, f"archives: {[a.name for a in archives]}"
    for a in archives:
        assert not any(c.name.startswith("data") and c.is_dir() for c in a.iterdir()), f"nested archive in {a.name}"
    assert {tuple(sorted(snapshot(a).items())) for a in archives} == \
        {tuple(sorted(first_snapshot.items())), tuple(sorted(second_snapshot.items()))}


@pytest.mark.parametrize("extra", ["--confirm", "--confirm --delete"])
def test_r5_04_refuses_unrelated_directory(tmp_path, extra):
    unrelated = tmp_path / "my-notes"
    unrelated.mkdir()
    (unrelated / "thesis.docx").write_bytes(b"not demo data")
    (unrelated / "adops.db").write_bytes(b"a file that merely has the expected name")
    before, names_before = snapshot(unrelated), siblings(tmp_path)
    r = reset(*extra.split(), "--data-dir", str(unrelated))
    assert r.returncode != 0, r.stdout + r.stderr
    assert snapshot(unrelated) == before and siblings(tmp_path) == names_before


def test_r5_04_refuses_directory_with_unexpected_content_even_if_marked(tmp_path):
    d = make_data_dir(tmp_path)
    (d / "someone-elses-file.txt").write_text("keep me")
    before = snapshot(d)
    r = reset("--confirm", "--delete", "--data-dir", str(d))
    assert r.returncode != 0 and snapshot(d) == before


def test_r5_04_refuses_a_source_checkout(tmp_path):
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / ".git").mkdir(parents=True)
    (fake_repo / "README.md").write_text("x")
    before = snapshot(fake_repo)
    r = reset("--confirm", "--data-dir", str(fake_repo))
    assert r.returncode != 0 and snapshot(fake_repo) == before


def test_r5_04_validation_refuses_root_home_and_repo_without_touching_them():
    """Pure function only: reset is never invoked on these paths."""
    mod = load_script_module()
    for target in (Path("/"), Path.home(), ROOT, ROOT / "backend", ROOT / "docs", ROOT.parent):
        reason = mod.validate_target(target)
        assert reason, f"{target} was not refused"


def test_r5_04_server_start_refused_while_reset_holds_exclusive_lock(tmp_path):
    from backend.datalock import DataDirBusy, DataDirLock
    d = make_data_dir(tmp_path)
    lock = DataDirLock(d, exclusive=True)
    try:
        with pytest.raises(DataDirBusy):
            WorkflowRunner(Settings(data_dir=d, _env_file=None))
    finally:
        lock.release()
    WorkflowRunner(Settings(data_dir=d, _env_file=None)).close()
