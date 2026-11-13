import { useEffect, useState } from "react";
import type { CompletedGameDetail, CompletedGameListItem, ReleaseDetail, ReleaseListItem, SettingsStatus, SyncStatus } from "../../../shared/types";
import type { ApiClient } from "./api/client";

export type AppView =
  | "gallery"
  | "calendar"
  | "detail"
  | "settings"
  | "add"
  | "completed-library"
  | "completed-detail"
  | "completed-add"
  | "randomizer"
  | "year-in-review";

// A pre-loaded starting point for the app (tests and previews). When given, workflows start from it
// instead of fetching on mount.
export interface AppState {
  status: "starting" | "ready" | "error";
  releases: ReleaseListItem[];
  syncStatus: SyncStatus;
  settingsStatus?: SettingsStatus;
  error?: string;
  operationError?: string;
  initialView?: AppView;
  initialDetail?: ReleaseDetail;
  completedLibraryStatus?: "starting" | "ready" | "error";
  completedGames?: CompletedGameListItem[];
  initialCompletedDetail?: CompletedGameDetail;
}

// Browser dialogs, injected so workflows can be driven from tests without stubbing globals.
export interface Dialogs {
  confirm(message: string): boolean;
  alert(message: string): void;
}

const browserDialogs: Dialogs = {
  confirm: message => globalThis.confirm(message),
  alert: message => globalThis.alert?.(message)
};

export type AppShell = ReturnType<typeof useAppShell>;

// App-wide state that belongs to no single collection: the current view, the
// operation-error banner, UI event logging, and unexpected-error reporting.
export function useAppShell({ api, initialView, initialOperationError, dialogs = browserDialogs }: {
  api: ApiClient;
  initialView?: AppView;
  initialOperationError?: string;
  dialogs?: Dialogs;
}) {
  const [view, setViewState] = useState<AppView>(initialView ?? "gallery");
  const setView = (next: AppView) => setViewState(next);
  const [operationError, setOperationError] = useState<string | undefined>(initialOperationError);

  const logUiEvent = (event: string, details: Record<string, unknown> = {}) => {
    void api.logEvent(event, { view, ...details }).catch(() => undefined);
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const showUnexpectedError = (source: string, error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      setOperationError(message);
      void api.logEvent("ui.unexpected_error", { source, error: message }).catch(() => undefined);
    };
    const onError = (event: ErrorEvent) => showUnexpectedError("window.error", event.error ?? event.message);
    const onRejection = (event: PromiseRejectionEvent) => showUnexpectedError("window.unhandledrejection", event.reason);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [api]);

  const reportOperationError = (action: string, error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    setOperationError(message);
    logUiEvent("ui.operation.failed", { action, error: message });
    return message;
  };

  const clearOperationError = () => setOperationError(undefined);

  return {
    view,
    setView,
    operationError,
    showOperationMessage: (message: string) => setOperationError(message),
    reportOperationError,
    clearOperationError,
    logUiEvent,
    dialogs
  };
}
