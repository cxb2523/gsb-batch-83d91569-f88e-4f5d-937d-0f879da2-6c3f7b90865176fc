// UnTangled Mesh Wi-Fi — the frontend half of the mesh feature. It drives the
// device-side `untangled.mesh` ubus helper (shipped by the `untangled-mesh`
// package). If that helper isn't installed, the screen degrades to an
// "install the backend" card — it never errors and never touches config on its
// own. Loaded at runtime via the plugin system; core is not rebuilt to add it.
//
// Design notes (future-proof):
//  - All risky orchestration lives in the backend helper, not here. The UI only
//    calls named, versioned methods (info/status/nodes/set_roaming/join/leave).
//  - The one write wired up now is set_roaming (enable 802.11r/k/v + dawn): it
//    keeps SSID/password unchanged, so it can't lock anyone out.
//  - Multi-router onboarding is presented as a guided, reversible flow; the
//    actual satellite apply is a later phase and the helper reports it as
//    "planned" rather than doing anything half-finished.

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
));

export default {
  id: 'mesh',
  title: 'Mesh Wi-Fi',
  group: 'General',
  icon: 'i-ext',
  order: 5,
  commands: [{ label: 'Open Mesh Wi-Fi', run: () => { location.hash = 'mesh'; } }],

  mount(container, api) {
    let alive = true;

    const notInstalled = () => `
      <div class="page-head"><div><div class="breadcrumb">General</div><h1>Mesh Wi-Fi</h1>
        <p>Blanket your home in one Wi-Fi name, with devices roaming smoothly between routers.</p></div></div>
      <div class="panel" style="max-width:720px"><div class="panel-b">
        <p style="margin:0 0 6px"><b>Mesh isn't set up on this router yet.</b></p>
        <p class="hint" style="margin:0 0 10px">Install the <span class="mono">untangled-mesh</span> package to enable it. It adds seamless roaming
          (<span class="mono">dawn</span>) and mesh discovery (<span class="mono">umdns</span>), and a small helper this screen talks to.</p>
        <p class="hint" style="margin:0">On each router you want in the mesh: <span class="mono">apk add untangled-mesh</span>
          (or <span class="mono">opkg install untangled-mesh</span>), then reopen this screen.</p>
      </div></div>`;

    const loading = (msg) => `
      <div class="page-head"><div><div class="breadcrumb">General</div><h1>Mesh Wi-Fi</h1>
        <p>Blanket your home in one Wi-Fi name, with devices roaming smoothly between routers.</p></div></div>
      <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">${esc(msg)}</div></div>`;

    const roleLabel = (r) => r === 'controller' ? 'Main router' : r === 'agent' ? 'Mesh point' : 'Standalone';

    const view = (info, status, nodes) => {
      const n = Array.isArray(nodes) ? nodes : [];
      const rows = n.length ? n.map((x) => `
        <tr>
          <td><div class="cname"><span class="mi"><svg><use href="#d-router"/></svg></span>
            <span><b>${esc(x.name || x.ip || 'node')}</b><small class="mono">${esc(x.ip || '')}</small></span></div></td>
          <td>${esc(roleLabel(x.role))}</td>
          <td class="mono">${x.signal != null && x.signal !== '' ? esc(x.signal) + ' dBm' : (x.self ? 'this router' : '—')}</td>
        </tr>`).join('') : `<tr><td colspan="3" style="color:var(--muted);padding:18px">Only this router so far.</td></tr>`;

      const code = status.join_code || '';
      const dawnWarn = info && info.dawn === false
        ? `<div class="hint" style="margin-top:8px">Tip: install <span class="mono">dawn</span> for the smoothest roaming between routers.</div>` : '';

      return `
      <div class="page-head"><div><div class="breadcrumb">General</div><h1>Mesh Wi-Fi</h1>
        <p>Blanket your home in one Wi-Fi name, with devices roaming smoothly between routers.</p></div></div>

      <div class="tiles" style="grid-template-columns:repeat(3,1fr);max-width:720px">
        <div class="tile"><div class="k">This router</div><div class="v" style="font-size:16px;margin-top:11px">${esc(roleLabel(status.role))}</div></div>
        <div class="tile"><div class="k">Backhaul</div><div class="v" style="font-size:16px;margin-top:11px">${esc(status.backhaul || 'wired')}</div></div>
        <div class="tile"><div class="k">Routers</div><div class="v">${n.length || 1}</div></div>
      </div>

      <div class="panel" style="max-width:720px;margin-bottom:16px">
        <div class="panel-h"><h2>Seamless roaming</h2><span class="sub">802.11r / k / v${info && info.dawn ? ' · dawn' : ''}</span></div>
        <div class="panel-b">
          <div class="form-row">
            <div class="lbl">Hand devices between routers automatically
              <small>phones switch to the strongest router without dropping</small></div>
            <div class="ctl"><label class="toggle"><input type="checkbox" class="mx-roam" ${status.roaming ? 'checked' : ''}/>
              <span class="track"></span><span class="knob"></span></label></div>
          </div>
          ${dawnWarn}
        </div>
      </div>

      <div class="panel" style="max-width:720px;margin-bottom:16px">
        <div class="panel-h"><h2>Routers in this mesh</h2><span class="sub">${n.length || 1}</span></div>
        <div style="overflow-x:auto"><table class="clients">
          <thead><tr><th>Router</th><th>Role</th><th>Signal</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </div>

      <div class="panel" style="max-width:720px;margin-bottom:16px">
        <div class="panel-h"><h2>Role</h2><span class="sub">${esc(roleLabel(status.role))}</span></div>
        <div class="panel-b">
          <div class="hint" style="margin:0 0 12px">${status.role === 'controller'
            ? 'This router leads the mesh. Add satellites with the code below.'
            : status.role === 'agent'
              ? 'This router is a mesh point following the main router.'
              : 'Standalone. Make this the main router, or join an existing mesh below.'}</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            ${status.role !== 'controller' ? '<button class="btn primary mx-makemain" type="button">Make this the main router</button>' : ''}
            ${status.role !== 'standalone' ? '<button class="btn mx-leave" type="button">Leave mesh</button>' : ''}
          </div>
        </div>
      </div>

      ${status.role === 'controller' ? `
      <div class="panel" style="max-width:720px;margin-bottom:16px">
        <div class="panel-h"><h2>Add another router</h2><span class="sub">extend coverage</span></div>
        <div class="panel-b">
          <ol style="margin:0 0 4px;padding-left:20px;line-height:1.9">
            <li>Install UnTangled + <span class="mono">untangled-mesh</span> on the second router.</li>
            <li>Connect it to this one — by Ethernet (most reliable) or over Wi-Fi.</li>
            <li>On the new router, open Mesh Wi-Fi → <b>Join an existing mesh</b>, then paste this code.</li>
          </ol>
          <div class="form-row" style="border:0"><div class="lbl">Join code</div>
            <div class="ctl"><input type="text" class="mx-code mono" readonly value="${esc(code)}" style="min-width:280px" />
              <button class="btn mx-copy" type="button">Copy</button></div></div>
        </div>
      </div>` : ''}

      <div class="panel" style="max-width:720px">
        <div class="panel-h"><h2>Join an existing mesh</h2><span class="sub">for a satellite router</span></div>
        <div class="panel-b">
          <div class="form-row" style="border:0"><div class="lbl">Join code<small>from the main router's Mesh screen</small></div>
            <div class="ctl"><input type="text" class="mx-joincode mono" placeholder="paste code" style="min-width:280px" />
              <button class="btn primary mx-join" type="button">Join</button></div></div>
          <div class="hint">Matches this router's Wi-Fi name &amp; password to the mesh and turns on roaming. To share one network,
            also connect it to the main router by Ethernet and switch it to Access Point mode on the LAN screen.</div>
        </div>
      </div>`;
    };

    const setHTML = (html) => { if (alive) container.innerHTML = html; };

    async function render() {
      setHTML(loading('Checking mesh status…'));
      let info, status, nodes;
      try {
        status = await api.ubus.call('untangled.mesh', 'status', {});
      } catch (e) {
        // NOT_FOUND / object missing -> backend not installed.
        setHTML(notInstalled());
        return;
      }
      try { info = await api.ubus.call('untangled.mesh', 'info', {}); } catch { info = {}; }
      try { const r = await api.ubus.call('untangled.mesh', 'nodes', {}); nodes = r && r.nodes; } catch { nodes = []; }
      if (!alive) return;

      setHTML(view(info || {}, status || {}, nodes || []));

      const roam = container.querySelector('.mx-roam');
      if (roam) roam.addEventListener('change', async () => {
        roam.disabled = true;
        try {
          await api.ubus.call('untangled.mesh', 'set_roaming', { enable: roam.checked });
          api.toast(roam.checked ? 'Seamless roaming turned on' : 'Seamless roaming turned off');
        } catch {
          roam.checked = !roam.checked;
          api.toast('Could not change roaming');
        } finally {
          roam.disabled = false;
        }
      });

      const copy = container.querySelector('.mx-copy');
      if (copy) copy.addEventListener('click', () => {
        const el = container.querySelector('.mx-code');
        if (!el || !el.value) { api.toast('No join code yet'); return; }
        try { navigator.clipboard.writeText(el.value); api.toast('Join code copied'); }
        catch { el.select(); api.toast('Select and copy the code'); }
      });

      const makeMain = container.querySelector('.mx-makemain');
      if (makeMain) makeMain.addEventListener('click', async () => {
        makeMain.disabled = true;
        try {
          await api.ubus.call('untangled.mesh', 'set_role', { role: 'controller', backhaul: 'wired' });
          api.toast('This router is now the mesh main');
          render();
        } catch { makeMain.disabled = false; api.toast('Could not change role'); }
      });

      const leave = container.querySelector('.mx-leave');
      if (leave) leave.addEventListener('click', async () => {
        leave.disabled = true;
        try { await api.ubus.call('untangled.mesh', 'leave', {}); api.toast('Left the mesh'); render(); }
        catch { leave.disabled = false; api.toast('Could not leave the mesh'); }
      });

      const join = container.querySelector('.mx-join');
      if (join) join.addEventListener('click', async () => {
        const el = container.querySelector('.mx-joincode');
        const codeVal = el && el.value.trim();
        if (!codeVal) { api.toast('Paste the join code first'); return; }
        join.disabled = true;
        try {
          const r = await api.ubus.call('untangled.mesh', 'join', { code: codeVal });
          if (r && r.ok) { api.toast(r.message || 'Joined the mesh'); render(); }
          else { join.disabled = false; api.toast((r && r.message) || 'That join code isn\'t valid'); }
        } catch { join.disabled = false; api.toast('Could not join the mesh'); }
      });
    }

    render();
    return () => { alive = false; };
  }
};
