"""Read-only collector that runs on a monitored machine and prints one line of JSON.

Usage: ``ssh host python3 - < remote_collect.py`` (MeshAtlas feeds it through stdin; nothing is written to disk).
It only reads ``docker ps``, ``docker stats``, ``systemctl list-units`` and ``/proc``. It never runs
``docker inspect`` and never reads environment variables, because those may contain secrets.
Must stay compatible with Python 3.8 and use only the standard library.

Besides the legacy fields (``ok``, ``sys``, ``docker``, ``services``, ``hostname``, ``elapsed`` ...),
the JSON carries a ``collection`` object. Every collection item there has a verifiable outcome:

* ``ok``          -- data was collected successfully
* ``missing``     -- the required tool is not installed on this host
* ``error``       -- the command failed (``error`` holds a truncated stderr/exception summary)
* ``parse_error`` -- the command ran but its output could not be parsed
* ``skipped``     -- the step was not attempted (e.g. ``docker stats`` with ``--no-stats``)

The legacy fields keep their exact meaning and structure; ``collection`` is additive only.
"""
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

# --no-stats skips `docker stats`, the slowest part on hosts with many containers.
WANT_STATS = "--no-stats" not in sys.argv

out = {"ok": True, "ts": time.time(), "hostname": socket.gethostname(), "system": platform.system()}

# 127 is the conventional "command not found" shell exit code; we reuse it when the OS
# raises FileNotFoundError so callers can tell a missing tool apart from a real failure.
RC_MISSING = 127
ERR_LIMIT = 200

# Outcome statuses used inside the `collection` field.
ST_OK = "ok"
ST_MISSING = "missing"
ST_ERROR = "error"
ST_PARSE = "parse_error"
ST_SKIPPED = "skipped"


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as exc:
        return RC_MISSING, "", short_err(str(exc))
    except Exception as exc:  # noqa: BLE001  (includes TimeoutExpired)
        return -1, "", short_err(str(exc))


def short_err(text):
    """Collapse whitespace and truncate an error summary to ERR_LIMIT characters, like the old docker path did."""
    text = " ".join((text or "").split())
    return text[-ERR_LIMIT:] if len(text) > ERR_LIMIT else text


def outcome(status, error=None):
    return {"status": status, "error": error}


OK_OUTCOME = outcome(ST_OK)


def disk_usage(path):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bfree * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    used = total - free
    return {"mount": path, "total": total, "used": used, "avail": avail}


def linux_system():
    info = {}
    try:
        rel = {}
        with open("/etc/os-release") as fh:
            for line in fh:
                key, _, val = line.strip().partition("=")
                rel[key] = val.strip('"')
        info["os"] = rel.get("PRETTY_NAME", "Linux")
    except OSError:
        info["os"] = "Linux"
    info["kernel"] = platform.release()
    try:
        with open("/proc/uptime") as fh:
            info["uptime"] = float(fh.read().split()[0])
        with open("/proc/loadavg") as fh:
            info["load"] = [float(x) for x in fh.read().split()[:3]]
    except OSError:
        pass
    info["ncpu"] = os.cpu_count()

    def cpu_times():
        with open("/proc/stat") as fh:
            vals = [int(x) for x in fh.readline().split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)

    try:
        i1, t1 = cpu_times()
        time.sleep(0.6)
        i2, t2 = cpu_times()
        info["cpu"] = round(100.0 * (1 - (i2 - i1) / max(1, t2 - t1)), 1)
    except OSError:
        pass
    try:
        mem = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, val = line.split(":", 1)
                mem[key] = int(val.split()[0]) * 1024
        total = mem["MemTotal"]
        info["mem"] = {"total": total, "used": total - mem.get("MemAvailable", mem.get("MemFree", 0))}
    except (OSError, KeyError, ValueError):
        pass
    info["disks"] = linux_disks()
    return info


REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "bcachefs", "ntfs3", "exfat"}
SKIP_PREFIX = ("/boot", "/snap", "/var/lib/docker", "/var/lib/containers", "/run", "/proc", "/sys", "/dev")


