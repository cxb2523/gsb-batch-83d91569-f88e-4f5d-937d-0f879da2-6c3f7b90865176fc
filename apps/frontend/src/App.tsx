import { CalendarView } from "./views/CalendarView";
import { CompletedDetailView } from "./views/CompletedDetailView";
import { CompletedLibraryView } from "./views/CompletedLibraryView";
import { CompletedManualGameView } from "./views/CompletedManualGameView";
import { DetailView } from "./views/DetailView";
import { UpcomingView } from "./views/UpcomingView";
import { ManualReleaseView } from "./views/ManualReleaseView";
import { lazy, Suspense } from "react";
import { SettingsView } from "./views/SettingsView";
import { useAppWorkflow, type AppState } from "./useAppWorkflow";
import type { ApiClient } from "./api/client";
import { ThemeMenu } from "./ui/ThemeMenu";
import { Button } from "./ui/Button";
import { FramedPanel } from "./ui/FramedPanel";
import { Backdrop } from "./ui/Backdrop";
import "./styles.css";

// The Randomizer is the largest screen and many sessions never open it, so its code loads on first visit.
const RandomizerView = lazy(() => import("./views/RandomizerView").then(module => ({ default: module.RandomizerView })));
// Year in Review is visited rarely, so it loads on first visit too.
const YearInReviewView = lazy(() => import("./views/YearInReviewView").then(module => ({ default: module.YearInReviewView })));

interface AppShellProps {
  apiBaseUrl: string;
  api?: ApiClient;
  initialState?: AppState;
  diagnosticsLogPath?: string;
  onOpenDiagnosticsLog?: () => void | Promise<unknown>;
}

export function AppShell({ apiBaseUrl, api, initialState, diagnosticsLogPath, onOpenDiagnosticsLog }: AppShellProps) {
  const workflow = useAppWorkflow({ apiBaseUrl, initialState, api });
  const {
    state,
    view,
    operationError,
    hasNativeWallpaperPicker,
    wallpaperUrl,
    detail,
    manual,
    releases,
    settings,
    syncSettings,
    demo,
    completedLibrary,
    randomizer,
    yearInReview,
    preferences: { palette, setPaletteId, themeAutoplay, setThemeAutoplay },
    eligibleReleases,
    groups,
    actions
  } = workflow;

  return (
    <main className="app-shell">
      <header className="topbar">
        <span className="topbar__brand">Game Release Tracker</span>
        <nav className="side-nav topbar__nav" aria-label="Primary navigation">
          <button type="button" className={view === "gallery" ? "active" : ""} onClick={() => actions.setView("gallery")}>Upcoming</button>
          <button type="button" className={view === "calendar" ? "active" : ""} onClick={() => actions.setView("calendar")}>Calendar</button>
          <button type="button" className={view.startsWith("completed") ? "active" : ""} onClick={() => actions.setView("completed-library")}>Completed Library</button>
          <button type="button" className={view === "randomizer" ? "active" : ""} onClick={() => actions.setView("randomizer")}>Randomizer</button>
          <button type="button" className={view === "year-in-review" ? "active" : ""} onClick={() => actions.setView("year-in-review")}>Year in Review</button>
          <button type="button" className={view === "settings" ? "active" : ""} onClick={() => actions.setView("settings")}>Settings</button>
        </nav>
        <ThemeMenu palette={palette} setPaletteId={setPaletteId} />
        <Button small className="topbar__sync" onClick={actions.sync}>Sync now</Button>
      </header>
      <div className="stage">
        {operationError && <FramedPanel className="operation-error">Action failed: {operationError}</FramedPanel>}
          {view === "gallery" && (
        <UpcomingView
          wallpaperUrl={wallpaperUrl ?? undefined}
          apiBaseUrl={apiBaseUrl}
          releases={releases}
          groups={groups}
          status={state.status}
          syncStatus={state.syncStatus}
          error={state.error}
          onDeleteSelected={actions.deleteSelected}
          onOpenDetail={actions.openDetail}
          onSetWatched={actions.setWatched}
          onAddGame={() => actions.setView("add")}
          demo={demo}
          onSetUpOwnLibrary={actions.setUpOwnLibrary}
        />
          )}

          {view === "calendar" && (
        <><Backdrop src={wallpaperUrl ?? undefined} blur={18} /><CalendarView
          apiBaseUrl={apiBaseUrl}
          items={eligibleReleases}
          onOpenDetail={actions.openDetail}
          onSync={actions.sync}
        /></>
          )}

          {view === "detail" && (
        <DetailView apiBaseUrl={apiBaseUrl} workflow={detail} onBack={actions.returnToReleaseList} />
          )}

          {view === "add" && (
        <><Backdrop src={wallpaperUrl || undefined} blur={18} /><ManualReleaseView manual={manual} onBack={() => actions.setView("gallery")} /></>
          )}

          {view === "completed-library" && (
        <CompletedLibraryView
          wallpaperUrl={wallpaperUrl ?? undefined}
          games={completedLibrary.games}
          groups={completedLibrary.groups}
          viewMode={completedLibrary.viewMode}
          status={completedLibrary.status}
          error={completedLibrary.error}
          onViewMode={completedLibrary.actions.setViewMode}
          onDeleteSelected={completedLibrary.actions.deleteSelected}
          onOpenDetail={completedLibrary.actions.openDetail}
          onAddManual={() => actions.setView("completed-add")}
        />
          )}

          {view === "completed-detail" && (
        <CompletedDetailView
          apiBaseUrl={apiBaseUrl}
          workflow={completedLibrary.detail}
          onBack={completedLibrary.actions.returnToLibrary}
          backLabel={completedLibrary.openedFrom === "year-in-review" ? "Year in Review" : undefined}
        />
          )}

          {view === "completed-add" && (
        <><Backdrop src={wallpaperUrl || undefined} blur={18} /><CompletedManualGameView manual={completedLibrary.manual} onBack={() => actions.setView("completed-library")} /></>
          )}

          {view === "randomizer" && (
        <Suspense fallback={<div className="state">Loading Randomizer...</div>}><RandomizerView
          workflow={randomizer}
          wallpaperUrl={wallpaperUrl ?? undefined}
          onOpenSettings={() => actions.setView("settings")}
        /></Suspense>
          )}

          {view === "year-in-review" && (
        <Suspense fallback={<div className="state">Loading Year in Review...</div>}><YearInReviewView
          workflow={yearInReview}
          apiBaseUrl={apiBaseUrl}
          onOpenGame={id => completedLibrary.actions.openGameFrom(id, "year-in-review")}
          onExit={() => actions.setView("gallery")}
        /></Suspense>
          )}

          {view === "settings" && (
        <><Backdrop src={wallpaperUrl ?? undefined} blur={18} /><SettingsView
          palette={palette}
          setPaletteId={setPaletteId}
          themeAutoplay={themeAutoplay}
          setThemeAutoplay={setThemeAutoplay}
          hasNativeWallpaperPicker={hasNativeWallpaperPicker}
          hasWallpaper={Boolean(wallpaperUrl)}
          onChooseWallpaper={actions.chooseWallpaper}
          onClearWallpaper={actions.clearWallpaper}
          workflow={settings}
          syncWorkflow={syncSettings}
          onBack={() => actions.setView("gallery")}
          diagnosticsLogPath={diagnosticsLogPath}
          onOpenDiagnosticsLog={onOpenDiagnosticsLog}
        /></>
          )}
      </div>
    </main>
  );
}
