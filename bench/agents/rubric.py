"""Grading rubric for the 20 agent-level questions.

Each question maps fact id -> list of elements; a fact is right only when every required element holds.
Element kinds: ("re", pattern) the pattern occurs in the answer; ("near", [patterns], window) all patterns occur
within `window` characters of each other; ("judge", statement) an LLM judge says the answer states it. A trailing
False marks an optional element (reported, not scored). Fixed before grading: ko-holiday scores only f1, because the
Wikipedia wording for f2/f3 differs from the 2026 regulation; claude-cache's 1-hour price and ko-minwage's June 29
are optional because the questions do not ask for them.

Notation fix after the 2026-10-09 runs, judgment unchanged: gdpr-fines accepts "20,000,000" and "10,000,000" as the
fine amounts (one answer wrote the amounts that way and had scored 0/2); k8s-termination's preStop/2-second window
widened from 250 to 400 characters (one answer put a sentence between the two and had scored 2/3)."""

from bench.agents.rubric_body import RUBRIC

__all__ = ["RUBRIC"]
