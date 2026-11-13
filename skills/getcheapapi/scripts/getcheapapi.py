#!/usr/bin/env python3
"""Run the getcheapapi CLI from this skill.

Uses the installed package when there is one; otherwise the src/ folder of the
getcheapapi repository this skill was linked from. Standard library only.
"""
import importlib.util
import sys
from pathlib import Path

# This file shares the package's name: drop its own folder so imports find the package, not this script.
HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]

if importlib.util.find_spec("getcheapapi") is None:
    src = Path(__file__).resolve().parents[3] / "src"  # scripts -> skill -> skills -> repo root
    if not (src / "getcheapapi").is_dir():
        sys.exit("getcheapapi cannot find its code. Link this skill from a clone of https://github.com/getcheapapi/getcheapapi "
                 "instead of copying it; see https://getcheapapi.com/llms.txt.")
    sys.path.insert(0, str(src))

from getcheapapi.cli import main  # noqa: E402

main()
