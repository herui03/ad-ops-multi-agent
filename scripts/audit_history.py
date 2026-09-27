"""Secret / personal-data audit of the working tree history: every blob reachable from any ref.

Prints pattern names, match counts and file paths only, never the matched values. Binary files (e.g. PNG
screenshots) are skipped and must be reviewed by eye. Usage: git fetch --all && python scripts/audit_history.py
"""
# Scans every blob reachable from any ref (all history) plus the working tree. Prints counts and paths only,
# never the matched values.
import re, subprocess, collections
PATTERNS = {
    "groq_key": r"gsk_[A-Za-z0-9]{20,}",
    "openai_style_key": r"sk-[A-Za-z0-9]{20,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "slack_token": r"xox[abpr]-[A-Za-z0-9-]{10,}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "assigned_secret": r"(?i)(api[_-]?key|secret|password|token)[ \t]*[=:][ \t]*['\"]?[A-Za-z0-9/+_\-]{16,}",
    "bearer_literal": r"(?i)bearer[ \t]+[A-Za-z0-9._\-]{20,}",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone_like": r"(?<![\w.])\+?\d[\d \-]{8,}\d(?![\w.])",
    "real_brand_marina_bay_sands": r"(?i)marina bay sands|\bMBS\b",
    "platform_affiliation_terms": r"(?i)tencent|wechat|weixin|moments feed|mini programs?|official account",
    "job_application_terms": r"(?i)cover letter|job application|salary expectation|resume\b|curriculum vitae",
}
objs = subprocess.run(["git", "rev-list", "--all", "--objects"], capture_output=True, text=True).stdout.split("\n")
paths = collections.defaultdict(set)
for line in objs:
    if " " in line:
        sha, path = line.split(" ", 1); paths[sha].add(path)
hits = collections.defaultdict(lambda: collections.defaultdict(int))
for sha, ps in paths.items():
    t = subprocess.run(["git", "cat-file", "-t", sha], capture_output=True, text=True).stdout.strip()
    if t != "blob":
        continue
    data = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True).stdout
    if b"\0" in data[:4000]:
        continue  # binary
    text = data.decode("utf-8", "replace")
    for name, pat in PATTERNS.items():
        n = len(re.findall(pat, text))
        if n:
            for p in ps:
                hits[name][p] += n
for name in PATTERNS:
    files = hits.get(name, {})
    print(f"{name}: {sum(files.values())} matches in {len(files)} path(s)" + (": " + ", ".join(sorted(files)) if files else ""))
