#!/usr/bin/env node
// recipe.test.mjs — tests for the recipe compiler (scripts/recipe.mjs).
// No deps: mini-runner + an inline example profile. Covers parsing, validation, --fast/--step
// compilation, template filling with escaping, and — critically — that a hostile value is
// left INERT in the compiled code (browser_run_code_unsafe is RCE-equivalent).
// Usage: node tests/recipe.test.mjs   (exit 0 = green).

import {
  parseProfile, parseRecipes, parseLocators, validate, diagnose,
  compileFast, compileSteps, fillTemplate, assertCompiledSafe,
} from '../scripts/recipe.mjs';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

let pass = 0; let fail = 0;
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function t(d, got, want) { if (eq(got, want)) { pass++; process.stdout.write(`  ✓ ${d}\n`); } else { fail++; process.stdout.write(`  ✗ ${d}\n      got:  ${JSON.stringify(got)}\n      want: ${JSON.stringify(want)}\n`); } }
function ok(d, c) { if (c) { pass++; process.stdout.write(`  ✓ ${d}\n`); } else { fail++; process.stdout.write(`  ✗ ${d}\n`); } }

const MD = `## Locators (multi-anchor)
- ticket-search:
    sel:       role=textbox[name=/Search by number/]
    primary:   textbox
- ticket-row:
    sel:       span.ticket-number >> text="{id}" >> visible=true
    primary:   row
- row-regex:
    sel:       role=row[name=/^{id}/]
- no-sel:
    primary:   read-only
- item-pod:
    sel:       article.product_pod

## Recipes
open-ticket-by-id(id):
  - type:     ticket-search  <- {id}
  - click:    ticket-row     <- {id}
  - wait-url: /tickets/
  - return:   url

navigate-to(url):
  - navigate: <- {url}
  - extract:  item-pod

bad-action():
  - clik:     ticket-search

missing-locator():
  - click:    no-such-locator

use-no-sel():
  - click:    no-sel

extract-missing-locator():
  - extract:  no-such-locator

navigate-with-hole():
  - navigate: "{url}"

## Other section
- ignore this
`;

// --- parsing ----------------------------------------------------------------------
process.stdout.write('[parsing]\n');
const { locators, recipes } = parseProfile(MD);
ok('parses 5 locators', locators.size === 5);
t('sel of ticket-search', locators.get('ticket-search').sel, 'role=textbox[name=/Search by number/]');
t('detects template (holes)', locators.get('ticket-row').holes, ['id']);
ok('locator with no sel → sel null', locators.get('no-sel').sel === null);
ok('parses 7 recipes', recipes.size === 7);
const recipe = recipes.get('open-ticket-by-id');
t('recipe signature', recipe.params, ['id']);
t('number of steps', recipe.steps.length, 4);
t('type step with param arg', recipe.steps[0], { action: 'type', operand: 'ticket-search', arg: { kind: 'param', name: 'id' } });

// --- fillTemplate (per-engine escaping) -------------------------------------------
process.stdout.write('[fillTemplate]\n');
t('string-engine template', fillTemplate('span.ticket-number >> text="{id}" >> visible=true', { id: 'TCK-2026-123' }), 'span.ticket-number >> text="TCK-2026-123" >> visible=true');
t('regex-engine escapes metacharacters', fillTemplate('role=row[name=/^{id}/]', { id: 'A.B' }), 'role=row[name=/^A\\.B/]');
t('string-engine escapes quotes', fillTemplate('text="{x}"', { x: 'a"b' }), 'text="a\\"b"');

// --- validation -------------------------------------------------------------------
process.stdout.write('[validation]\n');
ok('canonical recipe is valid', validate(recipe, locators).ok);
ok('unknown action detected', !validate(recipes.get('bad-action'), locators).ok);
ok('missing locator detected', !validate(recipes.get('missing-locator'), locators).ok);
ok('locator without sel detected', !validate(recipes.get('use-no-sel'), locators).ok);
const fakeParam = { name: 'x', params: [], steps: [{ action: 'type', operand: 'ticket-search', arg: { kind: 'param', name: 'notdeclared' } }] };
ok('undeclared param detected', !validate(fakeParam, locators).ok);
// H2: extract with missing locator must give error (previously: silent continue)
ok('extract missing locator detected', !validate(recipes.get('extract-missing-locator'), locators).ok);
// H2: extract with valid locator (item-pod) must pass
ok('extract valid locator passes', validate(recipes.get('navigate-to'), locators).ok);
// H2: navigate with {…} in operand without <- generates warning
const navHole = validate(recipes.get('navigate-with-hole'), locators);
ok('navigate with {…} in operand generates warning', navHole.ok && navHole.warnings.length > 0);

