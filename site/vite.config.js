// Renders src/page.html once per language in i18n/ (English at /, the rest at /<code>/), then lets Vite
// build them like any multi-page site. The rendered HTML files are build output and are not committed.
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const SITE = dirname(fileURLToPath(import.meta.url));
const TEMPLATE = join(SITE, 'src', 'page.html');
const I18N = join(SITE, 'i18n');
const ORIGIN = 'https://getcheapapi.com';
const HOLE = /\{\{(\w+)\}\}/g;
const GLOBE = '<svg class="globe" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M1.5 8h13M8 1.5c1.8 1.8 2.7 4 2.7 6.5s-.9 4.7-2.7 6.5M8 1.5C6.2 3.3 5.3 5.5 5.3 8s.9 4.7 2.7 6.5" /></svg>';
// Added to every built page (not in dev). Rybbit loads from /stats/, which the Worker proxies upstream.
const ANALYTICS = `    <script async src="https://www.googletagmanager.com/gtag/js?id=G-49X99WY2B7"></script>
    <script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','G-49X99WY2B7');</script>
    <script src="/stats/script.js?siteId=8732edd4c50b" defer></script>
  </head>`;

// The language's own words for the "switch to this language?" prompt site.js shows, carried on its menu link.
const offer = (s) => ` data-offer="${s.lang_offer}" data-switch="${s.lang_switch}" data-close="${s.lang_close}"`;

const pathOf = (code) => (code === 'en' ? '/' : `/${code}/`);
const fileOf = (code) => (code === 'en' ? join(SITE, 'index.html') : join(SITE, code, 'index.html'));

function loadLangs() {
  const langs = readdirSync(I18N)
    .filter((f) => f.endsWith('.json'))
    .map((f) => [f.slice(0, -5), JSON.parse(readFileSync(join(I18N, f), 'utf8'))]);
  return [...langs.filter(([c]) => c === 'en'), ...langs.filter(([c]) => c !== 'en')];
}

function check(langs, template) {
  const en = langs[0][1];
  const generated = new Set(['html_lang', 'url', 'og_locale', 'hreflang', 'lang_menu', 'lang_links']);
  const problems = [];
  for (const [code, strings] of langs) {
    for (const key of Object.keys(en)) if (!(key in strings)) problems.push(`${code}: missing ${key}`);
    for (const [key, value] of Object.entries(strings)) {
      if (value.includes('"')) problems.push(`${code}.${key}: use typographic quotes, not "`);
    }
  }
  for (const [, key] of template.matchAll(HOLE)) {
    if (!generated.has(key) && !(key in en)) problems.push(`template uses {{${key}}}, which en.json does not define`);
  }
  if (problems.length) throw new Error(`i18n:\n${problems.join('\n')}`);
}

function render(template, langs, code, strings) {
  const hreflang = langs.map(([c, s]) => `    <link rel="alternate" hreflang="${s._hreflang}" href="${ORIGIN}${pathOf(c)}" />`);
  hreflang.push(`    <link rel="alternate" hreflang="x-default" href="${ORIGIN}/" />`);
  const anchors = (indent) =>
    langs
      .map(([c, s]) => `${indent}<a href="${pathOf(c)}" lang="${s._hreflang}" hreflang="${s._hreflang}"${offer(s)}${c === code ? ' aria-current="page"' : ''}>${s._name}</a>`)
      .join('\n');
  const values = {
    ...strings,
    html_lang: strings._hreflang,
    url: ORIGIN + pathOf(code),
    og_locale: strings._og_locale,
    hreflang: hreflang.join('\n'),
    lang_menu: anchors('              '),
    lang_links: anchors('            '),
  };
  return template.replace(HOLE, (_, key) => values[key]);
}

function writePages() {
  const template = readFileSync(TEMPLATE, 'utf8');
  const langs = loadLangs();
  check(langs, template);
  for (const [code, strings] of langs) {
    const file = fileOf(code);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, render(template, langs, code, strings));
  }
  return langs;
}

// Pages kept as plain HTML in their own folder: /<slug>/ in English, /<code>/<slug>/ once translated.
const PAGES = ['serp-api-pricing', 'twitter-api-pricing', 'reddit-api-pricing', 'privacy'];
const pageFile = (code, slug) => join(SITE, code === 'en' ? '' : code, slug, 'index.html');
const pageFiles = (langs) => langs.flatMap(([c]) => PAGES.map((p) => pageFile(c, p))).filter(existsSync);
const pagePath = (code, slug) => `${code === 'en' ? '' : `/${code}`}/${slug}/`;

