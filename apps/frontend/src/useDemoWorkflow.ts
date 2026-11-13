import { useEffect, useState } from "react";
import type { ApiClient } from "./api/client";

// The sample library: whether it is loaded, and loading or removing it. `onChanged` reloads the screens
// that show library data afterwards.
export function useDemoWorkflow({ api, enabled, onChanged, onError }: {
  api: ApiClient;
  // Off when the app starts from a prepared state (tests of other screens).
  enabled: boolean;
  onChanged: () => Promise<unknown>;
  onError?: (action: string, error: unknown) => void;
}) {
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (enabled) api.getDemo().then(result => setLoaded(result.loaded), () => undefined);
  }, [api, enabled]);

  const change = async (action: string, request: () => Promise<{ loaded: boolean }>) => {
    try {
      setLoaded((await request()).loaded);
      await onChanged();
    } catch (error) {
      onError?.(action, error);
    }
  };

  return {
    loaded,
    actions: {
      load: () => change("load-sample-library", () => api.loadDemo()),
      remove: () => change("remove-sample-library", () => api.removeDemo())
    }
  };
}

export type DemoWorkflow = ReturnType<typeof useDemoWorkflow>;
