from meshatlas import tailscale


def test_parse_status(status_json):
    st = tailscale.parse_status(status_json)
    assert st["tailnet"] == "example.ts.net"
    me = st["self"]
    assert me["id"] == "homelab" and me["self"] and me["online"] and me["ip"] == "100.64.0.1"
    assert me["lastSeen"] is None            # the zero time is dropped
    peers = {p["id"]: p for p in st["peers"]}
    assert set(peers) == {"vps-fra", "my-laptop", "old-phone", "localhost"}
    assert peers["my-laptop"]["kind"] == "mac" and peers["my-laptop"]["host"] == "My Laptop"
    assert peers["old-phone"]["online"] is False and peers["old-phone"]["kind"] == "ios"
    assert peers["vps-fra"]["relay"] == "fra"


def test_parse_ping_direct():
    out = ("pong from vps-fra (100.64.1.1) via 203.0.113.5:41641 in 21ms\n"
           "pong from vps-fra (100.64.1.1) via 203.0.113.5:41641 in 19ms\n")
    r = tailscale.parse_ping(out)
    assert r == {"times": [21.0, 19.0], "route": "direct", "derp": None}


def test_parse_ping_derp_and_spaces_in_host():
    out = "pong from My Laptop (100.64.0.10) via DERP(lax) in 212ms\npong from My Laptop (100.64.0.10) via DERP(lax) in 230.5ms\n"
    r = tailscale.parse_ping(out)
    assert r["times"] == [212.0, 230.5] and r["route"] == "relay" and r["derp"] == "DERP(lax)"


def test_parse_ping_peer_relay():
    r = tailscale.parse_ping("pong from db (100.64.0.9) via peer-relay(198.51.100.7:40000:vni:12) in 48ms")
    assert r["route"] == "relay" and r["derp"] == "peer relay" and r["times"] == [48.0]


def test_parse_ping_timeout():
    r = tailscale.parse_ping("timeout waiting for ping reply\n")
    assert r == {"times": [], "route": None, "derp": None}


def test_node_id_fallback():
    assert tailscale.node_id({"DNSName": "", "HostName": "Jane's iPhone"}) == "jane-s-iphone"
