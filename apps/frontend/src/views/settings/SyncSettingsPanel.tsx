import { ALL_PLATFORM_FAMILIES, PLATFORM_FAMILIES } from "../../../../../shared/constants";
import type { SyncSettingsWorkflow } from "../../useSyncSettingsWorkflow";
import { useStartAtLogin } from "../../useStartAtLogin";


export function SyncSettingsPanel({ workflow }: { workflow: SyncSettingsWorkflow }) {
  const { settings, searchText, results, notFound, actions } = workflow;
  const startAtLogin = useStartAtLogin();
  if (!settings) return <p>Loading sync settings...</p>;
  const tracked = new Set(settings.publishers.map(publisher => publisher.id));
  return (
    <>
      <section className="settings-section">
        <h3>Publishers</h3>
        <p>Sync looks for upcoming games these companies publish or develop.</p>
        {settings.publishers.length === 0
          ? <p className="sync-publishers__empty">No publishers tracked yet, so Sync has nothing to look for. Search for the ones you follow, or start with a suggested set.</p>
          : (
            <ul className="sync-publishers">
              {settings.publishers.map(publisher => (
                <li className="sync-publishers__chip" key={publisher.id}>
                  <span>{publisher.name}</span>
                  <button type="button" className="secondary inline" aria-label={`Stop tracking ${publisher.name}`} onClick={() => void actions.untrack(publisher.id)}>×</button>
                </li>
              ))}
            </ul>
          )}
        <form className="settings-actions" onSubmit={event => { event.preventDefault(); void actions.search(); }}>
          <input aria-label="Search publishers" placeholder="Capcom, Atlus, Devolver..." value={searchText} onChange={event => actions.setSearchText(event.target.value)} />
          <button type="submit" disabled={searchText.trim().length < 2} onClick={event => { event.preventDefault(); void actions.search(); }}>Search</button>
          <button type="button" className="secondary" onClick={() => void actions.trackSuggested()}>Add suggested publishers</button>
        </form>
        {notFound.length > 0 && <p>IGDB didn't know: {notFound.join(", ")}</p>}
        {results && (
          results.length === 0
            ? <p>No IGDB company matches that name.</p>
            : (
              <ul className="sync-results">
                {results.map(publisher => (
                  <li key={publisher.id}>
                    <span>{publisher.name}</span>
                    {tracked.has(publisher.id)
                      ? <span className="sync-results__tracked">Tracked</span>
                      : <button type="button" className="secondary inline" aria-label={`Add ${publisher.name}`} onClick={() => void actions.track(publisher)}>Add</button>}
                  </li>
                ))}
              </ul>
            )
        )}
      </section>

      <section className="settings-section">
        <h3>Platforms</h3>
        <div className="sync-platforms">
          {ALL_PLATFORM_FAMILIES.map(platform => {
            const on = settings.platforms.includes(platform);
            return (
              <label key={platform}>
                <input type="checkbox" className="check" aria-label={PLATFORM_FAMILIES[platform].label} checked={on} disabled={on && settings.platforms.length === 1} onChange={() => void actions.togglePlatform(platform)} />
                {" "}{PLATFORM_FAMILIES[platform].label}
              </label>
            );
          })}
        </div>
      </section>

      <section className="settings-section">
        <h3>Release window</h3>
        <label className="sync-track-from">Track releases from
          <input type="date" aria-label="Track releases from" value={settings.trackFrom} onChange={event => void actions.setTrackFrom(event.target.value)} />
        </label>
        <label className="sync-auto">
          <input type="checkbox" className="check" aria-label="Sync automatically when the app starts" checked={settings.autoSync} onChange={event => void actions.setAutoSync(event.target.checked)} />
          {" "}Sync automatically when the app starts, and every 12 hours while it stays open
        </label>
        <label className="sync-auto">
          <input type="checkbox" className="check" aria-label="Notify me about watched games" checked={settings.alerts} onChange={event => void actions.setAlerts(event.target.checked)} />
          {" "}Notify me when a watched game comes out or its date changes (desktop app)
        </label>
        {startAtLogin.supported && (
          <label className="sync-auto">
            <input type="checkbox" className="check" aria-label="Start at login, in the tray" checked={startAtLogin.enabled} onChange={event => void startAtLogin.setEnabled(event.target.checked)} />
            {" "}{startAtLogin.platform === "linux" ? "Start when I log in, in the tray" : "Start with Windows, in the tray"}
          </label>
        )}
      </section>
    </>
  );
}
