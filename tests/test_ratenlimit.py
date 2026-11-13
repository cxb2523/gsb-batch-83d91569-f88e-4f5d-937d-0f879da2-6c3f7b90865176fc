"""Ratenlimit und Fehlerverteilung (13.11.2026) über den echten Einstieg python -m app.sammler (runpy, gleicher Prozess)
mit nachgebautem GitHub hinter urlopen — keine echten Zugangsdaten, GITHUB_TOKEN ist ein Platzhalter.
(a) Ratenlimit innerhalb der Frist: holen wartet bis zum Reset und fragt erneut an, der Lauf gelingt, und laeufe.gewartet,
    lauf.json und /lauf/status tragen die Wartesekunden; die Alterszeile nennt das Warten.
(b) Ratenlimit jenseits der Frist: globaler Fehler ohne Warten, das schon Geholte (Commits, Prüfungen) bleibt, keine
    laeufe-Zeile (kein falscher Erfolg), lauf.json trägt Exit 1; der nächste Lauf setzt fort und wird zum vollen Erfolg.
(c) 404, 403 ohne Limit und 422 einzelner Repos: nur diese Repos werden übersprungen und in repos.fehler vermerkt, die
    übrigen laden normal; der Lauf ist ein Teilerfolg (laeufe.teilweise, lauf.json), die abgewiesenen Repos sind abfragbar.
(d) Erstimport nach Seite 2 am Ratenlimit abgebrochen: import_seite 3 ist festgeschrieben, keine laeufe-Zeile; der nächste
    Lauf beginnt bei Seite 3 (gegen den festgehaltenen Kopf), nie wieder bei Seite 1, und schliesst den Import ab.
python3 -m tests.test_ratenlimit"""
import email.message
import io
import json
import os
import runpy
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

os.environ["GITPULS_DB"] = os.path.join(tempfile.mkdtemp(), "ratenlimit.db")   # vor dem Import, db.DB liest die Variable beim Laden
os.environ.setdefault("GITPULS_ADRESSEN", "dev@fernwerk-studio.example")
os.environ.setdefault("GITPULS_SPRACHE", "de")   # die Alterszeile unten steht auf Deutsch
os.environ["GITPULS_FORMAT"] = "de-CH"
os.environ["TZ"] = "Europe/Zurich"   # die Zone setzt der Test selbst (10.10.2026, Audit S28): grün unter jeder TZ der Shell
os.environ["GITHUB_TOKEN"] = "nachbau-token"   # Platzhalter, der Nachbau prüft ihn nicht
from app import db, web  # noqa: E402

DATUM = "2026-11-10T12:00:00Z"
WELT, REGEL, PROTOKOLL = {}, None, []


def antwort(daten, **kopf):
    r = io.BytesIO(json.dumps(daten).encode())
    m = email.message.Message()
    for k, v in kopf.items():
        m[k.replace("_", "-")] = str(v)
    r.headers = m
    return r


def http_fehler(req, code, meldung, **kopf):
    m = email.message.Message()
    for k, v in kopf.items():
        m[k.replace("_", "-")] = str(v)
    return urllib.error.HTTPError(req.full_url, code, meldung, m, io.BytesIO(json.dumps({"message": meldung}).encode()))


def commit(sha):
    return {"sha": sha, "commit": {"author": {"date": DATUM, "email": "dev@fernwerk-studio.example"}, "message": "Arbeit"},
            "author": None, "parents": [{"sha": "p"}]}


def urlopen_nachbau(req, timeout=None):
    """Das nachgebaute GitHub: Seiten aus WELT, Fehler aus REGEL, jede Anfrage im PROTOKOLL."""
    u = urlsplit(req.full_url)
    pfad, q = u.path.lstrip("/"), {k: v[0] for k, v in parse_qs(u.query).items()}
    PROTOKOLL.append((pfad, q))
    if REGEL:
        aus = REGEL(pfad, q)
        if aus:
            code, meldung, kopf = aus
            raise http_fehler(req, code, meldung, **kopf)
    if pfad == "rate_limit":
        return antwort({})
    if pfad == "user/repos":
        return antwort([{"full_name": n, "id": i + 1, "archived": False, "pushed_at": "2026-11-01T00:00:00Z",
                         "default_branch": "main", "language": "Python", "html_url": f"https://github.com/{n}"} for i, n in enumerate(WELT)])
    teile = pfad.split("/")
    fn = "/".join(teile[1:3])
    if len(teile) == 4 and teile[-1] == "commits":   # Commitliste, 100 je Seite wie der Sammler
        seite = int(q.get("page", "1"))
        alle = WELT[fn]
        kopf = {"Link": f'<https://api.github.com/repos/{fn}/commits?page={seite + 1}>; rel="next"'} if seite * 100 < len(alle) else {}
        return antwort([commit(s) for s in alle[(seite - 1) * 100:seite * 100]], **kopf)
    if len(teile) == 5 and teile[-2] == "commits":   # Commit-Detail (Kopf des Erstimports, Codezeilen)
        return antwort({"files": [], "parents": [{}], "commit": {"author": {"date": DATUM}}})
    if teile[-1] == "branches":
        return antwort([])
    if "actions" in teile:
        return antwort({"total_count": 0, "workflow_runs": []})
    if "dependabot" in teile:
        return antwort([])
    raise AssertionError(pfad)


