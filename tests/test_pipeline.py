"""End-to-end pipeline runs with fake sources: no network."""
from __future__ import annotations

from datetime import date

from smt import checks, pipeline, store, universe
from tests.conftest import fake_master


def test_refresh_loads_everything(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=2, src=fake_sources)
    assert rep.verified == 21 and not rep.mismatched and not rep.errors
    con = store.connect(db)
    h = store.holdings(con)
    # every holdings fund, including DSP Midcap (spelt 'Mid Cap' in the file); untracked schemes ignored
    assert set(h["scheme_code"]) == {f.scheme_code for f in universe.with_holdings()}
    # the window is the 2 most recent months that have ended: Sep and Aug
    assert sorted(h["as_of"].dt.month.unique()) == [8, 9]
    assert h.loc[h["isin"] == "INE522F01014", "cap_class"].iloc[0] == "Mid Cap"   # AMFI list joined
    log = store.refresh_log(con)
    assert {"universe", "nav", "market_cap", "holdings:ppfas", "holdings:dsp"} <= set(log["job"])
    assert (log["status"] == "ok").all()
    con.close()


def test_month_ends_is_a_trailing_window_that_excludes_the_running_month():
    assert pipeline.month_ends(date(2026, 10, 6), 3) == [date(2026, 9, 30), date(2026, 8, 31), date(2026, 7, 31)]
    # On the last day of a month that month's own disclosure is due, so it is included.
    assert pipeline.month_ends(date(2026, 10, 31), 2) == [date(2026, 10, 31), date(2026, 9, 30)]
    assert pipeline.month_ends(date(2026, 1, 15), 3) == [date(2025, 12, 31), date(2025, 11, 30), date(2025, 10, 31)]
    assert pipeline.month_ends(date(2026, 10, 6), 0) == []


def test_wrong_scheme_code_is_caught_and_excluded(tmp_path, fake_sources):
    fake_sources.scheme_master = lambda: fake_master(mismatch="119071")
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=1, src=fake_sources)
    assert rep.verified == 20 and rep.mismatched and "119071" in rep.mismatched[0]
    con = store.connect(db)
    assert "119071" not in set(store.funds(con)["scheme_code"])           # excluded from analytics
    assert "119071" not in set(store.nav_wide(con).columns)
    result = checks.run(con).set_index("check")
    assert result.loc["Scheme codes match AMFI names", "status"] == "fail"
    con.close()


def test_downloads_are_cached_and_reruns_are_idempotent(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=2, src=fake_sources)
    first = {n: c.downloads for n, c in fake_sources.connectors.items()}
    con = store.connect(db)
    rows_before = len(store.holdings(con))
    files_before = store.disclosure_files(con)
    pipeline.refresh(db, months=2, src=fake_sources)
    assert {n: c.downloads for n, c in fake_sources.connectors.items()} == first   # served from raw_dir
    assert len(store.holdings(con)) == rows_before                                  # no duplicates
    files_after = store.disclosure_files(con)
    assert len(files_after) == len(files_before)                                    # one row per AMC-month
    assert files_after["fetched_at"].min() >= files_before["fetched_at"].min()
    assert any((fake_sources.raw_dir / "dsp").iterdir())
    con.close()


def test_one_failing_fund_does_not_stop_the_rest(tmp_path, fake_sources):
    good = fake_sources.nav_history

    def flaky(code):
        if code == "118955":
            raise ConnectionError("timeout")
        return good(code)

    fake_sources.nav_history = flaky
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=1, src=fake_sources, holdings=False)
    assert any("118955" in e for e in rep.errors)
    con = store.connect(db)
    assert len(store.nav_wide(con).columns) == 20
    assert store.refresh_log(con).set_index("job").loc["nav", "status"] == "warning"
    con.close()


def test_market_cap_falls_back_to_isin_prefix_after_a_split(tmp_path, fake_sources, market_cap_df):
    # HDFC Bank gets a new ISIN serial after a split; the AMFI list still has the old one.
    fake_sources.market_cap = lambda: ("31Dec2025", market_cap_df.replace({"INE040A01034": "INE040A01026"}))
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=1, src=fake_sources)
    con = store.connect(db)
    h = store.holdings(con)
    assert (h.loc[h["isin"] == "INE040A01034", "cap_class"] == "Large Cap").all()
    con.close()


