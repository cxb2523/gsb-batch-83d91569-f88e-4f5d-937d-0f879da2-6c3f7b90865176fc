// Example UnTangled plugin — loaded at runtime, not part of the core build.
// A plugin is a self-contained ES module exporting a descriptor whose mount()
// renders into a container using the host API. It reuses core CSS classes so
// it looks native, and never imports core internals (future-proof).
export default {
  id: 'ping',
  title: 'Ping Test',
  group: 'Tools',
  order: 10,
  // icon omitted -> defaults to the puzzle-piece plugin icon
  commands: [{ label: 'Run a ping test', run: () => { location.hash = 'ping'; } }],

  mount(container, api) {
    container.innerHTML = `
      <div class="page-head"><div>
        <div class="breadcrumb">Plugins · Tools</div>
        <h1>Ping Test</h1>
        <p>Check whether the router can reach a host, and how fast.</p>
      </div></div>
      <div class="panel" style="max-width:720px"><div class="panel-b">
        <div class="form-row">
          <div class="lbl">Host or IP</div>
          <div class="ctl">
            <input type="text" class="pg-host" value="openwrt.org" style="min-width:240px" />
            <button class="btn primary pg-run" type="button">Ping</button>
          </div>
        </div>
        <pre class="pg-out mono" style="white-space:pre-wrap;background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:14px;margin:8px 0 0;min-height:64px;font-size:12.5px;color:var(--ink)"></pre>
      </div></div>
      <details class="adv" style="max-width:720px"><summary>About this plugin</summary><div class="advb">Loaded at runtime from <span class="mono">plugins/ping/ping.js</span>. It uses the host API (<span class="mono">api.ubus.call('file','exec', …)</span>) and the core styles — UnTangled itself was not rebuilt to add it.</div></details>
    `;

    const host = container.querySelector('.pg-host');
    const btn = container.querySelector('.pg-run');
    const out = container.querySelector('.pg-out');

    const run = async () => {
      const target = host.value.trim();
      if (!target) return;
      btn.disabled = true;
      out.textContent = 'Pinging ' + target + '…';
      try {
        const r = await api.ubus.call('file', 'exec', { command: 'ping', params: ['-c', '3', '-w', '5', target] });
        out.textContent = (r && (r.stdout || r.stderr)) || 'No output.';
      } catch (e) {
        out.textContent = 'Failed: ' + (e && e.message ? e.message : String(e));
        api.toast('Ping failed');
      } finally {
        btn.disabled = false;
      }
    };

    btn.addEventListener('click', run);
    return () => btn.removeEventListener('click', run);
  }
};
