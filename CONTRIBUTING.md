# Contributing

Thanks for helping! A few ground rules keep MeshAtlas easy to run:

1. **No runtime dependencies.** The server uses the Python standard library only (3.9+). The front end is plain
   JavaScript with the vendored D3 and topojson-client — no build step, no npm.
2. **Read-only.** MeshAtlas never changes anything on the machines it watches. New collectors must be read-only
   and must not read secrets (environment variables, container configs, key files).
3. **Remote code stays tiny and 3.8-compatible.** `remote_collect.py` and the ping scripts run on other people's
   servers through `python3 -`.

## Setup

```bash
python -m pip install -e '.[dev]'
pytest
ruff check src tests
meshatlas demo          # UI with generated data
meshatlas run --host 127.0.0.1    # against your own tailnet
```

## Front end

- `web/prefs.js` per-browser settings, `web/i18n.js` translations, `web/app.js` overview,
  `web/page.js` detail page, `web/extras.js` search / issues / matrix / boot, `web/demo.js` demo data.
- User-facing text goes through `t("English text", {params})`. Add the Chinese translation to `ZH` in `i18n.js`
  (other languages are welcome: add a dictionary and a language button in `prefs.js`).
- Check both the desktop layout and a 375 px wide phone layout; the page must never scroll sideways.

## Pull requests

Keep them focused, describe what you tested, and include a screenshot for UI changes.
