#!/usr/bin/env python3
"""Fake `gh` CLI used by tests/test_verify.py — NOT a real GitHub client.

Behaviour is driven entirely by env vars set by the test harness:
    FAKE_GH_SCENARIO  path to a JSON file mapping "repos/{slug}" to either
                        {"payload": {...}}                -> print JSON, exit 0
                        {"exit": N, "stderr": "..."}      -> print stderr, exit N
    FAKE_GH_LOG       optional path; every invocation is appended here so
                        tests can assert whether any API call happened.

It never talks to the network and only ever runs against temp directories.
"""
import json
import os
import sys


def main() -> int:
    log = os.environ.get("FAKE_GH_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(" ".join(sys.argv[1:]) + "\n")

    scenario_path = os.environ.get("FAKE_GH_SCENARIO")
    if not scenario_path:
        print("fake_gh: FAKE_GH_SCENARIO not set", file=sys.stderr)
        return 2
    with open(scenario_path, encoding="utf-8") as f:
        scenario = json.load(f)

    if len(sys.argv) < 3 or sys.argv[1] != "api":
        print("fake_gh: only 'gh api <endpoint>' is supported", file=sys.stderr)
        return 2
    endpoint = sys.argv[2]

    stub = scenario.get(endpoint)
    if stub is None:
        print(f"fake_gh: no stub registered for {endpoint}", file=sys.stderr)
        return 2
    if "payload" in stub:
        sys.stdout.write(json.dumps(stub["payload"]))
        return 0
    sys.stderr.write(stub.get("stderr", ""))
    return int(stub.get("exit", 1))


if __name__ == "__main__":
    raise SystemExit(main())
