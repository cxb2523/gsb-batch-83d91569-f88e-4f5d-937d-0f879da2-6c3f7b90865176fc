import { html, type TemplateResult } from 'lit';

interface CompiledTemplate {
  strings: TemplateStringsArray;
  valueIndexes: number[];
}

const TEMPLATE_CACHE = new Map<string, CompiledTemplate>();
const PLACEHOLDER_REGEX = /\{\{(\d+)\}\}/g;

function toTemplateStrings(parts: string[]): TemplateStringsArray {
  const strings = [...parts] as unknown as TemplateStringsArray;
  Object.defineProperty(strings, 'raw', {
    value: [...parts],
    writable: false,
    enumerable: false,
    configurable: false,
  });
  return strings;
}

function compileTemplate(template: string): CompiledTemplate {
  const parts: string[] = [];
  const valueIndexes: number[] = [];
  let lastIndex = 0;

  PLACEHOLDER_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = PLACEHOLDER_REGEX.exec(template)) !== null) {
    parts.push(template.slice(lastIndex, match.index));
    valueIndexes.push(Number(match[1]));
    lastIndex = match.index + match[0].length;
  }

  parts.push(template.slice(lastIndex));

  return {
    strings: toTemplateStrings(parts),
    valueIndexes,
  };
}

export function htmlFromTpl(template: string, ...values: unknown[]): TemplateResult {
  let compiled = TEMPLATE_CACHE.get(template);
  if (!compiled) {
    compiled = compileTemplate(template);
    TEMPLATE_CACHE.set(template, compiled);
  }

  const orderedValues = compiled.valueIndexes.map((index) => values[index]);
  return html(compiled.strings, ...orderedValues);
}
