import http.client
import threading

import pytest

from meshatlas.server import make_handler, serve


@pytest.fixture
def server(request):
    token = getattr(request, "param", "")
    httpd = serve("127.0.0.1", 0, make_handler(None, token=token, demo=True))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_static_and_config(server):
    st, h, body = get(server, "/")
    assert st == 200 and b"MeshAtlas" in body and "default-src 'self'" in h["Content-Security-Policy"]
    st, _, body = get(server, "/config.js")
    assert st == 200 and b'"demo": true' in body
    assert get(server, "/../pyproject.toml")[0] == 404
    assert get(server, "/healthz")[0] == 200


@pytest.mark.parametrize("server", ["s3cret"], indirect=True)
def test_token(server):
    assert get(server, "/")[0] == 401
    assert get(server, "/healthz")[0] == 200
    st, h, _ = get(server, "/?token=s3cret")
    assert st == 302 and "meshatlas_token=s3cret" in h["Set-Cookie"] and h["Location"] == "/"
    assert get(server, "/", {"Cookie": "meshatlas_token=s3cret"})[0] == 200
    assert get(server, "/", {"Authorization": "Bearer s3cret"})[0] == 200
    assert get(server, "/", {"Cookie": "meshatlas_token=nope"})[0] == 401
