import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "meshatlas" / "remote_collect.py"

# ---------------------------------------------------------------------------
# Faking docker / systemctl / sudo.
#
# The task explicitly permits "locally faked docker/systemctl executables OR
# injected failing commands". On Windows the collector's shell-less
# subprocess.run cannot resolve bare command names through PATH reliably, so
# the fakes are small stdlib Python driver scripts and a prelude redirects the
# collector's shutil.which / subprocess.run at them. On POSIX the same drivers
# are also written out, so the mechanism is identical end to end. No real
# Docker or systemd is involved and nothing opens a network socket.
#
# The drivers never read environment variables: behaviour is selected purely
# from argv, mirroring the collector's own no-environment rule.
# ---------------------------------------------------------------------------

DOCKER_DRIVER = r'''
import json
import sys

# argv after the driver path: [ps_mode, stats_mode, then the real docker argv...]
ps_mode, stats_mode = sys.argv[1], sys.argv[2]
args = sys.argv[3:]


def emit_containers():
    rows = [
        {"Names": "web", "Image": "nginx:1.27", "State": "running",
         "Status": "Up 2 hours (healthy)", "Labels": "com.docker.compose.project=site",
         "Ports": "0.0.0.0:80->80/tcp", "Networks": "site_default",
         "RunningFor": "2 hours ago", "CreatedAt": "2026-01-01T00:00:00Z"},
        {"Names": "db", "Image": "postgres:16", "State": "running",
         "Status": "Up 3 days (unhealthy)", "Labels": "",
         "Ports": "", "Networks": "site_default",
         "RunningFor": "3 days ago", "CreatedAt": "2025-12-29T00:00:00Z"},
    ]
    for row in rows:
        print(json.dumps(row))


def emit_stats():
    for name, cpu, memp, mem in (("web", "1.50%", "20.00%", "100MiB / 512MiB"),
                                 ("db", "3.00%", "40.00%", "200MiB / 1GiB")):
        print(json.dumps({"Name": name, "CPUPerc": cpu, "MemPerc": memp, "MemUsage": mem}))


if "ps" in args:
    if ps_mode == "fail":
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                         "Is the docker daemon running?")
        sys.exit(1)
    if ps_mode == "garbage":
        print("this is not json at all")
        print("neither is this line")
        sys.exit(0)
    emit_containers()
elif "stats" in args:
    if stats_mode == "fail":
        sys.stderr.write("Got permission denied while trying to connect to the Docker daemon socket")
        sys.exit(1)
    if stats_mode == "garbage":
        print("stats output that is not json")
        sys.exit(0)
    emit_stats()
else:
    sys.stderr.write("unknown docker invocation: " + " ".join(args))
    sys.exit(2)
'''

SYSTEMCTL_DRIVER = r'''
import sys

# argv after the driver path: [system_mode, then the real systemctl argv...]
mode = sys.argv[1]
args = sys.argv[2:]
is_user = "--user" in args

if mode == "fail":
    sys.stderr.write("System has not been booted with systemd as init system (PID 1). Can't operate.")
    sys.exit(1)
if mode == "garbage":
    print("unparseable line without enough fields")
    print("another bad line")
    sys.exit(0)
if mode == "mixed" and is_user:
    sys.stderr.write("Failed to connect to bus: no user bus available")
    sys.exit(1)
print("ssh.service loaded active running OpenBSD Secure Shell server")
print("cron.service loaded active running Regular background program processing daemon")
print("broken.service loaded failed failed A service that broke on purpose")
print("dead.service loaded inactive dead An inactive unit that must be filtered out")
'''


