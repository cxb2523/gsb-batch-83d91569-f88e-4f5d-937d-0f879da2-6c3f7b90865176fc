import { useMemo, useState } from "react";
import type { ReleaseListItem } from "../../../../shared/types";
import { artworkSrc } from "../artwork";
import { FramedPanel } from "../ui/FramedPanel";

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function parseIsoDate(value: string | null | undefined): { year: number; month: number; day: number } | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
}

export function CalendarView({
  apiBaseUrl,
  items,
  onOpenDetail,
  onSync
}: {
  apiBaseUrl: string;
  items: ReleaseListItem[];
  onOpenDetail: (item: ReleaseListItem) => void;
  onSync: () => void;
}) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const eventsByDay = useMemo(() => {
    const map = new Map<string, ReleaseListItem[]>();
    for (const item of items) {
      if (item.datePrecision !== "Exact") continue;
      const parsed = parseIsoDate(item.releaseDate);
      if (!parsed) continue;
      if (parsed.year !== year || parsed.month !== month) continue;
      const key = String(parsed.day);
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return map;
  }, [items, year, month]);

  const monthLabel = `${MONTH_NAMES[month]} ${year}`;
  const scheduledCount = Array.from(eventsByDay.values()).reduce((sum, list) => sum + list.length, 0);

  const firstDay = new Date(year, month, 1);
  const startWeekday = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: Array<number | null> = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const isToday = (day: number | null) => {
    if (day === null) return false;
    return year === today.getFullYear() && month === today.getMonth() && day === today.getDate();
  };

  const goPrev = () => {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
  };
  const goNext = () => {
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
  };
  const goToday = () => { setYear(today.getFullYear()); setMonth(today.getMonth()); };

  return (
    <FramedPanel className="tab-panel calendar-panel">
      <div className="tab-panel-header">
        <div>
          <h1>{monthLabel}</h1>
          <p>{scheduledCount} {scheduledCount === 1 ? "release" : "releases"} scheduled this month</p>
        </div>
        <div className="tab-panel-actions">
          <button type="button" className="secondary" onClick={goPrev}>‹</button>
          <button type="button" className="secondary" onClick={goToday}>Today</button>
          <button type="button" className="secondary" onClick={goNext}>›</button>
          <button type="button" className="action-sync" onClick={onSync}>Sync now</button>
        </div>
      </div>

      <div className="calendar-grid">
        {DAY_NAMES.map(day => (
          <div key={day} className="calendar-weekday">{day}</div>
        ))}
        {cells.map((day, idx) => {
          if (day === null) return <div key={`empty-${idx}`} className="calendar-cell empty" />;
          const dayEvents = eventsByDay.get(String(day)) ?? [];
          return (
            <div key={day} className={`calendar-cell${isToday(day) ? " today" : ""}`}>
              <div className="calendar-day-number">{day}</div>
              <div className="calendar-events">
                {dayEvents.slice(0, 3).map(item => {
                  const art = item.artworks[0];
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className="calendar-event"
                      onClick={() => onOpenDetail(item)}
                      title={`${item.title} — ${item.publishers[0] ?? ""} · ${item.platforms[0] ?? ""}`}
                    >
                      {art && (
                        <img
                          className="calendar-event-art"
                          alt=""
                          src={artworkSrc(art, "grid", apiBaseUrl)}
                          loading="lazy" draggable={false}
                        />
                      )}
                      <span className="calendar-event-text">
                        <span className="calendar-event-title">{item.title}</span>
                        <span className="calendar-event-meta">{item.platforms[0] ?? ""}</span>
                      </span>
                    </button>
                  );
                })}
                {dayEvents.length > 3 && <span className="calendar-more">+{dayEvents.length - 3} more</span>}
              </div>
            </div>
          );
        })}
      </div>
    </FramedPanel>
  );
}
