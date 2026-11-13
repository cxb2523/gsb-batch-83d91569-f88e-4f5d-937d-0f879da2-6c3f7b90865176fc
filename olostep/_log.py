"""
Modern logging configuration for Olostep SDK.

Provides library-safe logging with secret redaction and structured IO logging.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import IO_LOG_PATH

# Top-level package logger
logger = logging.getLogger("olostep")
logger.addHandler(logging.NullHandler())  # library-safe default
logger.propagate = True  # let app handlers catch logs

# Sub-loggers (optional convenience)
io_logger = logging.getLogger("olostep.backend.io")
io_logger.propagate = True  # it's the default, just to be explicit


class RedactSecretsFilter(logging.Filter):
    """
    Redacts common secrets in log records. Users may attach this to their handlers.
    """

    SECRET_PATTERNS: Iterable[re.Pattern[str]] = (
        re.compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.I),
        re.compile(r"(api[_-]?key=)[A-Za-z0-9]{10,}", re.I),
        re.compile(r"(token=)[A-Za-z0-9\-_\.]{10,}", re.I),
        re.compile(r"(\"authorization\":\s*\"Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.I),
        re.compile(r"(\"Authorization\":\s*\"Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.I),
        re.compile(r"(\"x-api-key\":\s*\")[A-Za-z0-9]{10,}", re.I),
        re.compile(r"(\"x-auth-token\":\s*\")[A-Za-z0-9\-_\.]{10,}", re.I),
    )
    REPLACEMENT = r"\1[REDACTED]"

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat in self.SECRET_PATTERNS:
            msg = pat.sub(self.REPLACEMENT, msg)
        # stash sanitized message without mutating args (safe for %-formatting)
        record.msg = msg
        record.args = ()
        return True


class PerMessageIOFilter(logging.Filter):
    """
    Filter that allows per-message control of IO logging.
    Use the 'log_to_file' extra parameter to control whether a message gets logged to file.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        skip_file_logging = getattr(record, "skip_file_logging", False)
        return not skip_file_logging


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# functions to toggle logging behavior
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


def _enable_stderr_debug(level: int = logging.DEBUG) -> None:
    """
    Opt-in helper: attach a simple stderr handler to the package logger.
    Safe for quickstarts; in real apps users should configure logging themselves.
    """
    h = logging.StreamHandler()
    fmt = "[%(levelname)s] %(name)s: %(message)s"
    h.setFormatter(logging.Formatter(fmt))
    h.addFilter(RedactSecretsFilter())
    root = logging.getLogger("olostep")
    root.setLevel(level)
    root.addHandler(h)


def _enable_file_logging(log_path: str | Path | None = None) -> None:
    """
    Opt-in helper: enable file-based intercept logging.
    
    Creates individual JSON files per request in the intercepts directory
    and tracks them in a SQLite database. Must be called explicitly to enable logging.
    
    Args:
        log_path: Path for intercept files. If None, uses IO_LOG_PATH from config.
    
    Raises:
        OSError: If directories cannot be created or are not writable.
        sqlite3.Error: If database cannot be created or accessed.
    
    Safe for quickstarts; in real apps users should configure logging themselves.
    """
    
    # Use provided path or fall back to config
    if log_path is None:
        log_path = IO_LOG_PATH
    
    intercepts_dir, db_path = _resolve_log_paths(log_path)
    
    # Check if handler already exists
    if any(isinstance(h, InterceptFileHandler) for h in io_logger.handlers):
        logger.warning("File logging handler already exists")
        return
    
    # Validate paths are writable
    try:
        intercepts_dir.mkdir(parents=True, exist_ok=True)
        # Test write access by creating a temporary file
        test_file = intercepts_dir / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
    except OSError as e:
        raise OSError(f"Cannot create or write to intercepts directory {intercepts_dir}: {e}") from e
    
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Test database access by attempting to create/connect
        test_conn = sqlite3.connect(str(db_path), timeout=1.0)
        test_conn.execute("PRAGMA journal_mode=WAL")
        test_conn.close()
    except sqlite3.Error as e:
        raise sqlite3.Error(f"Cannot create or access database {db_path}: {e}") from e
    except OSError as e:
        raise OSError(f"Cannot create database directory {db_path.parent}: {e}") from e
    
    logger.info(f"Enabling file logging: {intercepts_dir.resolve()}")
    logger.info(f"Database: {db_path.resolve()}")
    
    intercept_handler = InterceptFileHandler(intercepts_dir, db_path)
    intercept_handler.setLevel(logging.DEBUG)
    intercept_handler.addFilter(RedactSecretsFilter())
    intercept_handler.addFilter(PerMessageIOFilter())
    io_logger.addHandler(intercept_handler)
    
    io_logger.setLevel(logging.DEBUG)


