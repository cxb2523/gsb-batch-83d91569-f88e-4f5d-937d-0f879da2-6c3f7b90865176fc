import type { ReactNode } from "react";
import { Button } from "../ui/Button";
import { Field, SelectShell } from "../ui/Field";

// List chrome shared by Upcoming and the Completed Library.

export function GenreField({ genre, genres, onGenre }: { genre: string; genres: string[]; onGenre: (value: string) => void }) {
  return <Field label="Genre"><SelectShell><select className="field__control" value={genre} onChange={event => onGenre(event.target.value)}><option value="">All genres</option>{genres.map(name => <option key={name}>{name}</option>)}</select></SelectShell></Field>;
}

export function BulkActions({ label, count, onSelectAll, onClear, children }: { label: string; count: number; onSelectAll: () => void; onClear: () => void; children: ReactNode }) {
  if (count === 0) return null;
  return <div className="bulk-actions" aria-label={label}><span>{count} selected</span><Button small onClick={onSelectAll}>Select all</Button><Button small onClick={onClear}>Clear</Button>{children}</div>;
}

export function SyncState({ status, message }: { status: string; message?: string }) {
  if (status === "idle") return null;
  return <div className={`sync-strip ${status}`}>Sync: {status}{message ? ` - ${message}` : ""}</div>;
}
