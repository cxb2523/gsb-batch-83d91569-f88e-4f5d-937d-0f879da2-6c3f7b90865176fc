<script lang="ts">
	import { platform } from './platforms';

	let { id }: { id: string } = $props();
	const p = $derived(platform(id));
</script>

<span class="badge" style="--hue: {p.hue}">{p.name}</span>

<style>
	.badge {
		display: inline-block;
		padding: 0 8px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 600;
		line-height: 20px;
		white-space: nowrap;
		background: hsl(var(--hue) 75% 93%);
		color: hsl(var(--hue) 65% 30%);
	}
	@media (prefers-color-scheme: dark) {
		.badge {
			background: hsl(var(--hue) 35% 22%);
			color: hsl(var(--hue) 80% 80%);
		}
	}
</style>
