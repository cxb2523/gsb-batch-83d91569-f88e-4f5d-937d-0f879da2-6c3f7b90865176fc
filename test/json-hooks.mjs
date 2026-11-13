/* Lets `node --test` load src/localize.js, which imports src/lang/*.json without an import
   attribute (esbuild inlines those at build time; Node requires the attribute).
   Node >= 22.15 / 23.5 uses in-process hooks; older versions fall back to a worker loader. */
import * as nodeModule from 'node:module';

const isLangJson = url => url.startsWith('file:') && url.includes('/src/lang/') && url.split('?')[0].endsWith('.json');

if (typeof nodeModule.registerHooks === 'function') {
  nodeModule.registerHooks({
    load(url, context, nextLoad) {
      if (isLangJson(url)) return nextLoad(url, { ...context, importAttributes: { type: 'json' } });
      return nextLoad(url, context);
    },
  });
} else if (typeof nodeModule.register === 'function') {
  nodeModule.register(new URL('./json-loader.mjs', import.meta.url));
}