class InterceptFileHandler(logging.Handler):
    """Custom handler that writes individual intercept files and database entries."""

    def __init__(self, intercepts_dir: Path, db_path: Path) -> None:
        super().__init__()
        self.intercepts_dir = intercepts_dir
        self.db_path = db_path
        self._redactor = _DataRedactor()

    def _ensure_db_schema(self, conn: sqlite3.Connection) -> None:
        """Ensure database schema exists. Called once per connection."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intercepts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                url TEXT,
                http_method TEXT,
                http_status INTEGER,
                request_id TEXT
            )
        """)
        conn.commit()

    @contextmanager
    def _db_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections.
        
        Uses WAL mode for thread-safe concurrent writes. Since this is write-only
        bookkeeping, per-operation connections are efficient and eliminate connection
        lifetime issues.
        
        Yields:
            sqlite3.Connection: Database connection with WAL mode enabled
            
        Example:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO ...")
                conn.commit()
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        
        try:
            # Enable WAL mode for concurrent writes (required for parallel tests)
            conn.execute("PRAGMA journal_mode=WAL")
            
            # Ensure schema exists (idempotent, fast if already exists)
            self._ensure_db_schema(conn)
            
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _extract_url_and_method(self, log_entry: dict[str, Any]) -> tuple[str, str, int | None]:
        """Extract URL, HTTP method, and status code from log entry."""
        url = ""
        http_method = ""
        http_status: int | None = None

        o_data = log_entry.get("O", {}) if isinstance(log_entry.get("O"), dict) else {}
        i_data = log_entry.get("I", {}) if isinstance(log_entry.get("I"), dict) else {}

        if "url" in o_data and "method" in o_data:
            url = o_data.get("url", "")
            http_method = o_data.get("method", "")
        elif "url" in i_data and "method" in i_data:
            url = i_data.get("url", "")
            http_method = i_data.get("method", "")

        if "status_code" in o_data:
            http_status = o_data.get("status_code")
        elif "status_code" in i_data:
            http_status = i_data.get("status_code")

        return url, http_method, http_status

    def emit(self, record: logging.LogRecord) -> None:
        """Write log entry to individual file and database."""
        if not hasattr(record, "request_id"):
            return

        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }

            if hasattr(record, "request_id"):
                log_entry["request_id"] = record.request_id

            if hasattr(record, "response_time_ms"):
                log_entry["response_time_ms"] = record.response_time_ms

            if hasattr(record, "i"):
                log_entry["I"] = self._redactor.redact_data(record.i)
            elif hasattr(record, "I"):
                log_entry["I"] = self._redactor.redact_data(record.I)

            if hasattr(record, "o"):
                log_entry["O"] = self._redactor.redact_data(record.o)
            elif hasattr(record, "O"):
                log_entry["O"] = self._redactor.redact_data(record.O)

            request_id = log_entry["request_id"]
            filename = self.intercepts_dir / f"{request_id}.json"
            url, http_method, http_status = self._extract_url_and_method(log_entry)

            # Ensure directory exists before starting transaction
            self.intercepts_dir.mkdir(parents=True, exist_ok=True)

            # Insert into database first, then write file to ensure atomicity
            # If file write fails, database transaction will rollback
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO intercepts (timestamp, url, http_method, http_status, request_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (log_entry["timestamp"], url, http_method, http_status, request_id))
                
                # File write happens within transaction context
                # If this fails, the database transaction will rollback
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(log_entry, f, indent=2)

        except (OSError, sqlite3.Error) as e:
            # Log database/file errors but don't crash the application
            logger.error(f"Failed to write intercept log: {e}", exc_info=True)
            self.handleError(record)
        except Exception as e:
            # Unexpected errors should be logged with full traceback
            logger.error(f"Unexpected error in intercept logging: {e}", exc_info=True)
            self.handleError(record)

    def close(self) -> None:
        """Close handler. No connection cleanup needed with per-operation connections."""
        super().close()


