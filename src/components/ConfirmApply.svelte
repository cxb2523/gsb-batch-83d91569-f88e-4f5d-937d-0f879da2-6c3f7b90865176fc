<script lang="ts">
  import { confirmState, keepChanges, revertChanges } from '../lib/confirm';
</script>

{#if $confirmState.active}
  <div class="overlay">
    <div class="dlg" role="dialog" aria-modal="true" aria-labelledby="ca-title">
      <h3 id="ca-title">Keep these changes?</h3>
      <p>{$confirmState.label} applied. If you can still see this page, it's working — press <b>Keep</b>. If something broke, do nothing: the router restores the previous settings automatically.</p>
      <div class="cd">Reverting in <b>{$confirmState.seconds}s</b></div>
      <div class="row">
        <button class="btn" on:click={revertChanges}>Revert now</button>
        <button class="btn primary" on:click={keepChanges}>Keep changes</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .dlg { width: min(440px, 92vw); background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 24px; box-shadow: 0 30px 80px -20px rgba(0,0,0,.4); }
  .dlg h3 { margin: 0 0 8px; font-size: 17px; }
  .dlg p { margin: 0 0 14px; color: var(--ink-dim); font-size: 13.5px; line-height: 1.55; }
  .cd { font-size: 13px; color: var(--warn); font-weight: 600; margin-bottom: 18px; font-variant-numeric: tabular-nums; }
  .row { display: flex; gap: 10px; justify-content: flex-end; }
</style>
