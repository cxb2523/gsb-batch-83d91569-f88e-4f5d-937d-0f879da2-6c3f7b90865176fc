# getcheapapi.com

The project's one-page website: a Vite multi-page build in `dist/`, served by Workers static assets. A small Worker (`src/worker.js`) handles only `/stats/*`, the Rybbit proxy; its upstream is the `RYBBIT_UPSTREAM` secret. GA4 and Rybbit tags are added to every page at build time (not in dev).

- `src/page.html`: the page template, with `{{key}}` holes for every translatable string.
- `i18n/<code>.json`: one file per language (en, es, ja, ko, pt, zh). English is served at `/`, the rest at `/<code>/`.
- `vite.config.js`: renders the template once per language (hreflang links, language menu), hands the pages to Vite, and emits `sitemap.xml`. It refuses to build if a language is missing a key. The rendered `index.html` and `<code>/index.html` are build output, not committed.
- `src/site.css`, `src/site.js`: shared by every language; Vite hashes and minifies them. The ASCII figures are drawn on `<canvas>` from the product's own words.
- `<slug>/index.html` (pricing pages): plain HTML, English at `/<slug>/`; a translation goes in `<code>/<slug>/index.html` and is picked up by the build, the sitemap, hreflang alternates and a footer language column (do not write those by hand). Write internal links as the English path (`/serp-api-pricing/`): the build points them at the page's own language when that copy exists, and marks them `hreflang="en"` when it does not.
- `public/`: copied as is (favicon, `og.png`, `robots.txt`, `llms.txt`). `404.html` is English only.

```bash
cd site && npm install
npm run dev       # http://localhost:6191, reloads on template and i18n edits
npm run build     # dist/
npm run deploy    # build + wrangler deploy, production, needs confirmation
```

To add a language, copy `i18n/en.json` to `i18n/<code>.json` and translate it (titles with the local search terms, not a literal translation). Every number on the page comes from the README; keep them in sync when prices or capabilities change.