def test_source_outage_keeps_last_good_market_cap_list(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=1, src=fake_sources)

    def down():
        raise RuntimeError("AMFI website unreachable: ConnectionError")

    fake_sources.market_cap = down
    rep = pipeline.refresh(db, months=1, src=fake_sources)
    assert any("market_cap" in e for e in rep.errors)
    con = store.connect(db)
    assert store.market_cap_label(con) == "31Dec2025"            # previous list kept
    assert store.refresh_log(con).iloc[0:5].set_index("job").loc["market_cap", "status"] == "warning"
    con.close()


def test_checks_pass_on_clean_data(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=2, src=fake_sources)
    con = store.connect(db)
    res = checks.run(con)
    assert not (res["status"] == "fail").any(), res.to_string()
    con.close()


# --------------------------------------------------------------------------- #
# Every month gets an outcome: present, missing, failed, or nothing matched
# --------------------------------------------------------------------------- #
def files_for(con, connector: str) -> dict[str, str]:
    df = store.disclosure_files(con)
    return dict(zip(df.loc[df["connector"] == connector, "as_of"], df.loc[df["connector"] == connector, "status"],
                    strict=True))


def test_every_month_in_the_window_gets_a_row(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=4, src=fake_sources)   # window: Sep, Aug, Jul, Jun
    con = store.connect(db)
    rows = store.disclosure_files(con)
    # FakeConnector publishes Sep, Aug and Jun, never Jul or May: Jul must still appear.
    assert set(rows["as_of"]) >= {"2026-09-30", "2026-08-31", "2026-07-31", "2026-06-30"}
    for connector in ("ppfas", "dsp"):
        got = files_for(con, connector)
        assert got == {
            "2026-09-30": "ok", "2026-08-31": "ok",
            "2026-07-31": "missing", "2026-06-30": "ok",
        }, connector
    missing = rows[rows["status"] == "missing"]
    assert len(missing) == 2 and missing["url"].isna().all()                  # url optional when absent
    assert set(missing["as_of"]) == {"2026-07-31"}
    assert (rows.loc[rows["status"] == "ok", "schemes_matched"] > 0).all()
    con.close()


def test_download_failure_and_empty_parse_are_reported_and_do_not_stop_other_months(tmp_path, fake_sources):
    dsp = fake_sources.connectors["dsp"]
    dsp.months = (9, 8, 7)         # a file exists for all three months...
    dsp.fail_download = {8}        # ...August's download raises...
    dsp.empty = {7}                # ...and July's file parses to no tracked scheme.
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=3, src=fake_sources)   # window: Sep, Aug, Jul

    con = store.connect(db)
    assert files_for(con, "dsp") == {
        "2026-09-30": "ok", "2026-08-31": "download_failed", "2026-07-31": "no_schemes",
    }
    assert files_for(con, "ppfas") == {"2026-09-30": "ok", "2026-08-31": "ok", "2026-07-31": "missing"}

    # the month that did load is in the database, and the failures surface in the report
    h = store.holdings(con)
    assert set(h["scheme_code"]) == {f.scheme_code for f in universe.with_holdings()}
    assert any("dsp 2026-08-31: download failed" in e for e in rep.errors)
    assert any("dsp 2026-07-31" in e for e in rep.errors)

    log = store.refresh_log(con).set_index("job")
    assert log.loc["holdings:dsp", "status"] == "warning"
    msg = log.loc["holdings:dsp", "message"]
    assert "2026-08-31: download failed" in msg and "2026-07-31" in msg
    con.close()


def test_a_failing_file_does_not_lose_the_months_file_level_detail(tmp_path, fake_sources):
    # Every month with a file gets a status, and a failed download keeps the URL and reason.
    dsp = fake_sources.connectors["dsp"]
    dsp.fail_download = {9, 8}
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=2, src=fake_sources)
    con = store.connect(db)
    rows = store.disclosure_files(con)
    bad = rows[(rows["connector"] == "dsp") & (rows["status"] == "download_failed")]
    assert len(bad) == 2
    assert bad["url"].notna().all()                  # the attempted URL is still recorded
    assert bad["detail"].str.contains("503").all()
    con.close()


