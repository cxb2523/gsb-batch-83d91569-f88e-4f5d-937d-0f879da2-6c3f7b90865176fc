"""Тесты пакетного сбора CSV (python_analytics.collect)."""

import json
import subprocess
import sys

import pytest

from python_analytics.collect import (
    MANIFEST_NAME,
    STATUS_EXISTING,
    STATUS_FAILED,
    STATUS_SUCCESS,
    collect_csv,
)
from python_analytics.pipeline import run_pipeline


@pytest.fixture()
def source_dir(tmp_path):
    """Директория-источник: нормальный файл, пустой и файл только с заголовком."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "good.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (src / "empty.csv").write_text("", encoding="utf-8")
    (src / "header_only.csv").write_text("a,b\n", encoding="utf-8")
    return src


def _by_name(manifest):
    return {entry["source_file"]: entry for entry in manifest["files"]}


def test_first_run_records_all_outcomes(source_dir, tmp_path):
    out = tmp_path / "output"
    manifest = collect_csv(
        source_dir, out, files=["good.csv", "empty.csv", "header_only.csv", "missing.csv"]
    )

    # Нормальный файл записан в выходную директорию под тем же именем.
    assert (out / "good.csv").exists()
    assert (out / MANIFEST_NAME).exists()

    entries = _by_name(manifest)
    assert entries["good.csv"]["status"] == STATUS_SUCCESS
    assert entries["good.csv"]["error"] == ""
    assert entries["good.csv"]["rows"] == 2
    assert entries["good.csv"]["columns"] == ["a", "b"]
    assert entries["good.csv"]["size_bytes"] > 0
    assert "modified_at" in entries["good.csv"]

    # Три класса сбоев, каждый с исходным текстом ошибки и типом.
    assert entries["empty.csv"]["status"] == STATUS_FAILED
    assert entries["empty.csv"]["error_type"] == "ValueError"
    assert "пуст" in entries["empty.csv"]["error"].lower()

    assert entries["header_only.csv"]["status"] == STATUS_FAILED
    assert entries["header_only.csv"]["error_type"] == "ValueError"
    assert entries["header_only.csv"]["error"]

    assert entries["missing.csv"]["status"] == STATUS_FAILED
    assert entries["missing.csv"]["error_type"] == "FileNotFoundError"
    assert "missing.csv" in entries["missing.csv"]["error"]
    # У отсутствующего источника сигнатуры быть не может.
    assert "size_bytes" not in entries["missing.csv"]
    # rows/columns только у успешных.
    assert "rows" not in entries["empty.csv"]
    assert "columns" not in entries["empty.csv"]

    # Сводка и метаданные запуска.
    assert manifest["summary"] == {"total": 4, "success": 1, "failed": 3, "existing": 0}
    assert manifest["run_timestamp"]
    assert manifest["change_basis"] == "size_bytes_and_modified_at"

    # Манифест на диске совпадает с возвращённым.
    on_disk = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk == manifest


def test_rerun_skips_unchanged_success(source_dir, tmp_path):
    out = tmp_path / "output"
    files = ["good.csv", "empty.csv", "header_only.csv", "missing.csv"]
    first = collect_csv(source_dir, out, files=files)
    good_first = _by_name(first)["good.csv"]

    second = collect_csv(source_dir, out, files=files)
    entries = _by_name(second)

    assert entries["good.csv"]["status"] == STATUS_EXISTING
    assert entries["good.csv"]["rows"] == good_first["rows"]
    assert entries["good.csv"]["columns"] == good_first["columns"]
    # Сбои пробуются заново, а не залипают навсегда.
    assert entries["empty.csv"]["status"] == STATUS_FAILED
    assert entries["missing.csv"]["status"] == STATUS_FAILED
    assert second["summary"] == {"total": 4, "success": 0, "failed": 3, "existing": 1}


def test_changed_source_is_recollected(source_dir, tmp_path):
    out = tmp_path / "output"
    collect_csv(source_dir, out, files=["good.csv"])

    # Меняем содержимое: новый размер и время модификации.
    good = source_dir / "good.csv"
    good.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")

    manifest = collect_csv(source_dir, out, files=["good.csv"])
    entry = _by_name(manifest)["good.csv"]
    assert entry["status"] == STATUS_SUCCESS
    assert entry["rows"] == 3
    assert manifest["summary"]["success"] == 1
    assert manifest["summary"]["existing"] == 0


def test_missing_output_file_forces_recollect(source_dir, tmp_path):
    out = tmp_path / "output"
    collect_csv(source_dir, out, files=["good.csv"])
    (out / "good.csv").unlink()

    manifest = collect_csv(source_dir, out, files=["good.csv"])
    assert _by_name(manifest)["good.csv"]["status"] == STATUS_SUCCESS
    assert (out / "good.csv").exists()


def test_default_scan_uses_all_csv_in_source(source_dir, tmp_path):
    out = tmp_path / "output"
    manifest = collect_csv(source_dir, out)

    names = {entry["source_file"] for entry in manifest["files"]}
    assert names == {"good.csv", "empty.csv", "header_only.csv"}
    # Отсутствующие файлы в режиме сканирования появиться не могут.
    assert all(
        entry["status"] != STATUS_FAILED or entry["source_file"] != "missing.csv"
        for entry in manifest["files"]
    )


def test_nonexistent_source_dir_with_explicit_files(tmp_path):
    out = tmp_path / "output"
    manifest = collect_csv(tmp_path / "no_such_dir", out, files=["x.csv"])
    entry = _by_name(manifest)["x.csv"]
    assert entry["status"] == STATUS_FAILED
    assert entry["error_type"] == "FileNotFoundError"
    assert manifest["summary"] == {"total": 1, "success": 0, "failed": 1, "existing": 0}


def test_run_pipeline_integrates_collect(source_dir, tmp_path):
    out = tmp_path / "reports"
    data = tmp_path / "data"
    result = run_pipeline(
        n=20,
        out_dir=str(out),
        data_dir=str(data),
        collect_source_dir=str(source_dir),
    )
    assert result["rows"] > 0
    manifest = result["collect_manifest"]
    assert manifest["summary"]["success"] == 1
    assert (data / "good.csv").exists()
    assert (data / MANIFEST_NAME).exists()
    # Поведение без сбора не изменилось.
    plain = run_pipeline(n=20, out_dir=str(tmp_path / "r2"), data_dir=str(tmp_path / "d2"))
    assert "collect_manifest" not in plain


def test_corrupt_manifest_is_ignored(source_dir, tmp_path):
    out = tmp_path / "output"
    collect_csv(source_dir, out, files=["good.csv"])
    # Повреждённый манифест не должен ломать повторный запуск.
    (out / MANIFEST_NAME).write_text("{ это не json", encoding="utf-8")

    manifest = collect_csv(source_dir, out, files=["good.csv"])
    assert _by_name(manifest)["good.csv"]["status"] == STATUS_SUCCESS


def test_main_entrypoint_in_process(source_dir, tmp_path, monkeypatch, capsys):
    from python_analytics.__main__ import main

    out = tmp_path / "output"
    rc = main(["collect", str(source_dir), str(out), "good.csv"])
    assert rc == 0
    assert (out / MANIFEST_NAME).exists()
    assert "Сбор завершён" in capsys.readouterr().out

    # Без подкоманды main() запускавает пайплайн в tmp_path.
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert (tmp_path / "data" / "synthetic.csv").exists()


def test_cli_collect_default_scan(source_dir, tmp_path):
    # Регрессия: nargs="*" даёт пустой список, что не должно означать
    # «обработать ноль файлов» — должен сработать скан каталога.
    from python_analytics.__main__ import main

    out = tmp_path / "scan_out"
    assert main(["collect", str(source_dir), str(out)]) == 0
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["summary"]["total"] == 3
    assert manifest["summary"]["success"] == 1


def test_cli_collect_subcommand(source_dir, tmp_path):
    out = tmp_path / "output"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "python_analytics",
            "collect",
            str(source_dir),
            str(out),
            "good.csv",
            "missing.csv",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["summary"] == {"total": 2, "success": 1, "failed": 1, "existing": 0}
    assert "Сбор завершён" in proc.stdout


def test_cli_without_args_runs_pipeline(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "python_analytics"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "data" / "synthetic.csv").exists()
