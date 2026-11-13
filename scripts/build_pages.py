"""Build the static demo site (GitHub Pages): the web app plus a config.js that turns demo mode on."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from meshatlas import __version__  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
if out.exists():
    shutil.rmtree(out)
shutil.copytree(ROOT / "src" / "meshatlas" / "web", out)
(out / "config.js").write_text(f"window.MESHATLAS = {json.dumps({'demo': True, 'version': __version__, 'static': True})};\n")
(out / ".nojekyll").write_text("")
print(f"demo site written to {out}/")
