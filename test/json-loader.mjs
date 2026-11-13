/* Fallback loader (older Node versions without module.registerHooks): gives src/lang/*.json the
   JSON format, which Node's built-in JSON loader accepts without an import attribute. */
export function resolve(specifier, context, nextResolve) {
  return nextResolve(specifier, context);
}

export function load(url, context, nextLoad) {
  if (url.startsWith('file:') && url.includes('/src/lang/') && url.split('?')[0].endsWith('.json')) {
    return nextLoad(url, { ...context, format: 'json' });
  }
  return nextLoad(url, context);
}
