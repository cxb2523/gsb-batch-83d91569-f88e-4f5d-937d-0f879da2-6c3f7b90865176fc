// recipe-parser.mjs — DSL parser and validator for recipes (tandem:map).
//
// Understands the profile markdown (sites/<host>.md): extracts locators and recipes into
// structures, and validates a recipe against its locators. Hand-parsed flat-YAML (no deps).
// Does NOT compile or execute: only "understands" the text. Compilation lives in recipe-compiler.mjs.

export const ACTIONS = new Set(['navigate', 'type', 'type-slowly', 'click', 'wait-url', 'return', 'extract', 'extract-all']);

// --- profile parsing ---------------------------------------------------------------
// Profiles get written in the human's language: `## Recetas` used to parse as no recipes at all, and
// validate said nothing (books.toscrape.com and www.google.com, benchmark 2026-10-30).
export const SECTION_NAMES = { Locators: ['Locators', 'Localizadores'], Recipes: ['Recipes', 'Recetas'] };

function sectionStart(lines, title) {
  return lines.findIndex((l) => SECTION_NAMES[title].some((t) => new RegExp(`^## ${t}\\b`).test(l.trim())));
}

export function hasSection(md, title) {
  return sectionStart(md.replace(/\r\n?/g, '\n').split('\n'), title) >= 0;
}

function section(md, title) {
  const lines = md.replace(/\r\n?/g, '\n').split('\n');   // CRLF (Windows checkout/editor) broke every line-anchored regex
  const start = sectionStart(lines, title);
  if (start < 0) return [];
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => /^##\s/.test(l));
  return (end < 0 ? rest : rest.slice(0, end));
}

// The selector part of a `sel:` value: profiles annotate after it — `  (comment)` or `| verified DATE`.
// A comment starts at 2+ spaces followed by '(' or '|', or at ' | '. Selectors themselves never contain
// those (`:has(…)`, `:nth-child(2)` have no double space before the paren).
export function selValue(raw) {
  return raw.split(/\s{2,}[(|]|\s\|\s/)[0].trim();
}

// Locators, in either form (both appear in real profiles — the shipped example uses both):
//   - name:                     - name:   sel: <selector>   | verified …
//       sel: <selector>
// isTemplate if sel has {holes}. A `- name:` line without any sel: stays (sel null → validate says so).
export function parseLocators(md) {
  const out = new Map();
  let cur = null;
  for (const line of section(md, 'Locators')) {
    const one = line.match(/^-\s+([a-z0-9-]+):\s+sel:\s*(.+)$/);
    const head = one || line.match(/^-\s+([a-z0-9-]+):\s*$/);
    if (head) { cur = head[1]; out.set(cur, { sel: null, holes: [] }); }
    const sel = one ? [null, one[2]] : (!head && line.match(/^\s+sel:\s*(.+?)\s*$/));
    if (sel && cur) {
      const value = selValue(sel[1]);
      const holes = [...value.matchAll(/\{([^}]+)\}/g)].map((m) => m[1]);
      out.set(cur, { sel: value, holes });
    }
  }
  return out;
}

// `- name: …` lines in Locators that are neither form above: dropped silently before, now reported.
export function unparsedLocatorLines(md) {
  return section(md, 'Locators').filter((l) => /^-\s+\S/.test(l)
    && !/^-\s+([a-z0-9-]+):\s*$/.test(l) && !/^-\s+([a-z0-9-]+):\s+sel:\s*\S/.test(l));
}

// Recipes: header `name(params):` and steps `- action: operand [<- {param}|"lit"]`.
export function parseRecipes(md) {
  const out = new Map();
  let cur = null;
  for (const line of section(md, 'Recipes')) {
    const head = line.match(/^([A-Za-z0-9-]+)(?:\(([^)]*)\))?:\s*$/);
    if (head) {
      const params = head[2] ? head[2].split(',').map((s) => s.trim()).filter(Boolean) : [];
      cur = { name: head[1], params, steps: [] };
      out.set(head[1], cur);
      continue;
    }
    const step = line.match(/^\s*-\s*([a-z-]+):\s*(.*)$/);
    if (step && cur) {
      const action = step[1];
      let operand = step[2].trim(); let arg = null;
      const arrow = operand.split('<-');
      if (arrow.length === 2) {
        operand = arrow[0].trim();
        const raw = arrow[1].trim();
        const param = raw.match(/^\{([^}]+)\}$/);
        const lit = raw.match(/^"(.*)"$/);
        arg = param ? { kind: 'param', name: param[1] }
          : lit ? { kind: 'literal', value: lit[1] }
            : { kind: 'literal', value: raw };
      }
      cur.steps.push({ action, operand, arg });
    }
  }
  return out;
}

export function parseProfile(md) {
  return { locators: parseLocators(md), recipes: parseRecipes(md) };
}

// --- per-step diagnostics ----------------------------------------------------------
// diagnose(recipe, locators, args) — the pre-compile check: every problem as
// { step, action, level, message }, where step is the 1-based position of the step in the recipe
// (0 = recipe-level, no single step to point at). level 'error' blocks compilation; 'warning'
// marks a suspicious but non-fatal form. The collector reads this to fix the profile step by
// step instead of guessing from one thrown message.
// args: the actual arguments the recipe would be compiled with, or null when unknown (plain
// validation of the profile) — value-dependent checks (missing argument, resolved navigate
// URL) only run when args are given.
function isAbsoluteHttpUrl(u) {
  try { const p = new URL(String(u)); return p.protocol === 'http:' || p.protocol === 'https:'; }
  catch { return false; }
}

