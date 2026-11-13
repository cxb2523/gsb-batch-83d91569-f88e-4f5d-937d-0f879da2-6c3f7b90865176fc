<script lang="ts">
  export let name: string;
  export let size: number = 18;
</script>

<svg width={size} height={size} aria-hidden="true"><use href={'#' + name} /></svg>