urllib.request.urlopen = urlopen_nachbau


def neue_db():
    """Jeder Fall eine frische Datenbank in einem frischen Ordner; lauf.json und token.json liegen daneben."""
    d = Path(tempfile.mkdtemp())
    db.DB = d / "probe.db"
    web.LAUF, web.TOKEN = d / "lauf.json", d / "token.json"


def lauf():
    """Ein Lauf über den echten Einstieg (python -m app.sammler), im selben Prozess mit dem Nachbau. Liefert den Exitcode."""
    argv, sys.argv = sys.argv, ["app.sammler"]
    try:
        runpy.run_module("app.sammler", run_name="__main__")
        return 0
    except SystemExit as e:   # GitHubFehler ist SystemExit mit Text, FristAbgelaufen wird zu sys.exit(1)
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = argv


def lauf_json():
    return json.loads((db.DB.parent / "lauf.json").read_text())


def eine(sql, *args):
    with db.verbinden() as c:
        return c.execute(sql, args).fetchone()[0]


def zeile1(sql, *args):
    with db.verbinden() as c:
        return tuple(c.execute(sql, args).fetchone())


def seiten_abfragen(fn):
    """Angefragte Seiten der Commitliste eines Repos, aus dem Protokoll."""
    return [q.get("page", "1") for pfad, q in PROTOKOLL if pfad == f"repos/{fn}/commits"]


# (a) Ratenlimit innerhalb der Frist: gewartet und erneut angefragt, der Lauf gelingt.
neue_db()
WELT = {"o/eins": ["a1"]}
versuche = [0]


def regel_a(pfad, q):
    if pfad == "repos/o/eins/commits" and not versuche[0]:
        versuche[0] += 1
        return (403, "API rate limit exceeded for user ID 1.", {"X_RateLimit_Remaining": 0, "Retry_After": 2})


REGEL = regel_a
assert lauf() == 0, "Warten innerhalb der Frist: der Lauf gelingt"
REGEL = None
assert versuche[0] == 1 and seiten_abfragen("o/eins") == ["1", "1"], ("dieselbe Anfrage nach dem Warten erneut", seiten_abfragen("o/eins"))
assert zeile1("SELECT teilweise, gewartet FROM laeufe") == (0, 2), "voller Erfolg mit zwei Wartesekunden in der Laufzeile"
lj = lauf_json()
assert lj["exit"] == 0 and lj["teilweise"] == 0 and lj["gewartet"] == 2, lj
assert web.lauf_status()["gewartet"] == 2, web.lauf_status()
with db.verbinden() as c:
    zeile_html = web.stand_block(c)
assert "davon 2 s am Ratenlimit gewartet" in zeile_html, zeile_html
assert eine("SELECT COUNT(*) FROM commits WHERE repo = 'o/eins'") == 1

# (b) Ratenlimit jenseits der Frist: kein Warten, globaler Fehler, das Geholte bleibt, der nächste Lauf setzt fort.
neue_db()
WELT = {"o/a": ["b1"], "o/b": ["b2"]}


def regel_b(pfad, q):
    if pfad == "repos/o/b/actions/runs":   # das Limit trifft erst beim Prüfen: Commits und Zweige beider Repos sind schon geholt
        return (403, "API rate limit exceeded for user ID 1.", {"X_RateLimit_Remaining": 0, "X_RateLimit_Reset": int(time.time()) + 3600})


REGEL = regel_b
PROTOKOLL.clear()
assert lauf() == 1, "der Reset liegt jenseits der Frist: der Lauf endet mit dem globalen Fehler"
REGEL = None
assert eine("SELECT COUNT(*) FROM laeufe") == 0, "ein abgebrochener Lauf schreibt keine Laufzeile"
assert eine("SELECT COUNT(*) FROM commits") == 2, "die geholten Commits beider Repos bleiben"
assert eine("SELECT COUNT(*) FROM pruefungen WHERE repo = 'o/a'") == 1 and eine("SELECT COUNT(*) FROM pruefungen WHERE repo = 'o/b'") == 0, \
    "die Prüfung des fertigen Repos bleibt, die des getroffenen fehlt"
