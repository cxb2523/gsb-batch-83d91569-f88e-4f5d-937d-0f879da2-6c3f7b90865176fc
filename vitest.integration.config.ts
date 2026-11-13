import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['packages/api/test/integration/**/*.int.test.ts'],
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
