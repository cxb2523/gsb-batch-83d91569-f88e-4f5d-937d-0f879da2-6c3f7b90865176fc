"""Per-document batch results: terminal summary and the JSON report."""

import json

import pytest

A = "https://www.scribd.com/document/111/Report"
A_AGAIN = "https://de.scribd.com/document/111/Report"
B = "https://www.scribd.com/document/222/Report"
C = "https://www.scribd.com/document/333/Other"
SECRET = "https://www.scribd.com/document/444/Secret?secret_password=TOPSECRET"
INVALID = "https://example.com/document/not-scribd"
REPORT_NAME = "scribd-report.json"


def fake_downloader(failing_ids=()):
    """
    Build a fake download_document that writes real files and returns them.

    It follows the real naming rule: <base_name>.<format> inside output_dir.
    """
    calls = []

    def fake(job, formats, output_dir):
        calls.append(job["info"]["doc_id"])
        if job["info"]["doc_id"] in failing_ids:
            raise RuntimeError(
                "No printable document pages were detected.\n"
                "  Reason: The document was not found."
            )

        saved = {}
        for fmt in formats:
            path = f"{output_dir}/{job['base_name']}.{fmt}"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"content for {job['info']['doc_id']} as {fmt}\n")
            saved[fmt] = path
        return saved

    fake.calls = calls
    return fake


def read_report(out_dir):
    report_path = out_dir / REPORT_NAME
    assert report_path.is_file()
    return json.loads(report_path.read_text(encoding="utf-8"))


def summary_lines(output):
    return output.split("Summary: ", 1)[1].splitlines()


def test_batch_reports_successes_failures_and_invalid_links(
    sd, monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "out"
    fake = fake_downloader(failing_ids={"333"})
    monkeypatch.setattr(sd, "download_document", fake)

    # Two successes (one repeated id), one failure, one invalid link.
    with pytest.raises(SystemExit) as exit_info:
        sd.main(
            [A, A_AGAIN, B, C, INVALID, "--format", "pdf,txt", "-o", str(out_dir)]
        )

    assert exit_info.value.code == 1
    # The duplicate document id is downloaded once; the failure stops nothing.
    assert fake.calls == ["111", "222", "333"]

    output = capsys.readouterr().out
    assert "Summary: 2 succeeded, 1 failed, 1 invalid link(s) skipped." in output
    assert f"Not a valid Scribd document URL: {INVALID}" in output
    assert f"Report: {out_dir / REPORT_NAME}" in output

    # Every successful document reports its id, final base name and real paths.
    assert "  OK 111: Report" in output
    assert f"    pdf -> {out_dir / 'Report.pdf'}" in output
    assert f"    txt -> {out_dir / 'Report.txt'}" in output
    # Same title, different id -> the renamed file is what gets reported.
    assert "  OK 222: Report-222" in output
    assert f"    pdf -> {out_dir / 'Report-222.pdf'}" in output
    assert f"    txt -> {out_dir / 'Report-222.txt'}" in output
    assert "OK 333" not in output

    # The failed document reports id, base name and only the first reason line.
    failed_lines = [line for line in summary_lines(output) if line.startswith("  FAILED")]
    assert failed_lines == [
        "  FAILED Other: No printable document pages were detected. [doc id 333]"
    ]

    # Reported paths point at the files that really exist.
    for base in ("Report", "Report-222"):
        for fmt in ("pdf", "txt"):
            assert (out_dir / f"{base}.{fmt}").is_file()

    report = read_report(out_dir)
    assert report["summary"] == {
        "documents": 3,
        "succeeded": 2,
        "failed": 1,
        "invalid_links": 1,
    }
    assert report["formats"] == ["pdf", "txt"]
    assert report["invalid_links"] == [INVALID]

    by_id = {entry["doc_id"]: entry for entry in report["results"]}
    assert by_id["111"]["base_name"] == "Report"
    assert by_id["111"]["status"] == "success"
    assert set(by_id["111"]["files"]) == {"pdf", "txt"}
    assert by_id["222"]["base_name"] == "Report-222"
    assert by_id["222"]["files"]["pdf"] == str((out_dir / "Report-222.pdf").resolve())
    assert by_id["333"]["status"] == "failed"
    assert by_id["333"]["reason"] == "No printable document pages were detected."
    assert "files" not in by_id["333"]

    # The JSON files match the terminal lines exactly.
    for entry in report["results"]:
        if entry["status"] == "success":
            for fmt, path in entry["files"].items():
                filename = path.replace("\\", "/").rsplit("/", 1)[-1]
                assert (out_dir / filename).is_file()
                assert f"{fmt} -> {out_dir / filename}" in output


def test_batch_report_never_leaks_secret_password(sd, monkeypatch, tmp_path, capsys):
    out_dir = tmp_path / "out"

    def failing_for_secret(job, formats, output_dir):
        raise RuntimeError(
            "Scribd footer page https://www.scribd.com/embeds/444/content"
            "?secret_password=TOPSECRET failed."
        )

    monkeypatch.setattr(sd, "download_document", failing_for_secret)

    with pytest.raises(SystemExit) as exit_info:
        sd.main([A, SECRET, INVALID, "--format", "pdf", "-o", str(out_dir)])
    assert exit_info.value.code == 1

    output = capsys.readouterr().out
    report_text = (out_dir / REPORT_NAME).read_text(encoding="utf-8")

    assert "TOPSECRET" not in output
    assert "TOPSECRET" not in report_text
    assert "secret_password=REDACTED" in report_text
    assert "Not a valid Scribd document URL" in output
    report = json.loads(report_text)
    assert report["summary"]["invalid_links"] == 1


def test_batch_counts_every_invalid_link_and_still_exports_valid_ones(
    sd, monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sd, "download_document", fake_downloader())
    bad = ["https://example.com/a", "https://example.com/b"]

    with pytest.raises(SystemExit) as exit_info:
        sd.main([A, *bad, "--format", "pdf", "-o", str(out_dir)])
    assert exit_info.value.code == 1

    output = capsys.readouterr().out
    assert "Summary: 1 succeeded, 0 failed, 2 invalid link(s) skipped." in output
    assert "https://example.com/a" in output
    assert "https://example.com/b" in output
    assert (out_dir / "Report.pdf").is_file()

    report = read_report(out_dir)
    assert report["invalid_links"] == bad
    assert report["summary"]["succeeded"] == 1


def test_batch_report_records_a_failed_document_without_paths(
    sd, monkeypatch, tmp_path
):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        sd, "download_document", fake_downloader(failing_ids={"111"})
    )

    with pytest.raises(SystemExit) as exit_info:
        sd.main([A, B, "--format", "pdf", "-o", str(out_dir)])
    assert exit_info.value.code == 1

    report = read_report(out_dir)
    assert report["summary"]["failed"] == 1
    assert report["results"][0]["status"] == "failed"
    assert "files" not in report["results"][0]
    # The failed document wrote nothing; the successful one is still there.
    assert not (out_dir / "Report.pdf").exists()
    assert (out_dir / "Report-222.pdf").is_file()
    assert report["results"][1]["files"]["pdf"] == str(
        (out_dir / "Report-222.pdf").resolve()
    )


def test_single_document_run_keeps_original_output(sd, monkeypatch, tmp_path, capsys):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sd, "download_document", fake_downloader())

    assert sd.main([A, "--format", "pdf", "-o", str(out_dir)]) is None

    output = capsys.readouterr().out
    assert "Summary: " not in output
    assert not (out_dir / REPORT_NAME).exists()
