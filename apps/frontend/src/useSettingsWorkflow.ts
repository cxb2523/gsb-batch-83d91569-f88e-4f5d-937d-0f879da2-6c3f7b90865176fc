import { useState } from "react";
import type { SettingsStatus } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import { useLoadOnFirstOpen } from "./useLoadOnFirstOpen";

// The unsaved IGDB credential drafts typed on the Settings page.
interface IgdbSettingsForm {
  IGDB_CLIENT_ID: string;
  IGDB_CLIENT_SECRET: string;
  IGDB_ACCESS_TOKEN: string;
}

export const SETTINGS_TABS = ["Appearance", "API keys", "Sync", "Diagnostics"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

// Nothing else works without IGDB keys, so Settings opens on API keys while they need attention.
function keysNeedAttention(status: SettingsStatus | undefined) {
  if (!status) return false;
  return status.credentialStatus.status !== "ready" || Object.values(status.credentials).some(credential => credential.unreadable);
}

const emptySettings: IgdbSettingsForm = {
  IGDB_CLIENT_ID: "",
  IGDB_CLIENT_SECRET: "",
  IGDB_ACCESS_TOKEN: ""
};

// The Settings page: saved credential status (loaded on first open), the credential drafts, save/clear/test.
export function useSettingsWorkflow({
  api,
  initialStatus,
  loadOnOpen,
  onError
}: {
  api: ApiClient;
  initialStatus?: SettingsStatus;
  loadOnOpen: boolean;
  onError?: (action: string, error: unknown) => void;
}) {
  const [settings, setSettings] = useState<IgdbSettingsForm>(emptySettings);
  const [steamGridDbKey, setSteamGridDbKey] = useState("");
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatus | undefined>(initialStatus);
  const [tab, setTabState] = useState<SettingsTab>(keysNeedAttention(initialStatus) ? "API keys" : "Appearance");
  const [tabChosen, setTabChosen] = useState(false);
  const setTab = (next: SettingsTab) => {
    setTabChosen(true);
    setTabState(next);
  };

  useLoadOnFirstOpen(loadOnOpen, () => {
    api.getSettings().then(status => {
      setSettingsStatus(status);
      if (!tabChosen && keysNeedAttention(status)) setTabState("API keys");
    }, error => onError?.("load-settings", error));
  });

  const resetDrafts = () => {
    setSettings(emptySettings);
    setSteamGridDbKey("");
  };

  const saveSettings = async () => {
    try {
      const result = await api.patchSettings({ ...settings, STEAMGRIDDB_API_KEY: steamGridDbKey });
      setSettingsStatus(result.settings);
      resetDrafts();
    } catch (error) {
      onError?.("save-settings", error);
    }
  };

  const clearCredentials = async () => {
    try {
      const result = await api.clearCredentials();
      setSettingsStatus(result.settings);
      resetDrafts();
    } catch (error) {
      onError?.("clear-credentials", error);
    }
  };

  const testCredentials = async () => {
    try {
      const { credentialStatus } = await api.testCredentials();
      setSettingsStatus(current => ({ autoSyncDue: false, credentials: emptyCredentialFlags(), ...current, credentialStatus }));
    } catch (error) {
      onError?.("test-credentials", error);
    }
  };

  return {
    settings,
    settingsStatus,
    steamGridDbKey,
    tab,
    actions: {
      setTab,
      setSettings,
      setSteamGridDbKey,
      saveSettings,
      clearCredentials,
      testCredentials
    }
  };
}

export type SettingsWorkflow = ReturnType<typeof useSettingsWorkflow>;

function emptyCredentialFlags(): SettingsStatus["credentials"] {
  return {
    IGDB_CLIENT_ID: { saved: false },
    IGDB_CLIENT_SECRET: { saved: false },
    IGDB_ACCESS_TOKEN: { saved: false },
    STEAMGRIDDB_API_KEY: { saved: false }
  };
}
