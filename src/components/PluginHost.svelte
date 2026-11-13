<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { makeApi } from '../lib/pluginApi';
  import type { UntangledPlugin } from '../lib/plugins';

  export let plugin: UntangledPlugin;

  let container: HTMLElement;
  let cleanup: void | (() => void);
  let mountedId = '';
  const api = makeApi();

  function remount(p: UntangledPlugin) {
    if (!container || mountedId === p.id) return;
    if (typeof cleanup === 'function') { try { cleanup(); } catch { /* ignore */ } }
    container.innerHTML = '';
    mountedId = p.id;
    try {
      cleanup = p.mount(container, api);
    } catch (e) {
      container.innerHTML =
        '<div class="panel"><div class="panel-b" style="color:var(--crit)">This plugin failed to render.</div></div>';
      console.warn('[untangled] plugin mount error:', p.id, e);
    }
  }

  onMount(() => remount(plugin));
  onDestroy(() => { if (typeof cleanup === 'function') { try { cleanup(); } catch { /* ignore */ } } });
  $: if (container && plugin) remount(plugin);
</script>

<div bind:this={container}></div>
