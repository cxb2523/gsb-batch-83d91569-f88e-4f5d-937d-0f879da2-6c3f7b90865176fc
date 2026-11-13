import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	// bun:sqlite lo resuelve Bun en runtime, Vite no debe intentar empaquetarlo
	ssr: { external: ['bun:sqlite'] },
	optimizeDeps: { exclude: ['bun:sqlite'] }
});