export function diagnose(recipe, locators, args = null) {
  const issues = [];
  const error = (step, action, message) => issues.push({ step, action, level: 'error', message });
  const warning = (step, action, message) => issues.push({ step, action, level: 'warning', message });
  if (!recipe) {
    error(0, null, 'recipe not found');
    return { ok: false, issues };
  }
  const checkLocator = (n, action, name) => {
    const loc = locators.get(name);
    if (!loc) error(n, action, `locator not found: '${name}'`);
    else if (!loc.sel) error(n, action, `locator '${name}' has no sel: — not actionable`);
  };
  recipe.steps.forEach((step, i) => {
    const n = i + 1;
    if (!ACTIONS.has(step.action)) {
      error(n, step.action, `unknown action (valid: ${[...ACTIONS].join(', ')})`);
      return;
    }
    // referenced param must be declared, and (when args are known) actually provided
    if (step.arg?.kind === 'param') {
      if (!recipe.params.includes(step.arg.name)) {
        error(n, step.action, `param not declared in signature: {${step.arg.name}}`);
      } else if (args && !(step.arg.name in args)) {
        error(n, step.action, `missing argument: no value for {${step.arg.name}}`);
      }
    }
    // navigate: only absolute http(s) — a literal/operand is checked here, an argument once its
    // value is known (args given). `{…}` in the operand without `<-` is only a warning.
    if (step.action === 'navigate') {
      if (/\{[^}]+\}/.test(step.operand) && !step.arg) {
        warning(n, step.action, `operand contains '{…}' — did you mean '<- {param}' to pass it as an argument?`);
        return;
      }
      const target = step.arg
        ? (step.arg.kind === 'literal' ? step.arg.value : (args ? args[step.arg.name] : undefined))
        : step.operand;
      if (target == null) return;   // value unknown here; the missing-argument error above covers it
      if (!/\{[^}]+\}/.test(String(target)) && !isAbsoluteHttpUrl(target)) {
        error(n, step.action, `navigate target is not an absolute http(s) URL: '${String(target).slice(0, 60)}'`);
      }
      return;
    }
    // wait-url does not use a locator
    if (step.action === 'wait-url') return;
    // extract / extract-all: plain locator, or (extract only) a map {key: url | url:/re/ | <locator>} —
    // every locator named in the map is checked too (it used to pass validate and fail at compile).
    if (step.action === 'extract' || step.action === 'extract-all') {
      if (step.action === 'extract-all' && step.operand.startsWith('{')) {
        error(n, step.action, 'extract-all takes one locator, not a {…} map');
        return;
      }
      const names = step.operand.startsWith('{')
        ? step.operand.replace(/^\{|\}$/g, '').split(',').map((p) => p.trim()).filter(Boolean)
          .map((p) => (p.indexOf(':') < 0 ? null : p.slice(p.indexOf(':') + 1).trim()))
        : [step.operand];
      for (const name of names) {
        if (name == null) { error(n, step.action, `pair without ':' in map '${step.operand}'`); continue; }
        if (name === 'url' || /^url:\/.*\/$/.test(name)) continue;
        checkLocator(n, step.action, name);
      }
      return;
    }
    // return url is special
    if (step.action === 'return' && step.operand === 'url') return;
    // type, type-slowly, click, return <locator>: must exist and have sel
    const loc = locators.get(step.operand);
    if (!loc) { error(n, step.action, `locator not found: '${step.operand}'`); return; }
    if (!loc.sel) { error(n, step.action, `locator '${step.operand}' has no sel: — not actionable`); return; }
    // a template locator in a click: the step must supply the (single) hole value
    if (step.action === 'click' && loc.holes.length) {
      const distinct = new Set(loc.holes);
      if (distinct.size > 1) {
        error(n, step.action, `locator '${step.operand}' has ${distinct.size} distinct holes (${[...distinct].map((h) => `{${h}}`).join(', ')}): a click step can only provide one value`);
      } else if (!step.arg) {
        error(n, step.action, `locator '${step.operand}' is a template (${loc.holes.map((h) => `{${h}}`).join(',')}) but the step does not pass '<- {param}'`);
      }
    }
  });
  return { ok: !issues.some((i) => i.level === 'error'), issues };
}

// Stable, human-readable rendering: `step 2 (navigate): …` / `recipe: …`, ✗ error / ⚠ warning.
export function formatIssue(issue) {
  const where = issue.step > 0 ? `step ${issue.step} (${issue.action})` : 'recipe';
  return `${where}: ${issue.message}`;
}
export function formatDiagnostics(issues) {
  return issues.map((i) => `${i.level === 'error' ? '✗' : '⚠'} ${formatIssue(i)}`).join('\n');
}

// --- validation --------------------------------------------------------------------
// Thin wrapper over diagnose without concrete args (structure only), kept for callers that want
// flat error/warning strings.
export function validate(recipe, locators) {
  const d = diagnose(recipe, locators, null);
  return {
    ok: d.ok,
    errors: d.issues.filter((i) => i.level === 'error').map(formatIssue),
    warnings: d.issues.filter((i) => i.level === 'warning').map(formatIssue),
  };
}