def test_discover_failure_still_yields_one_outcome_per_month(tmp_path, fake_sources):
    def down():
        raise ConnectionError("AMC page unreachable")

    fake_sources.connectors["dsp"].discover = lambda html=None: down()
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=2, src=fake_sources)
    assert any("dsp" in e for e in rep.errors)
    con = store.connect(db)
    got = files_for(con, "dsp")
    assert got == {"2026-09-30": "discover_failed", "2026-08-31": "discover_failed"}
    # PPFAS is unaffected
    assert files_for(con, "ppfas") == {"2026-09-30": "ok", "2026-08-31": "ok"}
    log = store.refresh_log(con).set_index("job")
    assert log.loc["holdings:dsp", "status"] == "warning"
    assert "could not list files" in log.loc["holdings:dsp", "message"]
    con.close()


def test_all_months_present_is_ok_and_a_missing_month_is_warned(tmp_path, fake_sources):
    fake_sources.connectors["dsp"].months = (9, 8, 7)
    db = tmp_path / "smt.db"
    rep = pipeline.refresh(db, months=3, src=fake_sources)
    con = store.connect(db)
    # DSP has every month; PPFAS has no July file, so its job warns and names July
    assert rep.errors == ["ppfas 2026-07-31: no file found on the page"]
    log = store.refresh_log(con).set_index("job")
    assert log.loc["holdings:dsp", "status"] == "ok"
    assert log.loc["holdings:ppfas", "status"] == "warning"
    assert "2026-07-31" in log.loc["holdings:ppfas", "message"]
    con.close()


def test_repeated_refresh_overwrites_outcomes_instead_of_piling_up_rows(tmp_path, fake_sources):
    db = tmp_path / "smt.db"
    pipeline.refresh(db, months=3, src=fake_sources)
    con = store.connect(db)
    first = store.disclosure_files(con).sort_values(["connector", "as_of"]).reset_index(drop=True)
    assert len(first) == 6                                        # 2 AMCs x 3 months

    # A fresh cache directory makes the next refresh download again (the raw cache
    # would otherwise serve the copy kept by the first run).
    fake_sources.raw_dir = tmp_path / "raw2"
    fake_sources.connectors["dsp"].fail_download = {8}
    pipeline.refresh(db, months=3, src=fake_sources)
    second = store.disclosure_files(con).sort_values(["connector", "as_of"]).reset_index(drop=True)
    assert len(second) == len(first)                              # overwritten, not appended
    changed = first["status"] != second["status"]
    assert changed.sum() == 1 and second.loc[changed, "status"].tolist() == ["download_failed"]

    # and once the source recovers, the same row goes back to ok
    fake_sources.raw_dir = tmp_path / "raw3"
    fake_sources.connectors["dsp"].fail_download = set()
    pipeline.refresh(db, months=3, src=fake_sources)
    third = store.disclosure_files(con).sort_values(["connector", "as_of"]).reset_index(drop=True)
    assert len(third) == len(first)
    assert third.loc[third["connector"] == "dsp", "status"].tolist() == ["missing", "ok", "ok"]
    con.close()


def test_recording_a_second_outcome_for_the_same_month_replaces_the_first(tmp_path):
    con = store.connect(tmp_path / "smt.db")
    store.record_file(con, "dsp", "2026-09-30", status="missing")
    store.record_file(con, "dsp", "2026-09-30", url="https://x.test/a.zip", size=10,
                      matched=3, status="ok")
    rows = store.disclosure_files(con)
    assert len(rows) == 1
    assert rows.iloc[0]["status"] == "ok" and rows.iloc[0]["url"] == "https://x.test/a.zip"
    con.close()


def test_old_disclosure_table_is_migrated_to_one_row_per_month(tmp_path):
    import sqlite3
    db = tmp_path / "smt.db"
    raw = sqlite3.connect(db)
    raw.executescript("""
        CREATE TABLE disclosure_files (url TEXT PRIMARY KEY, connector TEXT NOT NULL, as_of TEXT NOT NULL,
            fetched_at TEXT NOT NULL, bytes INTEGER, schemes_matched INTEGER, status TEXT NOT NULL);
        INSERT INTO disclosure_files VALUES ('u1','ppfas','2026-09-30','2026-10-01 00:00:00',100,1,'ok');
        INSERT INTO disclosure_files VALUES ('u2','ppfas','2026-09-30','2026-10-01 00:00:01',200,2,'ok');
    """)
    raw.commit()
    raw.close()
    con = store.connect(db)
    rows = store.disclosure_files(con)
    assert len(rows) == 1
    assert rows.iloc[0]["as_of"] == "2026-09-30" and rows.iloc[0]["schemes_matched"] == 3
    con.close()
