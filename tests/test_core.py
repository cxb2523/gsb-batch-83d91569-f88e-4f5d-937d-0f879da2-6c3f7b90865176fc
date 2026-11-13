import pytest

from meshatlas import config, core, tailscale


@pytest.fixture
def atlas(tmp_path, monkeypatch, status_json):
    monkeypatch.setattr(tailscale, "status", lambda: tailscale.parse_status(status_json))
    monkeypatch.setattr(tailscale, "derp_map", lambda: ({"sfo": ("San Francisco", 37.77, -122.42),
                                                          "fra": ("Frankfurt", 50.11, 8.68),
                                                          "home-derp": ("Home DERP", None, None)}, {"2": "sfo", "4": "fra"}))
    monkeypatch.setattr(tailscale, "nearest_regions", lambda ids: ["sfo", "fra"])
    cfg = config._merge(config.DEFAULTS, {
        "nodes": {"vps-fra": {"role": "Edge", "ssh": "root@vps-fra", "notes": ["hello"]}},
        "external": [{"id": "pub", "address": "203.0.113.9", "location": "fra"}],
        "display": {"hide": ["localhost"]},
    })
    a = core.Atlas(cfg, tmp_path)
    a.discover()
    return a


def test_discover(atlas):
    nodes = atlas.nodes
    assert atlas.hub == "homelab"
    assert "localhost" not in nodes                      # hidden in config
    assert "old-phone" not in nodes                      # offline for more than 30 days
    assert nodes["homelab"]["loc"] == "sfo" and nodes["homelab"]["local"] is True
    assert nodes["vps-fra"]["collected"] and nodes["vps-fra"]["role"] == "Edge" and nodes["vps-fra"]["notes"] == ["hello"]
    # custom region without coordinates -> placed at the hub, flagged approximate
    assert nodes["my-laptop"]["loc"] == "sfo" and nodes["my-laptop"]["approxLoc"] is True
    assert nodes["pub"]["external"] and nodes["pub"]["loc"] == "fra" and not nodes["pub"]["inTailnet"]


def test_api_state_shape(atlas):
    s = atlas.api_state()
    assert s["config"]["hub"] == "homelab"
    assert s["config"]["nodes"][0]["id"] == "homelab"     # hub first
    assert set(s["config"]["locations"]) == {"sfo", "fra"}
    assert "ssh" not in s["config"]["nodes"][1]           # SSH targets never reach the browser
    assert s["nodes"]["vps-fra"]["tailscale"]["online"] is True


def test_events_and_history(atlas):
    atlas.emit("CTR", "vps-fra/web exited", "warn", "vps-fra")
    ev = atlas.api_events("vps-fra", ["warn"], 10, None)["events"]
    assert ev and ev[0]["msg"] == "vps-fra/web exited"
    atlas.record_status()
    up = atlas.api_uptime(24, 12)
    assert up["nodes"]["homelab"]["pct"] == 100.0
    h = atlas.api_history("homelab", 1)
    assert h["status"] and h["status"][0][1] == 1


def test_edge_helper():
    e = core.edge("a", "b", [10.0, 12.0], "direct", None, "tailscale")
    assert e["ms"] == 11.0 and e["min"] == 10.0 and e["max"] == 12.0 and e["state"] == "ok"
    d = core.edge("a", "b", [], "icmp", None, "icmp")
    assert d["ms"] is None and d["route"] == "icmp" and d["state"] == "unreachable"
