import { useEffect, useState } from "react";

// Settings → Sync: start the desktop app at login, in the tray. The operating system holds the choice,
// so this asks the desktop app for it; outside the packaged app the switch is not offered.
export function useStartAtLogin() {
  const [state, setState] = useState<StartAtLoginState>({ supported: false, platform: null, enabled: false });
  useEffect(() => {
    let live = true;
    void window.releaseTracker?.getStartAtLogin?.().then(next => { if (live) setState(next); }, () => undefined);
    return () => { live = false; };
  }, []);
  const setEnabled = async (on: boolean) => {
    const bridge = window.releaseTracker?.setStartAtLogin;
    if (!bridge) return;
    setState(current => ({ ...current, enabled: on }));
    try {
      setState(await bridge(on));
    } catch {
      setState(current => ({ ...current, enabled: !on }));
    }
  };
  return { ...state, setEnabled };
}
