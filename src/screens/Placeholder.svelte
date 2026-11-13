<script lang="ts">
  export let id: string;
  export let title: string;
</script>

<div class="page-head">
  <div>
    <h1>{title}</h1>
    <p>This screen is scaffolded. Live data and controls land in the build phases — see <code>docs/ARCHITECTURE.md</code>.</p>
  </div>
</div>

<div class="panel">
  <div class="panel-b" style="padding:44px;text-align:center;color:var(--muted)">
    <p style="margin:0">Screen <code>#{id}</code> — Phase&nbsp;0 shell in place.</p>
    <p style="margin:8px 0 0;font-size:12.5px">Wire this to ubus following the data-source map in the plan.</p>
  </div>
</div>
