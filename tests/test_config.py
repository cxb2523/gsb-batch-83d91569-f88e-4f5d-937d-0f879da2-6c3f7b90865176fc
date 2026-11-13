import json

import pytest

from meshatlas import config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MESHATLAS_CONFIG", raising=False)
    monkeypatch.setattr(config, "SEARCH_PATHS", ["meshatlas.toml", "meshatlas.json"])
    cfg, path = config.load()
    assert path is None
    assert cfg["server"]["port"] == 8765 and cfg["collect"]["mesh"] is True and cfg["nodes"] == {}


def test_json_merge(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"server": {"port": 9000}, "nodes": {"nas": {"ssh": "root@nas"}},
                             "locations": {"home": {"lat": 1, "lon": 2}}}))
    cfg, path = config.load(str(p))
    assert path == p
    assert cfg["server"]["port"] == 9000 and cfg["server"]["host"] == "auto"
    assert cfg["nodes"]["nas"]["ssh"] == "root@nas"


@pytest.mark.skipif(config.tomllib is None, reason="needs Python 3.11+")
def test_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[display]\ntitle = "LAB"\n[[external]]\nid = "pub"\naddress = "203.0.113.1"\n')
    cfg, _ = config.load(str(p))
    assert cfg["display"]["title"] == "LAB" and cfg["display"]["subtitle"] == "TAILNET OPS"
    assert cfg["external"][0]["id"] == "pub"


@pytest.mark.parametrize("raw, msg", [
    ({"bogus": {}}, "unknown top-level"),
    ({"locations": {"x": {"lat": "a", "lon": 1}}}, "numeric lat"),
    ({"external": [{"id": "x"}]}, "needs id and address"),
    ({"kuma": {"url": "http://k"}}, "url and slug"),
])
def test_validation(tmp_path, raw, msg):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(config.ConfigError, match=msg):
        config.load(str(p))
