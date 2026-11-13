"""Maintainers: check every catalog route's body fields against the provider's live input schema.

Free (schema reads only). GoAnyAPI needs no key; AnyAPI routes are skipped without ANYAPI_API_KEY.
Run before committing catalog changes: python scripts/check_catalog.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from getcheapapi.core import http, load_env  # noqa: E402
from getcheapapi.providers import AnyAPI, GoAnyAPI  # noqa: E402
from getcheapapi.router import load_catalog  # noqa: E402


def main() -> int:
    load_env()
    goany = {a["id"]: a["inputSchema"] for a in http("GET", f"{GoAnyAPI.base}/mcp/catalog", {})["data"]["apis"]}
    failed = 0
    for name, cap in load_catalog().items():
        for r in cap["routes"]:
            if r["provider"] == "goanyapi":
                schema = goany.get(r["endpoint"])
            elif r["provider"] == "anyapi" and AnyAPI.configured():
                schema = http("GET", f"{AnyAPI.base}/apis/{r['endpoint']}", {"X-API-Key": AnyAPI().key})["inputSchema"]
            else:
                continue
            if schema is None:
                print(f"FAIL {name} {r['provider']} {r['endpoint']}: not in the provider catalog")
                failed += 1
                continue
            unknown = set(r["body"]) - set(schema.get("properties", {}))
            missing = set(schema.get("required", [])) - set(r["body"])
            ok = not unknown and not missing
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {name} {r['provider']} {r['endpoint']}"
                  + ("" if ok else f": unknown {sorted(unknown)}, missing required {sorted(missing)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
