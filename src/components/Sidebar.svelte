<script lang="ts">
  import Icon from './Icon.svelte';
  import { nav } from '../lib/nav';
  import { plugins, buildNav } from '../lib/plugins';
  import { route, go } from '../lib/stores';

  export let open: boolean = false;
  export let onNavigate: () => void = () => {};

  const version = __APP_VERSION__;

  $: groups = buildNav(nav, $plugins);

  function navigate(id: string) {
    go(id);
    onNavigate();
  }
</script>

<nav class="sidebar" class:open aria-label="Main navigation">
  {#each groups as group}
    <div class="nav-label">{group.label}</div>
    <div class="nav-group">
      {#each group.items as item}
        <button class="nav-item" class:active={$route === item.id} on:click={() => navigate(item.id)}>
          <Icon name={item.icon} />
          {item.label}
          {#if item.soon}<span class="tag">soon</span>{/if}
        </button>
      {/each}
    </div>
  {/each}

  <div class="nav-foot">
    <div class="ver">UnTangled {version}-beta</div>
    <div>by <a href="mailto:me@krishnendu.com">Krish Paul</a></div>
    <a class="gh" href="https://github.com/bidhata/untangled" target="_blank" rel="noopener"><svg><use href="#i-github" /></svg> GitHub</a>
  </div>
</nav>
