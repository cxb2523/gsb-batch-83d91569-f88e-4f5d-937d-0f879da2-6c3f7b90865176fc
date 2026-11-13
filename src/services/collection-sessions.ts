// Collection sessions for the Messages page.
//
// A collection session is one auditable run of "subscribe to a subject and
// gather what arrives". Unlike the old fire-and-forget subscription list, a
// session records its lifecycle (collecting -> stopped | interrupted), how
// many messages it captured, when the last one arrived, and why it ended if
// it ended abnormally.
//
// Sessions are deliberately NOT persisted: they describe live subscriptions,
// so keeping them in localStorage would resurrect phantom "collecting" states
// after a reload. They are also kept fully separate from custom topics
// (bookmarks) — deleting a bookmark must never delete session history.
//
// This module is pure state-transition logic (arrays in, arrays out) so it
// can be unit-tested without React or a NATS server.

export type SessionStatus = 'collecting' | 'stopped' | 'interrupted';

export interface CollectedMessage {
  id: string;
  subject: string;
  data: string;
  headers?: Record<string, string>;
  timestamp: Date;
  replyTo?: string;
}

export interface CollectionSession {
  id: string;
  subject: string;
  queueGroup?: string;
  status: SessionStatus;
  /** Always equals messages.length — the count is derived, never tracked separately. */
  messageCount: number;
  startedAt: Date;
  lastMessageAt: Date | null;
  /** Set when the session leaves the collecting state (stopped or interrupted). */
  endedAt: Date | null;
  /** Why the session ended abnormally (interrupt reason or subscribe failure). */
  lastError: string | null;
  /** Newest first. Capped at MAX_SESSION_MESSAGES. */
  messages: CollectedMessage[];
}

/** Per-session retention cap. The count never exceeds the retained detail. */
export const MAX_SESSION_MESSAGES = 1000;

let sessionCounter = 0;

function nextSessionId(): string {
  sessionCounter += 1;
  return `sess_${Date.now()}_${sessionCounter}`;
}

export function createSession(subject: string, queueGroup?: string, now: Date = new Date()): CollectionSession {
  return {
    id: nextSessionId(),
    subject,
    queueGroup: queueGroup || undefined,
    status: 'collecting',
    messageCount: 0,
    startedAt: now,
    lastMessageAt: null,
    endedAt: null,
    lastError: null,
    messages: [],
  };
}

/** The single session currently collecting on a subject, if any. */
export function findActiveSession(
  sessions: CollectionSession[],
  subject: string,
): CollectionSession | undefined {
  return sessions.find((s) => s.subject === subject && s.status === 'collecting');
}

/** The most recently started session for a subject (any status). */
export function findLatestSession(
  sessions: CollectionSession[],
  subject: string,
): CollectionSession | undefined {
  let latest: CollectionSession | undefined;
  for (const s of sessions) {
    if (s.subject !== subject) continue;
    if (!latest || s.startedAt.getTime() >= latest.startedAt.getTime()) latest = s;
  }
  return latest;
}

export interface StartSessionResult {
  sessions: CollectionSession[];
  session: CollectionSession;
  /** True when an already-collecting session was reused instead of creating a new one. */
  reused: boolean;
}

/**
 * Start collecting on a subject. A subject may have at most one collecting
 * session: if one exists it is returned unchanged (reused) so a second click
 * can never spawn a parallel subscription.
 */
export function startSession(
  sessions: CollectionSession[],
  subject: string,
  queueGroup?: string,
  now: Date = new Date(),
): StartSessionResult {
  const active = findActiveSession(sessions, subject);
  if (active) {
    return { sessions, session: active, reused: true };
  }
  const session = createSession(subject, queueGroup, now);
  return { sessions: [...sessions, session], session, reused: false };
}

/** Append a message to a collecting session. No-op for stopped/interrupted/unknown sessions. */
export function recordMessage(
  sessions: CollectionSession[],
  sessionId: string,
  message: CollectedMessage,
): CollectionSession[] {
  return sessions.map((s) => {
    if (s.id !== sessionId || s.status !== 'collecting') return s;
    const messages = [message, ...s.messages].slice(0, MAX_SESSION_MESSAGES);
    return {
      ...s,
      messages,
      messageCount: messages.length,
      lastMessageAt: message.timestamp,
    };
  });
}

/** Stop a collecting session. The record stays in the list with its count frozen. */
export function stopSession(
  sessions: CollectionSession[],
  sessionId: string,
  now: Date = new Date(),
): CollectionSession[] {
  return sessions.map((s) =>
    s.id === sessionId && s.status === 'collecting'
      ? { ...s, status: 'stopped' as const, endedAt: now }
      : s,
  );
}

/** Mark a single collecting session as interrupted with a reason. */
export function interruptSession(
  sessions: CollectionSession[],
  sessionId: string,
  reason: string,
  now: Date = new Date(),
): CollectionSession[] {
  return sessions.map((s) =>
    s.id === sessionId && s.status === 'collecting'
      ? { ...s, status: 'interrupted' as const, endedAt: now, lastError: reason }
      : s,
  );
}

/**
 * Mark every collecting session as interrupted (e.g. the connection dropped).
 * Already stopped/interrupted sessions are untouched. Returns the same array
 * reference when nothing was collecting, so callers can skip re-renders.
 */
export function interruptAllSessions(
  sessions: CollectionSession[],
  reason: string,
  now: Date = new Date(),
): CollectionSession[] {
  if (!sessions.some((s) => s.status === 'collecting')) return sessions;
  return sessions.map((s) =>
    s.status === 'collecting'
      ? { ...s, status: 'interrupted' as const, endedAt: now, lastError: reason }
      : s,
  );
}

/** Remove all messages from a session (user-triggered clear). Keeps the session itself. */
export function clearSessionMessages(
  sessions: CollectionSession[],
  sessionId: string,
): CollectionSession[] {
  return sessions.map((s) =>
    s.id === sessionId ? { ...s, messages: [], messageCount: 0 } : s,
  );
}

export interface SessionExport {
  session: {
    id: string;
    subject: string;
    queueGroup?: string;
    status: SessionStatus;
    messageCount: number;
    startedAt: string;
    lastMessageAt: string | null;
    endedAt: string | null;
    lastError: string | null;
  };
  exportedAt: string;
  messages: Array<{
    subject: string;
    data: string;
    headers?: Record<string, string>;
    timestamp: string;
    replyTo?: string;
  }>;
}

/**
 * Build the export payload for a session. Works for empty and interrupted
 * sessions alike — the status and error are exported as-is, and the count is
 * derived from the message detail so the two can never disagree.
 */
export function buildSessionExport(
  session: CollectionSession,
  exportedAt: Date = new Date(),
): SessionExport {
  return {
    session: {
      id: session.id,
      subject: session.subject,
      queueGroup: session.queueGroup,
      status: session.status,
      messageCount: session.messages.length,
      startedAt: session.startedAt.toISOString(),
      lastMessageAt: session.lastMessageAt ? session.lastMessageAt.toISOString() : null,
      endedAt: session.endedAt ? session.endedAt.toISOString() : null,
      lastError: session.lastError,
    },
    exportedAt: exportedAt.toISOString(),
    messages: session.messages.map((m) => ({
      subject: m.subject,
      data: m.data,
      headers: m.headers,
      timestamp: m.timestamp.toISOString(),
      replyTo: m.replyTo,
    })),
  };
}
