import type { DateChangeKind, ReleaseAlert } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";
import { createSyncSettingsStore } from "../sync/syncSettingsStore";

// A date change older than this is history, not news. So is one from before the user watched the game.
const CHANGE_NEWS_DAYS = 7;

const changeTitle: Record<DateChangeKind, string> = {
  delayed: "Delayed",
  earlier: "Moved up",
  announced: "Release date announced"
};

// The alerts not yet shown for the games the user watches, each handed out once: a watched game whose
// exact release day is today, and each recent date change a sync recorded for one. Only the desktop
// app asks, and it shows them as system notifications. Nothing while alerts are off in Settings.
export function takeReleaseAlerts(db: TrackerDatabase, today: Date): ReleaseAlert[] {
  if (!createSyncSettingsStore(db).read().alerts) return [];
  const day = localDay(today);
  const watched = "join user_release_state state on state.release_id = releases.id and state.watched = 1 and state.hidden = 0 and releases.eligible = 1";

  const outToday = db.prepare(`
    select releases.id releaseId, releases.title title from releases ${watched}
    where releases.date_precision = 'Exact' and releases.release_date = ?
      and not exists (select 1 from release_alerts_sent sent where sent.release_id = releases.id and sent.alert_key = 'out:' || ?)
    order by releases.title
  `).all(day, day) as Array<{ releaseId: string; title: string }>;

  const changes = db.prepare(`
    select changes.id changeId, releases.id releaseId, releases.title title, changes.kind kind, changes.from_text fromText, changes.to_text toText
    from release_date_changes changes
    join releases on releases.id = changes.release_id ${watched}
    where changes.changed_at >= datetime('now', ?) and changes.changed_at >= state.updated_at
      and not exists (select 1 from release_alerts_sent sent where sent.release_id = releases.id and sent.alert_key = 'change:' || changes.id)
    order by changes.id
  `).all(`-${CHANGE_NEWS_DAYS} days`) as Array<{ changeId: number; releaseId: string; title: string; kind: DateChangeKind; fromText: string; toText: string }>;

  const markSent = db.prepare("insert or ignore into release_alerts_sent (release_id, alert_key) values (?, ?)");
  const alerts: ReleaseAlert[] = [];
  for (const game of outToday) {
    markSent.run(game.releaseId, `out:${day}`);
    alerts.push({ releaseId: game.releaseId, kind: "out", title: `Out today: ${game.title}`, body: "A game on your watchlist comes out today." });
  }
  for (const change of changes) {
    markSent.run(change.releaseId, `change:${change.changeId}`);
    alerts.push({
      releaseId: change.releaseId,
      kind: change.kind,
      title: `${changeTitle[change.kind]}: ${change.title}`,
      body: change.kind === "announced" ? `Now ${change.toText} (was ${change.fromText}).` : `Now ${change.toText}, was ${change.fromText}.`
    });
  }
  return alerts;
}

// The user's calendar day, as release dates are stored ("2027-03-14").
function localDay(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
