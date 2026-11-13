<script lang="ts">
  import IconSprite from './components/IconSprite.svelte';
  import Shell from './components/Shell.svelte';
  import Login from './components/Login.svelte';
  import { session } from './lib/stores';
  import { restoreSession } from './lib/ubus';

  // Restore a persisted session token (sessionStorage) on boot and revalidate
  // it against the router before showing the Shell. This is what keeps the user
  // signed in across in-tab reloads and iOS/Safari/Firefox tab-discard restores
  // — without it, every reload lands on the login screen. While the probe runs
  // we show nothing (a blank splash) so the login form never flashes for an
  // already-signed-in user.
  const booting = restoreSession().then((username) => {
    if (username) session.set({ username });
  });
</script>

<IconSprite />

{#await booting}
  <div class="boot-splash" aria-hidden="true"></div>
{:then}
  {#if $session.username}
    <Shell />
  {:else}
    <Login />
  {/if}
{/await}

<style>
  /* Neutral splash while the stored session is revalidated on boot. Uses the
     app background so there is no flash of the login screen for a signed-in
     user, and no flash of the shell for a signed-out one. */
  .boot-splash {
    position: fixed;
    inset: 0;
    background: var(--bg, #0b0f14);
  }
</style>
