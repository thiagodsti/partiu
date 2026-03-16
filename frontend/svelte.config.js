import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  // Do not force runes globally — svelte-spa-router uses legacy Svelte 4 APIs.
  // Each of our own .svelte files opts in via $state/$props etc.
};
