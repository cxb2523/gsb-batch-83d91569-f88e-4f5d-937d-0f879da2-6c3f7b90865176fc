"""Broken-install double: importing camoufox itself fails, as a half-finished
pip install or missing system library would make it fail on a real box."""

raise ImportError("simulated broken camoufox install")
