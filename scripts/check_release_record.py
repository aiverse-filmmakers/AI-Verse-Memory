#!/usr/bin/env python3
"""Check that release/component-release.json and the code it accepts agree.

The record names an accepted commit and a version. This check reads the code
AT THE ACCEPTED COMMIT (git show, so the clone needs full history) and fails if:
  * the record is malformed,
  * the accepted commit does not exist,
  * a version holder at that commit disagrees with the record's version,
  * the same CI run id is listed twice as separate evidence.
It only warns (exit code unchanged) when HEAD is far ahead of the accepted commit.

Usage: python scripts/check_release_record.py [--repo DIR] [--record PATH]
Exit code 0 means pass, 1 means the record and the code disagree, 2 means usage error.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
MAX_COMMITS_AHEAD = 50

# (path, regex with one group capturing the version). Every one must be found.
KNOWN_HOLDERS = [
    ("manifest.json", r'(?m)^\s*"version"\s*:\s*"([^"]+)"'),
    ("SKILL.md", r"(?m)^version:\s*[\"']?([^\s\"']+)[\"']?\s*$"),
    ("scripts/memory_engine.py", r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']'),
    ("scripts/install_engine.py", r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']'),
    ("README.md", r"Current development version:\s*\*\*([^*\s]+)\*\*"),
]
# Other holders are found by looking at the accepted commit itself.
DISCOVERED_PY = re.compile(r'(?m)^(?:__version__|VERSION)\s*=\s*["\']([^"\']+)["\']')
DISCOVERED_JSON = re.compile(r'(?m)^\s{0,4}"version"\s*:\s*"([^"]+)"')


def git(repo, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def check_record_shape(rec, problems):
    if not isinstance(rec, dict):
        problems.append("The release record is not a JSON object.")
        return False
    ok = True
    if rec.get("schema_version") != "ai-verse.component-release/v1":
        problems.append("The release record has a wrong or missing schema_version.")
        ok = False
    if rec.get("component_id") != "ai-verse-memory":
        problems.append("The release record has a wrong or missing component_id.")
        ok = False
    version = rec.get("version")
    if not isinstance(version, str) or not VERSION.match(version):
        problems.append("The release record has no valid version (got %r)." % (version,))
        ok = False
    revision = rec.get("revision")
    if not isinstance(revision, str) or not SHA.match(revision):
        problems.append("The release record revision is not a full 40 character commit id (got %r)." % (revision,))
        ok = False
    if rec.get("release_status") not in ("candidate", "accepted"):
        problems.append("The release record release_status must be candidate or accepted.")
        ok = False
    evidence = rec.get("evidence")
    if not isinstance(evidence, dict):
        problems.append("The release record has no evidence section.")
        ok = False
    else:
        for group in ("ci", "acceptance"):
            if not isinstance(evidence.get(group), list):
                problems.append("The release record evidence.%s must be a list." % group)
                ok = False
            elif not all(isinstance(e, dict) for e in evidence[group]):
                problems.append("Every evidence.%s entry must be an object." % group)
                ok = False
    return ok


def check_duplicate_runs(rec, problems):
    seen = {}
    for group in ("ci", "acceptance"):
        for entry in rec["evidence"][group]:
            run_id = str(entry.get("run_id", "")).strip()
            if not run_id:
                problems.append("An evidence.%s entry has no run_id." % group)
                continue
            if run_id in seen:
                problems.append(
                    "CI run %s is listed twice as separate evidence (in %s and %s). "
                    "One run proves one thing, so it cannot count as two proofs." % (run_id, seen[run_id], group)
                )
            else:
                seen[run_id] = group


def holders_at(repo, revision):
    """Return (found, missing): found is a list of (path, version)."""
    found, missing = [], []
    known_paths = set()
    for path, pattern in KNOWN_HOLDERS:
        known_paths.add(path)
        code, out, _ = git(repo, "show", "%s:%s" % (revision, path))
        if code != 0:
            missing.append(path)
            continue
        m = re.search(pattern, out)
        if not m:
            missing.append(path)
        else:
            found.append((path, m.group(1)))
    code, out, _ = git(repo, "ls-tree", "-r", "--name-only", revision)
    for path in out.splitlines() if code == 0 else []:
        if path in known_paths or path.startswith(("tests/", "docs/", "release/", "templates/")):
            continue
        if path.count("/") > 1:
            continue
        regex = DISCOVERED_PY if path.endswith(".py") else DISCOVERED_JSON if path.endswith(".json") and "/" not in path else None
        if regex is None:
            continue
        code, text, _ = git(repo, "show", "%s:%s" % (revision, path))
        m = regex.search(text) if code == 0 else None
        if m and VERSION.match(m.group(1)):
            found.append((path, m.group(1)))
    return found, missing


def run(repo, record_path):
    problems, warnings = [], []
    try:
        rec = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ["The release record cannot be read as JSON: %s" % exc], warnings, None
    if not check_record_shape(rec, problems):
        return problems, warnings, rec
    check_duplicate_runs(rec, problems)
    revision, version = rec["revision"], rec["version"]
    code, _, _ = git(repo, "cat-file", "-e", "%s^{commit}" % revision)
    if code != 0:
        problems.append(
            "The accepted commit %s does not exist in this clone. If the clone is shallow, fetch full history." % revision
        )
        return problems, warnings, rec
    found, missing = holders_at(repo, revision)
    for path in missing:
        problems.append("%s at the accepted commit has no readable version." % path)
    for path, held in found:
        if held != version:
            problems.append(
                "%s says %s at the accepted commit %s, but the release record says %s." % (path, held, revision[:12], version)
            )
    code, out, _ = git(repo, "rev-list", "--count", "%s..HEAD" % revision)
    if code == 0 and out.strip().isdigit() and int(out) > MAX_COMMITS_AHEAD:
        warnings.append(
            "Heads up: the code has moved %s commits past the accepted commit (more than %d). "
            "The record may be out of date and a fresh acceptance may be due. This is a warning, not a failure."
            % (out.strip(), MAX_COMMITS_AHEAD)
        )
    return problems, warnings, rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--record", default=None)
    args = ap.parse_args(argv)
    record = args.record or str(Path(args.repo) / "release" / "component-release.json")
    problems, warnings, rec = run(args.repo, record)
    for w in warnings:
        print("WARNING: " + w)
    if problems:
        print("RELEASE RECORD CHECK FAILED")
        for p in problems:
            print(" - " + p)
        return 1
    print("Release record check passed: version %s at accepted commit %s." % (rec["version"], rec["revision"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