// hreflang alternates for a page that exists in more than one language, as <link> or <xhtml:link> lines.
function alternates(langs, slug, tag, indent) {
  const copies = langs.filter(([c]) => existsSync(pageFile(c, slug)));
  if (copies.length < 2) return [];
  return [
    ...copies.map(([c, s]) => `${indent}<${tag} rel="alternate" hreflang="${s._hreflang}" href="${ORIGIN}${pagePath(c, slug)}" />`),
    `${indent}<${tag} rel="alternate" hreflang="x-default" href="${ORIGIN}${pagePath('en', slug)}" />`,
  ];
}

// Footer language menu for a page that exists in more than one language, added to the end of its .foot-bar.
function languageMenu(html, langs, slug, code) {
  const copies = langs.filter(([c]) => existsSync(pageFile(c, slug)));
  if (copies.length < 2) return html;
  const links = copies
    .map(([c, s]) => `<a href="${pagePath(c, slug)}" hreflang="${s._hreflang}" lang="${s._hreflang}"${offer(s)}${c === code ? ' aria-current="page"' : ''}>${s._name}</a>`)
    .join('');
  const { lang_label, _name } = langs.find(([c]) => c === code)[1];
  const menu = `<details class="lang foot-lang"><summary aria-label="${lang_label}">${GLOBE}${_name}</summary><div class="lang-menu">${links}</div></details>`;
  return html.replace(/(<div class="foot-bar mono"><span>[^<]*<\/span>)(.*)<\/div>/, `$1<span class="grow"></span>$2${menu}</div>`);
}

// Internal links are always written as the English path (/serp-api-pricing/). On a page in another
// language each one points at that language's copy, or is marked hreflang="en" while there is none.
// Anchors that already declare hreflang (the language menu) target a language on purpose and stay as is.
function localize(html, code) {
  if (code === 'en') return html;
  return html.replace(/<a\b[^>]*>/g, (tag) => {
    if (/\shreflang=/.test(tag)) return tag;
    return tag.replace(/\shref="(\/[^"#?]*\/|\/)([#?][^"]*)?"/, (attr, path, rest = '') =>
      existsSync(pageFile(code, path.slice(1, -1))) ? ` href="/${code}${path}${rest}"` : `${attr} hreflang="en"`,
    );
  });
}

function sitemap(langs) {
  const homeAlternates = langs
    .map(([c, s]) => `    <xhtml:link rel="alternate" hreflang="${s._hreflang}" href="${ORIGIN}${pathOf(c)}" />`)
    .join('\n');
  const urls = [
    ...langs.map(([c]) => `  <url>\n    <loc>${ORIGIN}${pathOf(c)}</loc>\n${homeAlternates}\n  </url>`),
    ...PAGES.flatMap((p) => {
      const links = alternates(langs, p, 'xhtml:link', '    ').map((l) => `\n${l}`).join('');
      return langs.filter(([c]) => existsSync(pageFile(c, p))).map(([c]) => `  <url>\n    <loc>${ORIGIN}${pagePath(c, p)}</loc>${links}\n  </url>`);
    }),
  ].join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urls}\n</urlset>\n`;
}

export default defineConfig(() => {
  const langs = writePages();
  return {
    root: SITE,
    appType: 'mpa',
    server: { host: '127.0.0.1', port: 6191, strictPort: true },
    preview: { host: '127.0.0.1', port: 6191 },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      rollupOptions: { input: [...langs.map(([c]) => fileOf(c)), ...pageFiles(langs), join(SITE, '404.html')] },
    },
    plugins: [
      {
        name: 'i18n-pages',
        transformIndexHtml(html, ctx) {
          const parts = relative(SITE, ctx.filename).split(sep);
          const code = langs.some(([c]) => c === parts[0]) ? parts[0] : 'en';
          const slug = code === 'en' ? parts[0] : parts[1];
          const links = PAGES.includes(slug) ? alternates(langs, slug, 'link', '    ') : [];
          if (links.length) html = languageMenu(html.replace(/<link rel="canonical"[^>]*>/, (tag) => `${tag}\n${links.join('\n')}`), langs, slug, code);
          if (!ctx.server) html = html.replace('  </head>', ANALYTICS);
          return localize(html, code);
        },
        configureServer(server) {
          server.watcher.add([TEMPLATE, I18N]);
          server.watcher.on('change', (file) => {
            if (file !== TEMPLATE && !file.startsWith(I18N)) return;
            try {
              writePages();
              server.ws.send({ type: 'full-reload' });
            } catch (err) {
              server.config.logger.error(err.message);
            }
          });
        },
        generateBundle() {
          this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemap(langs) });
        },
      },
    ],
  };
});
