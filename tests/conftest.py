"""Pytest collection shims for restricted/sandboxed Windows accounts.

Some CI/sandbox users run under a redirected USERPROFILE whose CSIDL shell
folders are not registered, so pywin32's SHGetFolderPath (called eagerly by
appdirs while pyppeteer imports) raises a com_error and prevents the whole
suite from even collecting. This is an environment defect, not a code one:
the path is only ever read lazily. When that lookup is broken, point
appdirs at an env-based directory before any engine module imports
pyppeteer. On a normal account the lookup succeeds and this file does
nothing.
"""
import os

try:
    import appdirs

    try:
        appdirs.AppDirs("probe").user_data_dir
    except Exception:  # pragma: no cover - only fires on the broken accounts
        def _user_data_dir(appname, appauthor=None, version=None, roaming=False):
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            return os.path.join(base, appname)

        appdirs.user_data_dir = _user_data_dir
except ImportError:  # pragma: no cover
    pass