def build_fake_bins(tmp_path, ps_mode="ok", stats_mode="ok", system_mode="ok",
                    docker_present=True, systemctl_present=True):
    """Write the fake driver scripts and return (bindir, prelude) for collector injection."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    docker_driver = bindir / "fake_docker.py"
    systemctl_driver = bindir / "fake_systemctl.py"
    docker_driver.write_text(DOCKER_DRIVER, encoding="utf-8")
    systemctl_driver.write_text(SYSTEMCTL_DRIVER, encoding="utf-8")

    present = {"docker": docker_present, "systemctl": systemctl_present}
    drivers = {"docker": str(docker_driver), "systemctl": str(systemctl_driver)}
    # fixed argv each driver expects before the real command's arguments
    mode_args = {"docker": [ps_mode, stats_mode], "systemctl": [system_mode]}

    # Redirect shutil.which: absent tools report missing exactly as on a real host.
    # Redirect subprocess.run: map a tool command onto `python <driver> <mode...> <remaining args>`,
    # dropping sudo/-n (the collector's privilege-escalation attempt) so fakes stay simple.
    prelude = (
        "import shutil as _sh, subprocess as _sp, sys as _sys\n"
        "_present = " + repr(present) + "\n"
        "_drivers = " + repr(drivers) + "\n"
        "_mode_args = " + repr(mode_args) + "\n"
        "_orig_which = _sh.which\n"
        "def _which(name, *a, **k):\n"
        "    if name in _present:\n"
        "        return _drivers[name] if _present[name] else None\n"
        "    return _orig_which(name, *a, **k)\n"
        "_sh.which = _which\n"
        "_orig_run = _sp.run\n"
        "def _run(cmd, *a, **k):\n"
        "    tokens = list(cmd)\n"
        "    for tool in ('docker', 'systemctl'):\n"
        "        if tool in tokens and _present[tool]:\n"
        "            rest = [t for t in tokens if t not in (tool, 'sudo', '-n')]\n"
        "            cmd = [_sys.executable, _drivers[tool]] + list(_mode_args[tool]) + rest\n"
        "            break\n"
        "    return _orig_run(cmd, *a, **k)\n"
        "_sp.run = _run\n"
    )
    return bindir, prelude


def run_collector(tmp_path, prelude="", extra_args=None):
    """Feed remote_collect.py through stdin, exactly as MeshAtlas does over SSH."""
    script = prelude + "\n" + SCRIPT.read_text(encoding="utf-8")
    proc = subprocess.run([sys.executable, "-I", "-"] + (extra_args or []),
                          input=script.encode("utf-8"), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=90, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr.decode()
    return json.loads(proc.stdout.decode().strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Structural checks shared by every run
# ---------------------------------------------------------------------------

def assert_legacy_shape(data):
    """Old callers must keep reading the original fields with their original shapes."""
    assert data["ok"] is True
    for key in ("ts", "hostname", "elapsed", "sys", "docker", "services"):
        assert key in data
    assert isinstance(data["elapsed"], (int, float))
    assert isinstance(data["hostname"], str)
    assert isinstance(data["sys"], dict)
    if data["docker"] is not None:
        assert isinstance(data["docker"].get("containers"), list)
    if data["services"] is not None:
        assert all(set(u) >= {"unit", "active", "sub", "desc", "scope"} for u in data["services"])


def assert_collection_shape(data):
    col = data["collection"]
    assert set(col) == {"docker", "systemd", "system"}
    assert set(col["docker"]) == {"ps", "stats"}
    assert set(col["systemd"]) == {"system", "user"}
    entries = list(col["docker"].values()) + list(col["systemd"].values()) + [col["system"]]
    for entry in entries:
        assert entry["status"] in ("ok", "missing", "error", "parse_error", "skipped")
        if entry["status"] in ("error", "parse_error", "missing"):
            assert isinstance(entry["error"], str) and entry["error"]
        elif entry["status"] == "ok":
            assert entry["error"] is None
        else:  # skipped may carry an explanatory note but never needs one
            assert entry["error"] is None or isinstance(entry["error"], str)


# ---------------------------------------------------------------------------
# Docker paths
# ---------------------------------------------------------------------------

def test_all_success(tmp_path):
    _, prelude = build_fake_bins(tmp_path)
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    col = data["collection"]
    assert col["docker"]["ps"]["status"] == "ok"
    assert col["docker"]["stats"]["status"] == "ok"
    assert col["systemd"]["system"]["status"] == "ok"
    assert col["systemd"]["user"]["status"] == "ok"
    assert col["system"]["status"] in ("ok", "error")  # /proc only exists on Linux

    # legacy docker payload is fully populated and stats are merged onto the containers
    docker = data["docker"]
    assert docker["stats"] is True and docker["sudo"] is False
    names = [c["name"] for c in docker["containers"]]
    assert names == ["web", "db"]
    web = next(c for c in docker["containers"] if c["name"] == "web")
    assert web["health"] == "healthy" and web["project"] == "site"
    assert web["cpu"] == 1.5 and web["memPct"] == 20.0 and web["mem"] == "100MiB"

    # legacy services list carries units from both scopes
    units = {u["unit"] for u in data["services"]}
    assert {"ssh.service", "cron.service", "broken.service"} <= units
    assert "dead.service" not in units  # inactive units are still filtered out
    assert all(u["scope"] in ("system", "user") for u in data["services"])


def test_docker_missing(tmp_path):
    _, prelude = build_fake_bins(tmp_path, docker_present=False)
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    # legacy contract: no docker installed -> null, exactly as before
    assert data["docker"] is None
    assert data["collection"]["docker"]["ps"]["status"] == "missing"
    assert data["collection"]["docker"]["stats"]["status"] == "missing"


def test_docker_ps_failure(tmp_path):
    _, prelude = build_fake_bins(tmp_path, ps_mode="fail")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    # legacy contract: ps failure -> empty container list plus error string
    docker = data["docker"]
    assert docker["containers"] == []
    assert "docker daemon" in docker["error"]

    ps_oc = data["collection"]["docker"]["ps"]
    assert ps_oc["status"] == "error"
    assert "docker daemon" in ps_oc["error"]
    assert len(ps_oc["error"]) <= 200
    # stats must not be conflated with the ps failure
    assert data["collection"]["docker"]["stats"]["status"] == "skipped"


def test_docker_ps_unparseable(tmp_path):
    _, prelude = build_fake_bins(tmp_path, ps_mode="garbage")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    assert data["docker"]["containers"] == []
    ps_oc = data["collection"]["docker"]["ps"]
    assert ps_oc["status"] == "parse_error"
    assert "parse" in ps_oc["error"]
    assert data["collection"]["docker"]["stats"]["status"] == "skipped"


def test_docker_stats_failure_keeps_containers(tmp_path):
    _, prelude = build_fake_bins(tmp_path, stats_mode="fail")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    # containers survive a stats failure and are simply left without statistics
    docker = data["docker"]
    assert [c["name"] for c in docker["containers"]] == ["web", "db"]
    assert docker["stats"] is False
    assert all("cpu" not in c for c in docker["containers"])

    assert data["collection"]["docker"]["ps"]["status"] == "ok"
    stats_oc = data["collection"]["docker"]["stats"]
    assert stats_oc["status"] == "error"
    assert "permission denied" in stats_oc["error"].lower()


def test_docker_stats_unparseable_keeps_containers(tmp_path):
    _, prelude = build_fake_bins(tmp_path, stats_mode="garbage")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)

    assert [c["name"] for c in data["docker"]["containers"]] == ["web", "db"]
    assert data["docker"]["stats"] is False
    assert data["collection"]["docker"]["ps"]["status"] == "ok"
    assert data["collection"]["docker"]["stats"]["status"] == "parse_error"


def test_no_stats_flag_reports_skipped(tmp_path):
    _, prelude = build_fake_bins(tmp_path)
    data = run_collector(tmp_path, prelude, extra_args=["--no-stats"])
    assert_legacy_shape(data)

    assert [c["name"] for c in data["docker"]["containers"]] == ["web", "db"]
    assert data["docker"]["stats"] is False
    assert data["collection"]["docker"]["ps"]["status"] == "ok"
    assert data["collection"]["docker"]["stats"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# systemd paths
# ---------------------------------------------------------------------------

def test_systemd_missing(tmp_path):
    _, prelude = build_fake_bins(tmp_path, systemctl_present=False)
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    # legacy contract: no systemctl -> null, exactly as before
    assert data["services"] is None
    for scope in ("system", "user"):
        assert data["collection"]["systemd"][scope]["status"] == "missing"


def test_systemd_both_scopes_fail(tmp_path):
    _, prelude = build_fake_bins(tmp_path, system_mode="fail")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)

    assert data["services"] == []
    for scope in ("system", "user"):
        oc = data["collection"]["systemd"][scope]
        assert oc["status"] == "error"
        assert "systemd" in oc["error"]
        assert len(oc["error"]) <= 200


def test_systemd_only_one_scope_succeeds(tmp_path):
    # user scope fails while the system scope succeeds: services must still carry the good half
    _, prelude = build_fake_bins(tmp_path, system_mode="mixed")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    assert data["collection"]["systemd"]["system"]["status"] == "ok"
    user_oc = data["collection"]["systemd"]["user"]
    assert user_oc["status"] == "error" and "bus" in user_oc["error"]

    assert data["services"], "the successful scope's units must still be returned"
    assert all(u["scope"] == "system" for u in data["services"])
    assert {u["unit"] for u in data["services"]} >= {"ssh.service", "cron.service"}


def test_systemd_unparseable(tmp_path):
    _, prelude = build_fake_bins(tmp_path, system_mode="garbage")
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)

    assert data["services"] == []
    for scope in ("system", "user"):
        assert data["collection"]["systemd"][scope]["status"] == "parse_error"


# ---------------------------------------------------------------------------
# System information path
# ---------------------------------------------------------------------------

def test_system_info_failure_is_recorded(tmp_path):
    # Force os.statvfs to raise, which propagates out of the system info collection.
    # Deterministic on every platform; no real /proc dependency.
    prelude = (
        "import os as _os\n"
        "def _boom(*a, **k):\n"
        "    raise OSError('simulated proc failure')\n"
        "_os.statvfs = _boom\n"
    )
    data = run_collector(tmp_path, prelude)
    assert_legacy_shape(data)
    assert_collection_shape(data)

    sys_oc = data["collection"]["system"]
    assert sys_oc["status"] == "error"
    assert "simulated" in sys_oc["error"]
    # legacy contract: sys stays a dict carrying an error key
    assert "error" in data["sys"]


def test_error_summaries_are_truncated(tmp_path):
    # A fake whose stderr far exceeds the 200-char limit must still yield a bounded summary.
    long_msg = "X" * 1000
    driver = tmp_path / "loud_docker.py"
    driver.write_text(
        "import sys\n"
        "if 'ps' in sys.argv:\n"
        "    sys.stderr.write(" + repr(long_msg) + ")\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n", encoding="utf-8")
    prelude = (
        "import shutil as _sh, subprocess as _sp, sys as _sys\n"
        "_d = " + repr(str(driver)) + "\n"
        "_sh.which = lambda name, *a, **k: _d if name == 'docker' else None\n"
        "def _run(cmd, *a, **k):\n"
        "    tokens = list(cmd)\n"
        "    if 'docker' in tokens:\n"
        "        cmd = [_sys.executable, _d] + [t for t in tokens if t not in ('docker', 'sudo', '-n')]\n"
        "    return _sp.run(cmd, *a, **k)\n"
        "_sp.run = _run\n"
    )
    data = run_collector(tmp_path, prelude)
    assert len(data["collection"]["docker"]["ps"]["error"]) <= 200
    assert data["docker"]["error"] and len(data["docker"]["error"]) <= 200


# ---------------------------------------------------------------------------
# Hard constraints of the collector
# ---------------------------------------------------------------------------

def test_no_environment_and_no_inspect_in_script():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # no os.environ / os.getenv access anywhere in executable code
    env_reads = [n.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv")]
    assert not env_reads

    # `inspect` must never appear as a command argument (module docstring is skipped)
    doc = tree.body[0].value if tree.body and isinstance(tree.body[0], ast.Expr) else None
    for node in ast.walk(tree):
        if node is doc or not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        assert "inspect" not in node.value


def test_python38_compatible_syntax():
    # match statements (3.10) and try-star (3.11) must never appear; everything used here
    # (f-strings, walrus-free plain code, standard ast nodes) already parses on 3.8.
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"Match", "TryStar"}
    for node in ast.walk(tree):
        assert type(node).__name__ not in forbidden


def test_remote_collect_runs_locally():
    r = subprocess.run([sys.executable, "-I", "-", "--no-stats"], input=SCRIPT.read_bytes(),
                       stdout=subprocess.PIPE, timeout=90)
    data = json.loads(r.stdout.decode().strip().splitlines()[-1])
    assert data["ok"] is True and "sys" in data
    assert isinstance(data["sys"].get("disks", []), list)
    # the new field is present even in a plain local run
    assert_collection_shape(data)
    assert data["collection"]["docker"]["stats"]["status"] in (
        "ok", "skipped", "missing", "error", "parse_error")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