def linux_disks(limit=6):
    """`/` plus other real filesystems of at least 1 GiB, biggest first (bind mounts and duplicates skipped)."""
    seen_dev, disks = set(), []
    try:
        with open("/proc/mounts") as fh:
            mounts = [line.split()[:3] for line in fh if len(line.split()) >= 3]
    except OSError:
        mounts = [["/", "/", "ext4"]]
    for dev, path, fstype in mounts:
        path = path.replace("\\040", " ")
        if fstype not in REAL_FS or (path != "/" and path.startswith(SKIP_PREFIX)) or dev in seen_dev:
            continue
        try:
            d = disk_usage(path)
        except OSError:
            continue
        if path != "/" and d["total"] < 2 ** 30:
            continue
        seen_dev.add(dev)
        disks.append(d)
    disks.sort(key=lambda d: (d["mount"] != "/", -d["total"]))
    return disks[:limit] or [disk_usage("/")]


def mac_system():
    info = {"kernel": platform.release(), "ncpu": os.cpu_count()}
    rc, ver, _ = run(["sw_vers", "-productVersion"], 5)
    info["os"] = "macOS " + ver.strip() if rc == 0 else "macOS"
    rc, boot, _ = run(["sysctl", "-n", "kern.boottime"], 5)
    try:
        sec = int(boot.split("sec =")[1].split(",")[0])
        info["uptime"] = time.time() - sec
    except (IndexError, ValueError):
        pass
    try:
        info["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    rc, top, _ = run(["top", "-l", "2", "-n", "0", "-s", "1"], 10)
    idle = [line for line in top.splitlines() if line.startswith("CPU usage:")]
    if idle:
        try:
            info["cpu"] = round(100.0 - float(idle[-1].split(",")[-1].split("%")[0]), 1)
        except ValueError:
            pass
    rc, memsize, _ = run(["sysctl", "-n", "hw.memsize"], 5)
    rc2, vm, _ = run(["vm_stat"], 5)
    try:
        total = int(memsize.strip())
        page = 4096
        pages = {}
        for line in vm.splitlines():
            if "page size of" in line:
                page = int(line.split("page size of")[1].split()[0])
            elif ":" in line:
                key, val = line.split(":", 1)
                pages[key.strip()] = int(val.strip().rstrip("."))
        used = (pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
                + pages.get("Pages occupied by compressor", 0)) * page
        info["mem"] = {"total": total, "used": used}
    except (ValueError, IndexError):
        pass
    try:
        info["disks"] = [disk_usage("/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/")]
    except OSError:
        info["disks"] = []
    return info


def docker_ps(listing):
    """Parse `docker ps` JSON-lines output into the legacy container records."""
    containers = []
    for line in listing.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        project = ""
        # keep only the compose project name; every other label is dropped
        for pair in (item.get("Labels") or "").split(","):
            if pair.startswith("com.docker.compose.project="):
                project = pair.split("=", 1)[1]
                break
        status = item.get("Status", "")
        health = ""
        if "(healthy)" in status:
            health = "healthy"
        elif "(unhealthy)" in status:
            health = "unhealthy"
        elif "health: starting" in status:
            health = "starting"
        containers.append({
            "name": item.get("Names", ""),
            "image": item.get("Image", ""),
            "state": item.get("State", ""),
            "status": status,
            "health": health,
            "project": project,
            "ports": item.get("Ports", ""),
            "networks": item.get("Networks", ""),
            "runningFor": item.get("RunningFor", ""),
            "createdAt": item.get("CreatedAt", ""),
        })
    return containers


def docker_stats(prefix):
    """Run and parse `docker stats`; returns (stats_by_name, outcome).

    A failing stats command never removes the containers collected by `docker ps`: the legacy
    docker dict stays intact and only this outcome reports the missing statistics.
    """
    if not WANT_STATS:
        return {}, outcome(ST_SKIPPED)
    rc, so, se = run(prefix + ["docker", "stats", "--no-stream", "--format", "{{json .}}"], 60)
    if rc == RC_MISSING:
        return {}, outcome(ST_MISSING, "docker: command not found")
    if rc != 0:
        return {}, outcome(ST_ERROR, short_err(se) or "docker stats failed (exit {0})".format(rc))
    stats = {}
    for line in so.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        try:
            cpu = float(item.get("CPUPerc", "0").rstrip("%") or 0)
        except ValueError:
            cpu = None
        try:
            memp = float(item.get("MemPerc", "0").rstrip("%") or 0)
        except ValueError:
            memp = None
        stats[item.get("Name", "")] = {"cpu": cpu, "memPct": memp,
                                       "mem": (item.get("MemUsage", "").split("/")[0]).strip()}
    if not stats and so.strip():
        # the command reported success with non-empty output, but none of it was parseable
        return {}, outcome(ST_PARSE, "could not parse docker stats output: " + short_err(so))
    return stats, OK_OUTCOME


def docker_info():
    """Returns (legacy_docker_dict_or_None, ps_outcome, stats_outcome)."""
    if not shutil.which("docker"):
        return None, outcome(ST_MISSING, "docker is not installed"), outcome(ST_MISSING, "docker is not installed")
    prefix = None
    listing = ""
    err = ""
    for candidate in ([], ["sudo", "-n"]):
        rc, so, se = run(candidate + ["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], 30)
        if rc == 0:
            prefix, listing = candidate, so
            break
        if rc == RC_MISSING:
            err = "docker: command not found"
            break
        err = short_err(se)
    if prefix is None:
        # docker ps failed: containers stay empty and the reason is recorded separately from stats
        return ({"error": err or "docker ps failed", "containers": []},
                outcome(ST_ERROR, err or "docker ps failed"),
                outcome(ST_SKIPPED, "skipped because docker ps failed"))
    if listing.strip():
        containers = docker_ps(listing)
        if not containers:
            return ({"error": "could not parse docker ps output", "containers": []},
                    outcome(ST_PARSE, "could not parse docker ps output: " + short_err(listing)),
                    outcome(ST_SKIPPED, "skipped because docker ps output was unparseable"))
    else:
        containers = []
    stats, stats_oc = docker_stats(prefix)
    for c in containers:
        s = stats.get(c["name"])
        if s:
            c.update(s)
    return {"containers": containers, "sudo": bool(prefix), "stats": bool(stats)}, OK_OUTCOME, stats_oc


def systemd_scope(scope, extra):
    """Collect one systemctl scope; returns (units, outcome) with its own independent status."""
    rc, so, se = run(["systemctl"] + extra + ["list-units", "--type=service", "--all",
                                              "--no-legend", "--plain", "--no-pager"], 15)
    if rc == RC_MISSING:
        return [], outcome(ST_MISSING, "systemctl: command not found")
    if rc != 0:
        return [], outcome(ST_ERROR, short_err(se) or "systemctl {0} list-units failed (exit {1})".format(scope, rc))
    units, malformed = [], 0
    for line in so.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            if line.strip():
                malformed += 1
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) > 4 else ""
        if load == "not-found":
            continue
        if active not in ("active", "failed", "activating", "reloading"):
            continue
        units.append({"unit": unit, "active": active, "sub": sub, "desc": desc[:80], "scope": scope})
    if not units and malformed:
        return [], outcome(ST_PARSE,
                           "could not parse systemctl {0} list-units output ({1} malformed line(s))".format(
                               scope, malformed))
    return units, OK_OUTCOME


def systemd_info():
    """Returns (legacy_units_list_or_None, {scope: outcome}).

    system and user scopes are independent: if only one succeeds, services still carries the
    successful scope's units and the two scopes record their own status.
    """
    if not shutil.which("systemctl"):
        missing = outcome(ST_MISSING, "systemctl is not installed")
        return None, {"system": missing, "user": missing}
    outcomes = {}
    units = []
    for scope, extra in (("system", []), ("user", ["--user"])):
        scope_units, scope_oc = systemd_scope(scope, extra)
        outcomes[scope] = scope_oc
        units.extend(scope_units)
    return units, outcomes


collection = {}
try:
    if out["system"] == "Darwin":
        out["sys"] = mac_system()
    else:
        out["sys"] = linux_system()
    collection["system"] = OK_OUTCOME
except Exception as exc:  # noqa: BLE001
    out["sys"] = {"error": str(exc)}
    collection["system"] = outcome(ST_ERROR, short_err(str(exc)) or "system information collection failed")

docker_data, docker_ps_oc, docker_stats_oc = docker_info()
out["docker"] = docker_data
collection["docker"] = {"ps": docker_ps_oc, "stats": docker_stats_oc}

services, systemd_oc = systemd_info()
out["services"] = services
collection["systemd"] = systemd_oc

out["collection"] = collection
out["elapsed"] = round(time.time() - out["ts"], 2)
print(json.dumps(out, ensure_ascii=False))
