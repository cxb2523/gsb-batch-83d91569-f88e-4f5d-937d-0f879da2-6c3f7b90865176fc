<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import Icon from './Icon.svelte';
  import { theme, toggleTheme, paletteOpen, session } from '../lib/stores';
  import { logout } from '../lib/ubus';
  import { getBoard, getWan } from '../lib/net';

  export let onMenu: () => void = () => {};

  const version = __APP_VERSION__;
  let model = '';
  let firmware = '';
  let wanUp: boolean | null = null; // null = unknown (not yet loaded)
  let timer: ReturnType<typeof setInterval> | undefined;

  async function refreshWan() {
    try {
      wanUp = (await getWan()).up;
    } catch {
      /* keep last known value */
    }
  }

  onMount(() => {
    getBoard()
      .then((b) => { model = b.model; firmware = b.firmware; })
      .catch(() => { /* leave blank until ubus is reachable */ });
    refreshWan();
    timer = setInterval(refreshWan, 5000);
  });
  onDestroy(() => clearInterval(timer));

  async function doLogout() {
    await logout();
    session.set({ username: null });
  }
</script>

<header class="topbar">
  <button class="hamburger" on:click={onMenu} aria-label="Open menu"><Icon name="i-menu" size={20} /></button>
  <div class="model">{model || 'Router'} <small>{[firmware, `UnTangled ${version}`].filter(Boolean).join(' · ')}</small></div>
  <div class="top-spacer"></div>
  <button class="tbtn" id="cmdBtn" on:click={() => paletteOpen.set(true)} aria-label="Search">
    <Icon name="i-search" /><span class="lbltxt">Search</span><kbd class="kbd">⌘K</kbd>
  </button>
  <span class="pill"><span class="dot" class:down={wanUp === false}></span> {wanUp === false ? 'Internet offline' : 'Internet online'}</span>
  <button class="tbtn icbtn" on:click={toggleTheme} aria-label="Toggle theme">
    <Icon name={$theme === 'dark' ? 'i-sun' : 'i-moon'} />
  </button>
  <button class="tbtn" on:click={doLogout}><Icon name="i-logout" /> {$session.username}</button>
</header>
