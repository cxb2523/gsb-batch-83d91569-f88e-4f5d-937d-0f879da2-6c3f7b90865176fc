# Templates and Styles Loading Guide

This project keeps UI markup and styles outside component source files by loading .tpl and .css files during the Rollup build.

## Overview

The rendering pipeline has three parts:

1. Build time raw loading of .tpl and .css files as strings.
2. Runtime conversion of .tpl strings into Lit templates.
3. Runtime conversion of .css strings into Lit CSS results.

Key files:

- rollup config: [rollup.config.js](rollup.config.js)
- template helper: [src/template-utils.ts](src/template-utils.ts)
- asset type declarations: [src/raw-imports.d.ts](src/raw-imports.d.ts)
- card component: [src/solar-panel-grid-card.ts](src/solar-panel-grid-card.ts)
- editor component: [src/solar-panel-grid-card-editor.ts](src/solar-panel-grid-card-editor.ts)
- templates folder: [src/templates](src/templates)

## Build Time: Raw Text Imports

In [rollup.config.js](rollup.config.js), rawTextPlugin reads .css and .tpl files and turns each file into a JavaScript default export string.

Effectively, imports like these work:

- import cardStyles from ./templates/solar-panel-grid-card.css
- import cardRenderTpl from ./templates/solar-panel-grid-card-render.tpl

No extra preprocessing is needed beyond the Rollup plugin.

## TypeScript Module Declarations

[raw-imports.d.ts](src/raw-imports.d.ts) declares .css and .tpl modules so TypeScript knows both import types are strings.

Without this file, TypeScript would report unknown module type errors.

## Runtime HTML Loading from .tpl

[src/template-utils.ts](src/template-utils.ts) provides htmlFromTpl(template, ...values).

Template syntax uses numbered placeholders:

- {{0}}, {{1}}, {{2}}, etc.

At runtime:

1. The helper scans the template text for placeholders.
2. It builds TemplateStringsArray segments.
3. It maps placeholder indexes to the values passed in.
4. It calls Lit html(strings, ...orderedValues).

The helper caches compiled templates in memory so repeated renders do not reparse every template string.

### Placeholder Rules

- Placeholders are positional and zero based.
- You can reorder values in a template by changing placeholder indexes.
- Keep template and calling code aligned when adding or removing placeholders.

Example shape:

- .tpl file: title {{0}} and body {{1}}
- call site: htmlFromTpl(templateString, titleValue, bodyValue)

## Runtime CSS Loading from .css

Components import CSS text from files in [src/templates](src/templates), then convert it into Lit styles using unsafeCSS.

Pattern used:

- static styles = css`${unsafeCSS(importedCssText)}`

This keeps all CSS editable as normal .css files while still working with Lit style APIs.

## Where to Edit UI

For card UI:

- CSS: [src/templates/solar-panel-grid-card.css](src/templates/solar-panel-grid-card.css)
- TPL files: [src/templates/solar-panel-grid-card-render.tpl](src/templates/solar-panel-grid-card-render.tpl) and related partials in [src/templates](src/templates)

For editor UI:

- CSS: [src/templates/solar-panel-grid-card-editor.css](src/templates/solar-panel-grid-card-editor.css)
- TPL files: [src/templates/solar-panel-grid-card-editor-render.tpl](src/templates/solar-panel-grid-card-editor-render.tpl) and related partials in [src/templates](src/templates)

## Adding a New Template

1. Create a new .tpl file in [src/templates](src/templates).
2. Add placeholders as needed, for example {{0}}.
3. Import the file in the component.
4. Render it with htmlFromTpl(templateText, ...values).
5. Keep placeholder indexes synchronized with argument order.

## Adding New Styles

1. Create or update a .css file in [src/templates](src/templates).
2. Import the CSS text into the component.
3. Expose it through Lit styles with css and unsafeCSS.

## Safety Note

unsafeCSS is used because style text is loaded from local project files at build time. Do not feed user generated or remote CSS into unsafeCSS.

## Validation

After template or style edits, run:

- npm run type-check
- npm run build

This verifies TypeScript, template imports, and Rollup bundling all remain valid.
