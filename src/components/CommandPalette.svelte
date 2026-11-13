<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { paletteOpen, go, toggleTheme } from '../lib/stores';
  import { nav } from '../lib/nav';
  import { plugins } from '../lib/plugins';

  interface Cmd { label: string; icon: string; cat: string; run: () => void; }

  const pages: Cmd[] = nav.flatMap((g) =>
    g.items.filter((i) => !i.soon).map((i) => ({ label: i.label, icon: i.icon, cat: 'Page', run: () => go(i.id) }))
  );
  const actions: Cmd[] = [
    { label: 'Toggle dark / light theme', icon: 'i-moon', cat: 'Action', run: toggleTheme }
  ];
  $: pluginPages = $plugins.map((p) => ({ label: p.title, icon: p.icon?.startsWith('i-') ? p.icon : 'i-plugin', cat: 'Plugin', run: () => go(p.id) }));
  $: pluginCmds = $plugins.flatMap((p) => (p.commands ?? []).map((c) => ({ label: c.label, icon: 'i-plugin', cat: 'Plugin', run: c.run })));
  $: all = [...pages, ...actions, ...pluginPages, ...pluginCmds];

  let q = '';
  let active = 0;
  let input: HTMLInputElement | undefined;

  $: filtered = all.filter(
    (c) => !q || c.label.toLowerCase().includes(q.toLowerCase()) || c.cat.toLowerCase().includes(q.toLowerCase())
  );
  $: if (active >= filtered.length) active = 0;

  function run(c: Cmd) {
    paletteOpen.set(false);
    c.run();
  }

  function onKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      paletteOpen.update((v) => !v);
      return;
    }
    if (!$paletteOpen) return;
    if (e.key === 'Escape') paletteOpen.set(false);
    else if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(filtered.length - 1, active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); if (filtered[active]) run(filtered[active]); }
  }

  onMount(() => {
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // reset + focus whenever it opens
  $: if ($paletteOpen) {
    q = '';
    active = 0;
    setTimeout(() => input?.focus(), 20);
  }
</script>

{#if $paletteOpen}
  <div
    class="overlay top"
    role="presentation"
    on:click={(e) => { if (e.target === e.currentTarget) paletteOpen.set(false); }}
  >
    <div class="cmdbox" role="dialog" aria-modal="true" aria-label="Search UnTangled">
      <div class="cmd-in">
        <Icon name="i-search" />
        <input bind:this={input} bind:value={q} placeholder="Search settings, devices and actions…" spellcheck="false" autocomplete="off" />
      </div>
      <div class="cmd-results">
        {#if filtered.length}
          {#each filtered as c, i}
            <button type="button" class="cmd-item" class:active={i === active} aria-current={i === active}
              on:click={() => run(c)} on:mousemove={() => (active = i)}>
              <span class="ci"><Icon name={c.icon} size={16} /></span>
              <span class="ct"><b>{c.label}</b></span>
              <span class="cat">{c.cat}</span>
            </button>
          {/each}
        {:else}
          <div class="cmd-empty">No matches.</div>
        {/if}
      </div>
      <div class="cmd-foot"><span><b>↑↓</b> move</span><span><b>↵</b> open</span><span><b>esc</b> close</span></div>
    </div>
  </div>
{/if}
