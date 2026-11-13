"""
Shared pytest configuration for the offline suite.

Sandbox-only workaround: pyppeteer imports `appdirs` at module load, and
appdirs' Windows backend calls SHGetFolderPath, which raises
pywintypes.com_error in a Windows profile whose LOCALAPPDATA/APPDATA
folders are missing. On a normal CI box that lookup succeeds, so this
shim is never installed -- it is strictly conditional on the lookup
failing. A genuinely absent engine still surfaces as the ImportError the
individual tests already turn into a skip.
"""

import os
import tempfile

try:  # pragma: no cover - environment-specific
    import appdirs

    if not hasattr(appdirs, "_zimmo_appdirs_shimmed"):
        try:
            appdirs.AppDirs("pyppeteer").user_data_dir
        except Exception:
            _home = os.path.join(tempfile.gettempdir(), "pyppeteer-appdirs")

            class _AppDirs:
                def __init__(self, *_, **__):
                    self.user_data_dir = os.path.join(_home, "Data")
                    self.user_config_dir = os.path.join(_home, "Config")
                    self.user_cache_dir = os.path.join(_home, "Cache")

            appdirs.AppDirs = _AppDirs
            appdirs._zimmo_appdirs_shimmed = True
except ImportError:
    pass