lj = lauf_json()
assert lj["exit"] == 1 and "403" in lj["fehler"] and lj["gewartet"] == 0, ("kein Warten verbucht, der Fehler steht im Laufstatus", lj)
assert lauf() == 0, "der nächste Lauf setzt fort und gelingt"
assert eine("SELECT COUNT(*) FROM laeufe") == 1 and zeile1("SELECT teilweise, gewartet FROM laeufe") == (0, 0)
assert eine("SELECT COUNT(*) FROM pruefungen") == 2, "beide Repos geprüft"
lj = lauf_json()
assert lj["exit"] == 0 and lj["teilweise"] == 0 and lj["gewartet"] == 0, lj

# (c) 404, 403 ohne Limit und 422 einzelner Repos: nur diese werden übersprungen, der Rest lädt normal.
neue_db()
WELT = {"o/vier": [], "o/drei": [], "o/zwei": [], "o/eins": ["c1"]}
FEHLER_C = {"o/vier": (404, "Not Found", {}), "o/drei": (403, "Resource not accessible by personal access token", {}),
            "o/zwei": (422, "Validation Failed", {})}


def regel_c(pfad, q):
    teile = pfad.split("/")
    if len(teile) == 4 and teile[-1] == "commits":
        return FEHLER_C.get("/".join(teile[1:3]))


REGEL = regel_c
assert lauf() == 0, "Fehler einzelner Repos beenden den Lauf nicht"
REGEL = None
start = eine("SELECT gestartet_utc FROM laeufe")
assert zeile1("SELECT teilweise, gewartet FROM laeufe") == (3, 0), "drei abgewiesene Repos: Teilerfolg, kein Warten"
lj = lauf_json()
assert lj["exit"] == 0 and lj["teilweise"] == 3, lj
with db.verbinden() as c:
    abgewiesen = dict(c.execute("SELECT repo, fehler FROM repos WHERE gesehen = ? AND fehler IS NOT NULL", (start,)))
assert set(abgewiesen) == {"o/vier", "o/drei", "o/zwei"}, ("die abgewiesenen Repos stehen abfragbar in der Datenbank", abgewiesen)
assert abgewiesen["o/vier"].startswith("404") and abgewiesen["o/drei"].startswith("403") and abgewiesen["o/zwei"].startswith("422"), abgewiesen
assert eine("SELECT fehler FROM repos WHERE repo = 'o/eins'") is None and eine("SELECT COUNT(*) FROM commits WHERE repo = 'o/eins'") == 1
assert eine("SELECT COUNT(*) FROM pruefungen") == 4, "CI und Sicherheit laufen auch für die übersprungenen Repos"

# (d) Erstimport nach Seite 2 am Ratenlimit abgebrochen: der nächste Lauf beginnt bei Seite 3.
neue_db()
WELT = {"o/gross": [f"g{i:03d}" for i in range(250)]}   # drei Seiten: 100, 100, 50


def regel_d(pfad, q):
    if pfad == "repos/o/gross/commits" and q.get("page") == "3":
        return (403, "API rate limit exceeded for user ID 1.", {"X_RateLimit_Remaining": 0, "X_RateLimit_Reset": int(time.time()) + 3600})


REGEL = regel_d
PROTOKOLL.clear()
assert lauf() == 1, "der Erstimport bricht an Seite 3 ab"
REGEL = None
assert seiten_abfragen("o/gross") == ["1", "2", "3"], seiten_abfragen("o/gross")
assert eine("SELECT COUNT(*) FROM commits") == 200 and eine("SELECT import_seite FROM repos") == 3, \
    "zwei Seiten festgeschrieben, die nächste Seite steht im Abrufzustand"
assert eine("SELECT COUNT(*) FROM laeufe") == 0, "der unterbrochene Import ist kein erfolgreicher Lauf"
assert lauf_json()["exit"] == 1
PROTOKOLL.clear()
assert lauf() == 0, "der nächste Lauf schliesst den Import ab"
assert seiten_abfragen("o/gross") == ["3"], ("Fortsetzung bei der festgeschriebenen Seite, nicht von vorn", seiten_abfragen("o/gross"))
assert [q.get("sha") for pfad, q in PROTOKOLL if pfad == "repos/o/gross/commits"] == ["g000"], "gegen den beim Start festgehaltenen Kopf"
assert eine("SELECT COUNT(*) FROM commits") == 250
with db.verbinden() as c:
    assert c.execute("SELECT import_seite FROM repos").fetchone()[0] is None and c.execute("SELECT abgerufen_utc FROM repos").fetchone()[0], \
        "der Import gilt als abgeschlossen: kein Seitenstand mehr, der Abrufstand steht"
assert eine("SELECT teilweise FROM laeufe") == 0, "der abschliessende Lauf ist ein voller Erfolg"
print("ok: Ratenlimit in der Frist wartet und wiederholt (Wartezeit in laeufe, lauf.json, /lauf/status und Alterszeile); jenseits der Frist"
      " bleibt das Geholte und der nächste Lauf setzt fort; 404/403/422 überspringen nur ihr Repo, abfragbar in repos.fehler;"
      " Erstimport nach Seite 2 abgebrochen setzt bei Seite 3 fort")