// --- compileFast ------------------------------------------------------------------
process.stdout.write('[compileFast]\n');
const code = compileFast(recipe, locators, { id: 'TCK-2026-123' });
ok('is async (page) function', /^async \(page\) => \{/.test(code));
ok('type → fill', code.includes('.fill("TCK-2026-123")'));
ok('click → template filled', code.includes('text=\\"TCK-2026-123\\"') || code.includes('text="TCK-2026-123"'));
ok('wait-url → waitForURL includes', /waitForURL.*includes\("\/tickets\/"\)/.test(code));
ok('return url → page.url()', code.includes('return page.url();'));
ok('passes assertCompiledSafe', assertCompiledSafe(code) === true);
ok('is parseable JS', (() => { try { new Function('page', `return (${code})`); return true; } catch { return false; } })());
// H3: navigate with <- {param} uses the arg value, no double-quoting
const navRecipe = recipes.get('navigate-to');
const navCode = compileFast(navRecipe, locators, { url: 'https://example.com/page-1' });
ok('H3: navigate uses arg (url substituted)', navCode.includes('"https://example.com/page-1"'));
ok('H3: navigate does not double-quote placeholder', !navCode.includes('"{url}"') && !navCode.includes("'{url}'"));
// H1: extract with plain locator — compileFast returns textContent, does not truncate the name
const extractCode = compileFast(navRecipe, locators, { url: 'https://example.com' });
ok('H1: extract plain locator uses correct sel', extractCode.includes('"article.product_pod"'));
ok('H1: locator name not truncated (not item-pod → item-po)', !extractCode.includes('"item-po"'));

// --- compileSteps -----------------------------------------------------------------
process.stdout.write('[compileSteps]\n');
const steps = compileSteps(recipe, locators, { id: 'TCK-2026-123' });
t('step 0 type', steps[0], { action: 'type', target: 'role=textbox[name=/Search by number/]', value: 'TCK-2026-123' });
t('step 1 click with filled template', steps[1], { action: 'click', target: 'span.ticket-number >> text="TCK-2026-123" >> visible=true' });
t('step 2 wait', steps[2], { action: 'wait', waitFor: 'url', value: '/tickets/' });
// H3: navigate with <- {param} in compileSteps
const navSteps = compileSteps(recipes.get('navigate-to'), locators, { url: 'https://example.com/p1' });
t('H3 compileSteps: navigate value = arg', navSteps[0], { action: 'navigate', value: 'https://example.com/p1' });
// H1: plain locator extract in compileSteps returns map with intact name
t('H1 compileSteps: extract plain locator', navSteps[1], { action: 'extract', map: 'item-pod' });

// --- injection (CRITICAL) ---------------------------------------------------------
process.stdout.write('[injection]\n');
const EVIL = 'x"); fetchEvil(); //';
const evilCode = compileFast(recipe, locators, { id: EVIL }); // must not throw
const skeleton = evilCode.replace(/"(\\.|[^"\\])*"/g, '""').replace(/'(\\.|[^'\\])*'/g, "''");
ok('payload does NOT appear outside strings (inert)', !/fetchEvil/.test(skeleton));
ok('code with payload is still parseable JS', (() => { try { new Function('page', `return (${evilCode})`); return true; } catch { return false; } })());
ok('assertCompiledSafe accepts (payload is encapsulated)', assertCompiledSafe(evilCode) === true);
// and assertCompiledSafe REJECTS genuinely dangerous structure:
let threw = false;
try { assertCompiledSafe('async (page) => { require("fs"); }'); } catch { threw = true; }
ok('assertCompiledSafe rejects require outside string', threw);
let threw2 = false;
try { assertCompiledSafe('async (page) => { await page.evaluate(`${x}`); }'); } catch { threw2 = true; }
ok('assertCompiledSafe rejects template string + page.evaluate', threw2);

