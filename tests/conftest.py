"""Pytest configuration for the offline engine tests.

The repo is a flat collection of top-level modules (see pyproject.toml's
``py-modules``) rather than an installed package, so make the repo root
importable without requiring an editable install.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
