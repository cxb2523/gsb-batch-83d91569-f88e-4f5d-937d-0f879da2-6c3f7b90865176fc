"""Пакетный сбор CSV из исходной директории с манифестом и возобновлением.

Модуль реализует повторяемый шаг «батч-загрузка → запись CSV»: каждый файл
обрабатывается изолированно, ошибка одного файла не прерывает всю партию,
а JSON-манифест в выходной директории фиксирует исход каждого файла. Повторный
запуск пропускает уже успешно собранные неизменные файлы (статус
``existing``) и заново собирает изменённые — основанием служат размер файла в
байтах и время модификации.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from python_analytics.load import load_csv

#: Имя JSON-манифеста в выходной директории.
MANIFEST_NAME = "manifest.json"

#: Успешно собран в текущем запуске.
STATUS_SUCCESS = "success"
#: Сбой при чтении (файл отсутствует, пуст или без строк данных).
STATUS_FAILED = "failed"
#: Уже собран ранее, источник не менялся — чтение пропущено.
STATUS_EXISTING = "existing"


def _source_signature(path: Path) -> dict:
    """Снять сигнатуру источника: размер в байтах и время модификации."""
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def _read_manifest(out_dir: Path) -> dict | None:
    """Прочитать предыдущий манифест, если он есть и является валидным JSON."""
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def collect_csv(
    source_dir: str | Path,
    output_dir: str | Path,
    files: list[str] | None = None,
    encoding: str = "utf-8",
) -> dict:
    """Собрать все CSV из исходной директории в выходную.

    Обрабатывает каждый ``.csv`` независимо: успех одного файла не влияет на
    остальные, сбой одного не прерывает партию. Сбои фиксируются в манифесте
    с сохранением исходного текста ошибки (``FileNotFoundError`` для
    отсутствующего файла, ``ValueError`` для пустого файла и файла только с
    заголовком — семантика целиком наследуется от
    :func:`python_analytics.load.load_csv`).

    Args:
        source_dir: директория-источник с CSV-файлами.
        output_dir: директория для успешно прочитанных CSV и манифеста.
        files: явный список имён файлов (относительно ``source_dir``).
            Если ``None`` или пустой список — сканируются все ``*.csv`` в
            ``source_dir``. Список позволяет сослаться на отсутствующий путь:
            такой файл попадёт в манифест как failed с FileNotFoundError.
        encoding: кодировка для чтения и записи CSV.

    Returns:
        Манифест в виде словаря: метаданные запуска, сводка и записи по
        каждому файлу. Тот же манифест записывается в
        ``<output_dir>/manifest.json``.
    """
    src = Path(source_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not files:
        # None или пустой список — режим сканирования всех *.csv в источнике.
        names = sorted(p.name for p in src.glob("*.csv")) if src.exists() else []
    else:
        names = sorted(files)

    previous = _read_manifest(out)
    previous_by_name = (
        {entry["source_file"]: entry for entry in previous.get("files", [])}
        if previous
        else {}
    )

    entries: list[dict] = []

    for name in names:
        source_path = src / name
        output_path = out / name
        prev = previous_by_name.get(name)

        # Возобновление: ранее успешный файл с неизменным источником и
        # сохранённым результатом пропускаем. Основание решения —
        # size_bytes и modified_at, записанные в прошлом манифесте.
        if (
            prev is not None
            and prev.get("status") in (STATUS_SUCCESS, STATUS_EXISTING)
            and source_path.exists()
            and output_path.exists()
            and prev.get("size_bytes") is not None
            and prev.get("modified_at") is not None
        ):
            current = _source_signature(source_path)
            if current == {
                "size_bytes": prev["size_bytes"],
                "modified_at": prev["modified_at"],
            }:
                entries.append(
                    {
                        "source_file": name,
                        "status": STATUS_EXISTING,
                        "error": "",
                        "rows": prev.get("rows"),
                        "columns": prev.get("columns"),
                        "size_bytes": current["size_bytes"],
                        "modified_at": current["modified_at"],
                    }
                )
                continue

        try:
            df = load_csv(source_path, encoding=encoding)
        except (FileNotFoundError, ValueError) as exc:
            entry = {
                "source_file": name,
                "status": STATUS_FAILED,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            if source_path.exists():
                entry.update(_source_signature(source_path))
            entries.append(entry)
            continue

        # Успешное чтение — пишем копию в выходную директорию под тем же именем.
        df.to_csv(output_path, index=False, encoding=encoding)
        entry = {
            "source_file": name,
            "status": STATUS_SUCCESS,
            "error": "",
            "rows": int(len(df)),
            "columns": [str(col) for col in df.columns],
        }
        entry.update(_source_signature(source_path))
        entries.append(entry)

    summary = {
        "total": len(entries),
        "success": sum(e["status"] == STATUS_SUCCESS for e in entries),
        "failed": sum(e["status"] == STATUS_FAILED for e in entries),
        "existing": sum(e["status"] == STATUS_EXISTING for e in entries),
    }
    manifest = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(src.resolve()),
        "output_dir": str(out.resolve()),
        "change_basis": "size_bytes_and_modified_at",
        "summary": summary,
        "files": entries,
    }

    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
