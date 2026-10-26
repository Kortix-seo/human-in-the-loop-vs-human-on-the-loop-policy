#!/usr/bin/env python3
"""Evaluate sample tool calls against a kortix.yaml approval policy, offline.

This is a reading aid for one file: it replays the rule order Kortix documents
(project-wide policies, then the connector's own policies, then `sensitive`,
then `policy.default_mode`) over a list of calls and prints what a person would
see: run, held for approval, or blocked. It is not Kortix and does not contact
any API.

    uv run --with pyyaml python check_calls.py

Reads kortix.yaml and calls.sample.json from this directory.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

READ_PREFIXES = ("get_", "list_", "search_", "retrieve", "read_")
WRITE_MARKERS = ("delete", "destroy", "refund", "create", "update", "send", "post", "put", "patch", "cancel", "close", "invite", "remove")


def matches(pattern: str, value: str) -> bool:
    """Glob (case-insensitive) or /regex/ in slashes."""
    if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
        return re.search(pattern[1:-1], value) is not None
    return re.fullmatch(pattern.replace(".", r"\.").replace("*", ".*"), value, re.IGNORECASE) is not None


def arg_value(arguments: dict, path: str):
    cur = arguments
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def condition_holds(cond: dict, arguments: dict) -> bool | None:
    """True/False, or None when the condition is malformed (fails closed)."""
    if not isinstance(cond, dict) or "arg" not in cond or "match" not in cond:
        return None
    value, present = arg_value(arguments, str(cond["arg"]))
    if not present or value is None:
        # A missing argument never matches, so a negated condition on it holds.
        result = False
    elif isinstance(value, list):
        result = all(matches(str(cond["match"]), str(v)) for v in value)
    else:
        result = matches(str(cond["match"]), str(value))
    return (not result) if cond.get("negate") else result


def rule_matches(rule: dict, name: str, arguments: dict):
    """('hit', action) | ('miss', None) | ('malformed', 'require_approval')."""
    if not matches(str(rule.get("match", "")), name):
        return "miss", None
    conditions = rule.get("conditions") or []
    if len(conditions) > 10:
        return "malformed", "require_approval"
    for cond in conditions:
        verdict = condition_holds(cond, arguments)
        if verdict is None:
            return "malformed", "require_approval"
        if verdict is False:
            return "miss", None
    return "hit", rule.get("action", "require_approval")


def is_read(action: str) -> bool:
    return action.lower().startswith(READ_PREFIXES)


def decide(call: dict, manifest: dict) -> tuple[str, str]:
    connector_slug = call["connector"]
    action = call["action"]
    arguments = call.get("arguments") or {}
    connector = next((c for c in manifest.get("connectors") or [] if c.get("slug") == connector_slug), None)

    # 1. Project-wide policies: fully qualified patterns, and they win.
    for rule in manifest.get("policies") or []:
        state, verdict = rule_matches(rule, f"{connector_slug}.{action}", arguments)
        if state != "miss":
            return outcome(verdict), f"project-wide rule {rule.get('match')}"

    # 2. The connector's own policies: patterns relative to the connector.
    if connector:
        for rule in connector.get("policies") or []:
            state, verdict = rule_matches(rule, action, arguments)
            if state != "miss":
                return outcome(verdict), f"{connector_slug} rule {rule.get('match')}"

        # 3. sensitive: every remaining action needs approval, reads included.
        if connector.get("sensitive"):
            return "held", f"{connector_slug} is sensitive: true"

    # 4. The project default.
    mode = (manifest.get("policy") or {}).get("default_mode", "allow_all")
    if mode == "allow_all":
        return "run", "default_mode allow_all"
    if is_read(action):
        return "run", f"default_mode {mode}: read"
    return "held", f"default_mode {mode}: write held"


def outcome(verdict: str) -> str:
    return {"always_run": "run", "require_approval": "held", "block": "blocked"}.get(verdict, "held")


def main() -> int:
    here = Path(__file__).resolve().parent
    manifest = yaml.safe_load((here / "kortix.yaml").read_text(encoding="utf-8"))
    calls = json.loads((here / "calls.sample.json").read_text(encoding="utf-8"))
    rows = []
    for call in calls:
        result, why = decide(call, manifest)
        rows.append((call["id"], result, why))
        print(f"{call['id']:<17} {result:<8} {why}")
    lines = (here / "expected.txt").read_text(encoding="utf-8").splitlines()
    expected = [line.split()[:2] for line in lines if line.strip() and not line.startswith("#")]
    actual = [[r[0], r[1]] for r in rows]
    if actual != expected:
        print("\nMISMATCH against expected.txt", file=sys.stderr)
        return 1
    print("\nAll calls match expected.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
