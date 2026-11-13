<script lang="ts">
  // Per-field help: a focusable "?" with a hover/focus tooltip.
  // Usage:  Enable radio <Help text="Switches this band on or off." />
  export let text: string;
</script>

<button type="button" class="help" aria-label="Help">?<span class="tip">{text}</span></button>
