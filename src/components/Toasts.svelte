<script lang="ts">
  import { toasts } from '../lib/toast';
  import Icon from './Icon.svelte';
</script>

<div class="toasts">
  {#each $toasts as t (t.id)}
    <div class="toast"><Icon name="i-check" size={18} /><span>{t.msg}</span></div>
  {/each}
</div>
