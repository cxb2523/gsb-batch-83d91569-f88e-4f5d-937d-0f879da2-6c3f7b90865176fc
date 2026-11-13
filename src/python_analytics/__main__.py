"""Точка входа: ``uv run python -m python_analytics``.

Без аргументов запускается end-to-end аналитический пайплайн
(:func:`python_analytics.pipeline.run_pipeline`). Подкоманда ``collect``
запускает пакетный сбор CSV:

    python -m python_analytics collect <source_dir> <output_dir> [files ...]
"""

import argparse

from python_analytics.collect import collect_csv
from python_analytics.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер командной строки."""
    parser = argparse.ArgumentParser(
        prog="python -m python_analytics",
        description="Аналитический пайплайн и пакетный сбор CSV.",
    )
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser(
        "collect", help="Пакетно собрать CSV из исходной директории."
    )
    collect_parser.add_argument("source_dir", help="Директория-источник с CSV.")
    collect_parser.add_argument(
        "output_dir", help="Директория для собранных CSV и манифеста."
    )
    collect_parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="Необязательный явный список имён файлов (по умолчанию — все *.csv).",
    )
    collect_parser.add_argument(
        "--encoding", default="utf-8", help="Кодировка CSV (по умолчанию utf-8)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI. Возвращает код завершения процесса."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "collect":
        # argparse nargs="*" отдаёт пустой список, когда позиционные имена
        # не заданы; для collect_csv это означает режим сканирования каталога.
        manifest = collect_csv(
            args.source_dir,
            args.output_dir,
            files=args.files or None,
            encoding=args.encoding,
        )
        summary = manifest["summary"]
        print(
            "Сбор завершён: "
            f"всего={summary['total']}, "
            f"успешно={summary['success']}, "
            f"ошибок={summary['failed']}, "
            f"пропущено={summary['existing']}"
        )
        print(f"Манифест: {manifest['output_dir']}/manifest.json")
        return 0

    run_pipeline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
