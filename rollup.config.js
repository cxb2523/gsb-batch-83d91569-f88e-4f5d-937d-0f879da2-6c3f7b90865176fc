import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import fs from 'node:fs';
import path from 'node:path';

function rawTextPlugin() {
  return {
    name: 'raw-text-plugin',
    load(id) {
      const ext = path.extname(id);
      if (ext !== '.css' && ext !== '.tpl') {
        return null;
      }

      const content = fs.readFileSync(id, 'utf8');
      return `export default ${JSON.stringify(content)};`;
    },
  };
}

export default {
  input: 'src/index.ts',
  output: {
    file: 'dist/homeassistant-solar-panel-preview.js',
    format: 'iife',
    sourcemap: true,
    globals: {
      lit: 'lit',
      'lit-element': 'litElement',
    },
  },
  external: [],
  plugins: [
    rawTextPlugin(),
    typescript({
      tsconfig: false,
      compilerOptions: {
        target: 'ES2020',
        module: 'ES2020',
        lib: ['ES2020', 'DOM', 'DOM.Iterable'],
      },
    }),
    resolve({ browser: true }),
    commonjs(),
  ],
};