// fuzz: various hostile values → always inert and safe.
// --- Spanish sections and type-slowly (T295, benchmark 2026-10-30) -----------------
process.stdout.write('[sections / type-slowly]\n');
const ES = `## Localizadores (multi-ancla)
- origen:   sel: role=combobox[name="De"]
- opcion:   sel: role=option[name="{estacion}"]
## Recetas (unidades nombradas)
buscar(q, estacion):
  - type-slowly: origen  <- {q}
  - click:       opcion  <- {estacion}
## Trampas
- x
`;
const pe = parseProfile(ES);
ok('"## Recetas" / "## Localizadores" are read (were 0 recipes, 0 locators)', pe.recipes.size === 1 && pe.locators.size === 2);
ok('a section only starting with the word is not it ("## Recipesque")', parseRecipes('## Recipesque\nr():\n  - return: url\n').size === 0);
ok('type-slowly validates like type', validate(pe.recipes.get('buscar'), pe.locators).ok);
const fastSlow = compileFast(pe.recipes.get('buscar'), pe.locators, { q: 'Atocha', estacion: 'MADRID' });
ok('--fast: type-slowly → pressSequentially, passes the safety net', fastSlow.includes('await page.locator("role=combobox[name=\\"De\\"]").pressSequentially("Atocha");') && assertCompiledSafe(fastSlow));
t('--step: type-slowly → browser_type with slowly', compileSteps(pe.recipes.get('buscar'), pe.locators, { q: 'Atocha', estacion: 'MADRID' })[0], { action: 'type', target: 'role=combobox[name="De"]', value: 'Atocha', slowly: true });

