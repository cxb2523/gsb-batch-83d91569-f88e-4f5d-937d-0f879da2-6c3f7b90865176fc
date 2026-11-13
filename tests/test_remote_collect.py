import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "meshatlas" / "remote_collect.py"


def test_remote_collect_runs_locally():
    r = subprocess.run([sys.executable, "-", "--no-stats"], input=SCRIPT.read_bytes(), stdout=subprocess.PIPE, timeout=90)
    data = json.loads(r.stdout.decode().strip().splitlines()[-1])
    assert data["ok"] is True and "sys" in data
    assert isinstance(data["sys"].get("disks", []), list)