class _DataRedactor:
    """Helper class for redacting sensitive data from log entries."""

    def _contains_secret(self, text: str) -> bool:
        """Check if text contains secrets."""
        if re.search(r"bearer\s+[a-za-z0-9\-\._~\+\/]+=*", text, re.I):
            return True
        if re.search(r"api[_-]?key[=:]\s*[a-za-z0-9]{10,}", text, re.I):
            return True
        return bool(re.search(r"token[=:]\s*[a-za-z0-9\-_\.]{10,}", text, re.I))

    def _redact_string(self, text: str) -> str:
        """Redact secrets in a string."""
        text = re.sub(
            r"(bearer\s+)[a-za-z0-9\-\._~\+\/]+=*",
            r"\1[REDACTED]",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"(api[_-]?key[=:]\s*)[a-za-z0-9]{10,}",
            r"\1[REDACTED]",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"(token[=:]\s*)[a-za-z0-9\-_\.]{10,}",
            r"\1[REDACTED]",
            text,
            flags=re.I,
        )
        return text

    def redact_data(self, data: Any) -> Any:
        """Recursively redact sensitive data from dictionaries."""
        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                if key == "body" and isinstance(value, str):
                    try:
                        parsed_body = json.loads(value)
                        redacted[key] = self.redact_data(parsed_body)
                    except (json.JSONDecodeError, TypeError):
                        if self._contains_secret(value):
                            redacted[key] = self._redact_string(value)
                        else:
                            redacted[key] = value
                elif isinstance(value, str) and self._contains_secret(value):
                    redacted[key] = self._redact_string(value)
                elif isinstance(value, dict):
                    redacted[key] = self.redact_data(value)
                else:
                    redacted[key] = value
            return redacted
        elif isinstance(data, str) and self._contains_secret(data):
            return self._redact_string(data)
        else:
            return data


def _resolve_log_paths(log_path: str | Path) -> tuple[Path, Path]:
    """Resolve intercept directory and database paths from base log path.
    
    Args:
        log_path: Base path for logging (e.g., ".runtime/io_logs")
        
    Returns:
        tuple[Path, Path]: (intercepts_dir, db_path)
    """
    log_path_obj = Path(log_path)
    if not log_path_obj.is_absolute() and not str(log_path).startswith("."):
        log_path_obj = Path.cwd() / log_path
    
    intercepts_dir = log_path_obj / "intercepts"
    
    # Database goes to .runtime/intercepts.db (one level up from io_logs if nested)
    if ".runtime" in str(log_path_obj) or log_path_obj.name == "io_logs":
        db_path = log_path_obj.parent / "intercepts.db"
    else:
        db_path = Path.cwd() / ".runtime" / "intercepts.db"
    
    return intercepts_dir, db_path


def get_logger(name: str | None = None) -> logging.Logger:
    """Library API for internal modules."""
    return logging.getLogger("olostep" + ("" if not name else f".{name}"))