process.stdout.write('[fuzz]\n');
let allSafe = true;
for (const v of ['a"b', "a'b", 'a\\b', '${x}', '`x`', 'require("x")', 'A.(B)+', 'TCK-1']) {
  try {
    const c = compileFast(recipe, locators, { id: v });
    const sk = c.replace(/"(\\.|[^"\\])*"/g, '""').replace(/'(\\.|[^'\\])*'/g, "''");
    if (/require|fetchEvil|`/.test(sk)) allSafe = false;
    new Function('page', `return (${c})`); // parseable
  } catch { allSafe = false; }
}
ok('fuzz invariant: every hostile value is inert and parseable', allSafe);

// --- per-step diagnostics (diagnose) ------------------------------------------------
// One self-made profile covering the five situations: normal compile, missing argument (and a
// template hole without `<-`), non-absolute navigate target, broken extract map, and a template
// with several distinct holes under a click. Every error must point at its step number.
process.stdout.write('[diagnostics]\n');
const DIAG_MD = `## Locators
- search-box:
    sel:       role=textbox[name="Search"]
- row-by-id:
    sel:       tr.row >> text="{id}"
- multi-hole:
    sel:       role=row[name="{a}"] >> text="{b}"
- price:
    sel:       span.price

## Recipes
good-recipe(q):
  - navigate: https://example.com/search
  - type:     search-box  <- {q}
  - click:    row-by-id   <- {q}
  - extract:  price

missing-param(q):
  - navigate: https://example.com/
  - type:     search-box  <- {q}
  - click:    row-by-id

bad-url():
  - navigate: https://example.com/ok
  - navigate: not-an-absolute-url
  - return:   url

bad-map():
  - navigate: https://example.com/
  - extract:  { title: price, broken, nope: no-such-locator }

multi-hole-click():
  - navigate: https://example.com/
  - click:    multi-hole  <- "x"

nav-braces():
  - navigate: "{url}"
`;
const dp = parseProfile(DIAG_MD);
// 1. normal: no issues, and the recipe still compiles to safe code
const dGood = diagnose(dp.recipes.get('good-recipe'), dp.locators, { q: 'TCK-1' });
ok('good recipe: diagnose finds no issues', dGood.ok && dGood.issues.length === 0);
const goodCode = compileFast(dp.recipes.get('good-recipe'), dp.locators, { q: 'TCK-1' });
ok('good recipe still compiles', goodCode.includes('await page.goto("https://example.com/search");'));
ok('good recipe compiled code passes the safety net', assertCompiledSafe(goodCode) === true);
// 2. missing argument: {q} declared but no value → error at the step that uses it (step 2);
//    template locator without <- {param} → error at its step (step 3)
const dMiss = diagnose(dp.recipes.get('missing-param'), dp.locators, {});
ok('missing argument: not ok', !dMiss.ok);
ok('missing argument: error at step 2 naming {q}', dMiss.issues.some((i) => i.level === 'error' && i.step === 2 && i.message.includes('{q}')));
ok('template hole without argument: error at step 3', dMiss.issues.some((i) => i.level === 'error' && i.step === 3 && i.message.includes('template')));
// 3. illegal navigate target → error at exactly step 2, step 1 (valid URL) untouched
const dBadUrl = diagnose(dp.recipes.get('bad-url'), dp.locators, {});
ok('bad url: exactly one error, at step 2', dBadUrl.issues.length === 1 && dBadUrl.issues[0].level === 'error' && dBadUrl.issues[0].step === 2);
ok('bad url: message says absolute http(s)', dBadUrl.issues[0].message.includes('http(s)'));
// 4. broken extract map: pair without ':' AND unknown locator → two errors, both at step 2
const dMap = diagnose(dp.recipes.get('bad-map'), dp.locators, {});
ok('bad map: two errors, both at step 2', dMap.issues.filter((i) => i.level === 'error').length === 2 && dMap.issues.every((i) => i.step === 2));
ok("bad map: pair without ':' reported", dMap.issues.some((i) => i.message.includes("without ':'")));
ok('bad map: unknown locator reported', dMap.issues.some((i) => i.message.includes("locator not found: 'no-such-locator'")));
// 5. template with several distinct holes under a click → error at step 2 naming the holes
const dMulti = diagnose(dp.recipes.get('multi-hole-click'), dp.locators, {});
ok('multi-hole template: one error at step 2', dMulti.issues.length === 1 && dMulti.issues[0].level === 'error' && dMulti.issues[0].step === 2);
ok('multi-hole template: message names both holes', dMulti.issues[0].message.includes('{a}') && dMulti.issues[0].message.includes('{b}'));
// warning (not error): navigate operand with {…} but no <- {param}
const dBrace = diagnose(dp.recipes.get('nav-braces'), dp.locators, {});
ok('navigate {…} without <- is a warning, recipe still ok', dBrace.ok && dBrace.issues.length === 1 && dBrace.issues[0].level === 'warning' && dBrace.issues[0].step === 1);

// --- diagnostics through the CLI (compile command) -----------------------------------
// A real profile in a temp TANDEM_DATA_DIR: errors → diagnostics on stderr, NO code on stdout,
// non-zero exit; a clean recipe → code on stdout, exit 0.
process.stdout.write('[diagnostics CLI]\n');
const tmp = mkdtempSync(join(tmpdir(), 'tandem-recipe-diag-'));
mkdirSync(join(tmp, 'sites'), { recursive: true });
writeFileSync(join(tmp, 'sites', 'diag.test.md'), DIAG_MD);
const RECIPE_CLI = fileURLToPath(new URL('../scripts/recipe.mjs', import.meta.url));
const runCli = (cliArgs) => spawnSync(process.execPath, [RECIPE_CLI, ...cliArgs], { env: { ...process.env, TANDEM_DATA_DIR: tmp }, encoding: 'utf8' });

const cliBad = runCli(['compile', 'diag.test', 'bad-url']);
ok('CLI: errors → exit non-zero', cliBad.status === 1);
ok('CLI: errors → no executable code on stdout', !cliBad.stdout.includes('page.goto') && !cliBad.stdout.includes('async (page)'));
ok('CLI: diagnostics point at the step', cliBad.stderr.includes('step 2 (navigate)'));

const cliMiss = runCli(['compile', 'diag.test', 'missing-param']);
ok('CLI: missing argument → exit non-zero', cliMiss.status === 1);
ok('CLI: missing argument located to its steps', cliMiss.stderr.includes('step 2 (type)') && cliMiss.stderr.includes('step 3 (click)'));

const cliGood = runCli(['compile', 'diag.test', 'good-recipe', 'TCK-1']);
ok('CLI: valid recipe exits 0', cliGood.status === 0);
ok('CLI: valid recipe emits code on stdout', cliGood.stdout.includes('async (page) =>'));
ok('CLI: emitted code passes the safety net', assertCompiledSafe(cliGood.stdout.trim()) === true);
rmSync(tmp, { recursive: true, force: true });

// --- summary ----------------------------------------------------------------------
process.stdout.write(`\nrecipe: ${pass} ok, ${fail} failures\n`);
process.exit(fail === 0 ? 0 : 1);
