"""Read-only collector that runs on a monitored machine and prints one line of JSON.

Usage: ``ssh host python3 - < remote_collect.py`` (MeshAtlas feeds it through stdin; nothing is written to disk).
It only reads ``docker ps``, ``docker stats``, ``systemctl list-units`` and ``/proc``. It never runs
``docker inspect`` and never reads environment variables, because those may contain secrets.
Must stay compatible with Python 3.8 and use only the standard library.
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

out ={"ok": True, "ts": time.time(), "hostname": socket.gethostname(), "system": platform.system()}


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


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


def docker_info():
    if not shutil.which("docker"):
        return None
    prefix = None
    listing = ""
    err = ""
    for candidate in ([], ["sudo", "-n"]):
        rc, so, se = run(candidate + ["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], 30)
        if rc == 0:
            prefix, listing = candidate, so
            break
        err = se.strip()[-200:]
    if prefix is None:
        return {"error": err or "docker ps failed", "containers": []}
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
    stats = {}
    rc, so = 1, ""
    if WANT_STATS:
        rc, so, _ = run(prefix + ["docker", "stats", "--no-stream", "--format", "{{json .}}"], 60)
    if rc == 0:
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
    for c in containers:
        s = stats.get(c["name"])
        if s:
            c.update(s)
    return {"containers": containers, "sudo": bool(prefix), "stats": bool(stats)}


def systemd_info():
    if not shutil.which("systemctl"):
        return None
    units = []
    for scope, extra in (("system", []), ("user", ["--user"])):
        rc, so, _ = run(["systemctl"] + extra + ["list-units", "--type=service", "--all",
                                                 "--no-legend", "--plain", "--no-pager"], 15)
        if rc != 0:
            continue
        for line in so.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            unit, load, active, sub = parts[:4]
            desc = parts[4] if len(parts) > 4 else ""
            if load == "not-found":
                continue
            if active not in ("active", "failed", "activating", "reloading"):
                continue
            units.append({"unit": unit, "active": active, "sub": sub, "desc": desc[:80], "scope": scope})
    return units


try:
    if out["system"] == "Darwin":
        out["sys"] = mac_system()
    else:
        out["sys"] = linux_system()
except Exception as exc:  # noqa: BLE001
    out["sys"] = {"error": str(exc)}
out["docker"] = docker_info()
out["services"] = systemd_info()
out["elapsed"] = round(time.time() - out["ts"], 2)
print(json.dumps(out, ensure_ascii=False))
