<script lang="ts">
  import Icon from './Icon.svelte';
  import { login, UbusError } from '../lib/ubus';
  import { session, theme, toggleTheme } from '../lib/stores';

  let username = 'root';
  let password = '';
  let error = '';
  let busy = false;
  let showPw = false;

  async function submit(e?: Event) {
    e?.preventDefault();
    if (busy) return;
    busy = true;
    error = '';
    try {
      const r = await login(username, password);
      session.set({ username: r.data?.username ?? username });
    } catch (err) {
      if (err instanceof UbusError && err.code === 6) error = 'Wrong username or password.';
      else error = 'Could not reach the router. Check the connection and try again.';
    } finally {
      busy = false;
    }
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter') submit(e);
  }
</script>

<div class="auth">
  <!-- Brand / value panel (hidden on small screens) -->
  <aside class="auth-hero" aria-hidden="true">
    <div class="auth-hero-glow"></div>
    <div class="auth-hero-body">
      <div class="auth-brand">
        <span class="logo"><Icon name="i-wifi" size={22} /></span>
        <span class="auth-brand-txt">
          <b>UnTangled</b>
          <small>Router UI</small>
        </span>
      </div>
      <h2>Your router,<br />untangled.</h2>
      <p>All the power of your OpenWRT router, in an interface the whole household can use.</p>
      <ul class="auth-points">
        <li><Icon name="i-shield" size={17} /> Signs in with your existing router account</li>
        <li><Icon name="i-lock" size={17} /> Runs entirely on your router — nothing leaves your network</li>
        <li><Icon name="i-check" size={17} /> LuCI keeps working, untouched</li>
      </ul>
    </div>
  </aside>

  <!-- Sign-in form -->
  <main class="auth-main">
    <button
      class="auth-theme"
      type="button"
      on:click={toggleTheme}
      aria-label={$theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <Icon name={$theme === 'dark' ? 'i-sun' : 'i-moon'} size={17} />
    </button>

    <form class="auth-card" on:submit={submit} novalidate>
      <div class="auth-card-head">
        <span class="logo logo-lg"><Icon name="i-wifi" size={26} /></span>
        <h1>Sign in</h1>
        <p>Use your router's admin credentials to continue.</p>
      </div>

      {#if error}
        <div class="login-err" role="alert">{error}</div>
      {/if}

      <label for="u">Username</label>
      <div class="field">
        <Icon name="i-user" size={17} />
        <input
          id="u"
          type="text"
          bind:value={username}
          autocomplete="username"
          autocapitalize="none"
          autocorrect="off"
          spellcheck="false"
          on:keydown={onKey}
        />
      </div>

      <label for="p">Password</label>
      <div class="field">
        <Icon name="i-lock" size={17} />
        {#if showPw}
          <input
            id="p"
            type="text"
            bind:value={password}
            autocomplete="current-password"
            placeholder="Leave empty if no password is set"
            on:keydown={onKey}
          />
        {:else}
          <input
            id="p"
            type="password"
            bind:value={password}
            autocomplete="current-password"
            placeholder="Leave empty if no password is set"
            on:keydown={onKey}
          />
        {/if}
        <button
          class="field-btn"
          type="button"
          on:click={() => (showPw = !showPw)}
          aria-label={showPw ? 'Hide password' : 'Show password'}
          aria-pressed={showPw}
          tabindex="-1"
        >
          <Icon name={showPw ? 'i-eye-off' : 'i-eye'} size={17} />
        </button>
      </div>

      <button class="btn primary auth-submit" type="submit" disabled={busy}>
        {#if busy}
          <span class="spin" aria-hidden="true"></span> Signing in…
        {:else}
          Sign in
        {/if}
      </button>

      <p class="auth-foot">Press <kbd>Enter</kbd> to sign in.</p>
    </form>
  </main>
</div>
