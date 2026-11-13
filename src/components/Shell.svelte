<script lang="ts">
  import Topbar from './Topbar.svelte';
  import Sidebar from './Sidebar.svelte';
  import CommandPalette from './CommandPalette.svelte';
  import Placeholder from '../screens/Placeholder.svelte';
  import NetworkMap from '../screens/NetworkMap.svelte';
  import Devices from '../screens/Devices.svelte';
  import TrafficMonitor from '../screens/TrafficMonitor.svelte';
  import UsageHistory from '../screens/UsageHistory.svelte';
  import SystemLog from '../screens/SystemLog.svelte';
  import Wireless from '../screens/Wireless.svelte';
  import GuestNetwork from '../screens/GuestNetwork.svelte';
  import Firewall from '../screens/Firewall.svelte';
  import Dmz from '../screens/Dmz.svelte';
  import PortForwarding from '../screens/PortForwarding.svelte';
  import ParentalControls from '../screens/ParentalControls.svelte';
  import ExtendWifi from '../screens/ExtendWifi.svelte';
  import NetworkProtection from '../screens/NetworkProtection.svelte';
  import Vpn from '../screens/Vpn.svelte';
  import Tailscale from '../screens/Tailscale.svelte';
  import Wan from '../screens/Wan.svelte';
  import Ddns from '../screens/Ddns.svelte';
  import Qos from '../screens/Qos.svelte';
  import DualWan from '../screens/DualWan.svelte';
  import Upnp from '../screens/Upnp.svelte';
  import UsbApps from '../screens/UsbApps.svelte';
  import Firmware from '../screens/Firmware.svelte';
  import Lan from '../screens/Lan.svelte';
  import Ipv6 from '../screens/Ipv6.svelte';
  import Administration from '../screens/Administration.svelte';
  import Software from '../screens/Software.svelte';
  import Toasts from './Toasts.svelte';
  import ConfirmApply from './ConfirmApply.svelte';
  import PluginHost from './PluginHost.svelte';
  import { onMount } from 'svelte';
  import { route } from '../lib/stores';
  import { titles } from '../lib/nav';
  import { plugins, loadPlugins } from '../lib/plugins';

  let sidebarOpen = false;
  onMount(loadPlugins);

  // Route id -> screen component. Unmapped ids fall back to Placeholder.
  const screens: Record<string, any> = {
    map: NetworkMap,
    devices: Devices,
    traffic: TrafficMonitor,
    usage: UsageHistory,
    log: SystemLog,
    wireless: Wireless,
    guest: GuestNetwork,
    firewall: Firewall,
    dmz: Dmz,
    portfwd: PortForwarding,
    parental: ParentalControls,
    extend: ExtendWifi,
    aiprotect: NetworkProtection,
    vpn: Vpn,
    tailscale: Tailscale,
    wan: Wan,
    ddns: Ddns,
    qos: Qos,
    dualwan: DualWan,
    upnp: Upnp,
    usb: UsbApps,
    firmware: Firmware,
    lan: Lan,
    ipv6: Ipv6,
    admin: Administration,
    software: Software
  };
  $: Current = screens[$route];
  $: activePlugin = $plugins.find((p) => p.id === $route) || null;
</script>

<div class="app">
  <div class="brandbar">
    <div class="logo"><svg width="18" height="18" aria-hidden="true"><use href="#i-wifi" /></svg></div>
    <div class="brand-txt"><b>UnTangled</b><span>Router&nbsp;UI</span></div>
  </div>

  <Topbar onMenu={() => (sidebarOpen = !sidebarOpen)} />
  <Sidebar open={sidebarOpen} onNavigate={() => (sidebarOpen = false)} />

  <main class="main">
    {#if Current}
      <svelte:component this={Current} />
    {:else if activePlugin}
      <PluginHost plugin={activePlugin} />
    {:else}
      <Placeholder id={$route} title={titles[$route] ?? 'UnTangled'} />
    {/if}
  </main>
</div>

<CommandPalette />
<Toasts />
<ConfirmApply />
