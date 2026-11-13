import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  // Lets <script lang="ts"> work inside .svelte files.
  preprocess: vitePreprocess()
};
