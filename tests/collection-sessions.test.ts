// Unit tests for the Messages page collection sessions.
// Run with: pnpm test   (node --test — no extra dependencies required)
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  createSession,
  startSession,
  findActiveSession,
  findLatestSession,
  recordMessage,
  stopSession,
  interruptSession,
  interruptAllSessions,
  clearSessionMessages,
  buildSessionExport,
  MAX_SESSION_MESSAGES,
} from '../src/services/collection-sessions.ts';

function makeMessage(subject, text, timestamp = new Date('2026-11-13T10:00:00Z')) {
  return {
    id: `msg_${text}`,
    subject,
    data: text,
    timestamp,
  };
}

// ---------------------------------------------------------------------------
// Normal path: create -> collect -> stop
// ---------------------------------------------------------------------------

test('starting a session records subject, start time and collecting status', () => {
  const started = new Date('2026-11-13T09:00:00Z');
  const { sessions, session, reused } = startSession([], 'orders.created', undefined, started);

  assert.equal(reused, false);
  assert.equal(sessions.length, 1);
  assert.equal(session.subject, 'orders.created');
  assert.equal(session.status, 'collecting');
  assert.equal(session.messageCount, 0);
  assert.deepEqual(session.startedAt, started);
  assert.equal(session.lastMessageAt, null);
  assert.equal(session.lastError, null);
});

test('recording messages updates count and last-message time', () => {
  const { sessions, session } = startSession([], 'orders.created');
  const t1 = new Date('2026-11-13T10:00:00Z');
  const t2 = new Date('2026-11-13T10:00:05Z');

  let next = recordMessage(sessions, session.id, makeMessage('orders.created', 'one', t1));
  next = recordMessage(next, session.id, makeMessage('orders.created', 'two', t2));

  const updated = next.find((s) => s.id === session.id);
  assert.equal(updated.messageCount, 2);
  assert.equal(updated.messages.length, 2);
  assert.deepEqual(updated.lastMessageAt, t2);
  // Newest first
  assert.equal(updated.messages[0].data, 'two');
});

test('stopping a session keeps it in the list, freezes the count and ignores late messages', () => {
  const { sessions, session } = startSession([], 'orders.created');
  let next = recordMessage(sessions, session.id, makeMessage('orders.created', 'one'));

  const stoppedAt = new Date('2026-11-13T11:00:00Z');
  next = stopSession(next, session.id, stoppedAt);

  const stopped = next.find((s) => s.id === session.id);
  assert.equal(next.length, 1, 'session must remain in the list after stop');
  assert.equal(stopped.status, 'stopped');
  assert.equal(stopped.messageCount, 1);
  assert.deepEqual(stopped.endedAt, stoppedAt);

  // Late-arriving messages must not touch a stopped session
  const after = recordMessage(next, session.id, makeMessage('orders.created', 'late'));
  const stillStopped = after.find((s) => s.id === session.id);
  assert.equal(stillStopped.messageCount, 1);
  assert.equal(stillStopped.messages.length, 1);
});

// ---------------------------------------------------------------------------
// Duplicate subscribe: one active session per subject
// ---------------------------------------------------------------------------

test('subscribing twice to the same subject reuses the active session', () => {
  const first = startSession([], 'orders.created');
  const second = startSession(first.sessions, 'orders.created');

  assert.equal(second.reused, true);
  assert.equal(second.session.id, first.session.id);
  assert.equal(second.sessions.length, 1, 'no parallel session may be created');
  assert.equal(second.sessions, first.sessions, 'state must be untouched on reuse');
});

test('different subjects get independent sessions', () => {
  const a = startSession([], 'orders.created');
  const b = startSession(a.sessions, 'orders.cancelled');

  assert.equal(b.reused, false);
  assert.equal(b.sessions.length, 2);
  assert.ok(findActiveSession(b.sessions, 'orders.created'));
  assert.ok(findActiveSession(b.sessions, 'orders.cancelled'));
});

test('re-subscribing after stop creates a new session (old one stays stopped)', () => {
  const first = startSession([], 'orders.created');
  const stopped = stopSession(first.sessions, first.session.id);
  const second = startSession(stopped, 'orders.created');

  assert.equal(second.reused, false);
  assert.notEqual(second.session.id, first.session.id);
  assert.equal(second.sessions.length, 2);
  assert.equal(second.sessions.find((s) => s.id === first.session.id).status, 'stopped');
  // The latest session for the subject is the new collecting one
  assert.equal(findLatestSession(second.sessions, 'orders.created').id, second.session.id);
});

// ---------------------------------------------------------------------------
// Disconnect: collecting sessions become interrupted with a reason
// ---------------------------------------------------------------------------

test('connection loss interrupts all collecting sessions with a reason', () => {
  let sessions = startSession([], 'orders.created').sessions;
  sessions = startSession(sessions, 'orders.cancelled').sessions;
  const stoppedOne = startSession(sessions, 'orders.paid');
  sessions = stopSession(stoppedOne.sessions, stoppedOne.session.id);

  const lostAt = new Date('2026-11-13T12:00:00Z');
  const reason = 'Connection to NATS server lost';
  const next = interruptAllSessions(sessions, reason, lostAt);

  const bySubject = (subject) => next.find((s) => s.subject === subject);
  assert.equal(bySubject('orders.created').status, 'interrupted');
  assert.equal(bySubject('orders.cancelled').status, 'interrupted');
  assert.equal(bySubject('orders.created').lastError, reason);
  assert.equal(bySubject('orders.cancelled').lastError, reason);
  assert.deepEqual(bySubject('orders.created').endedAt, lostAt);

  // A session that was already stopped must not be rewritten as interrupted
  assert.equal(bySubject('orders.paid').status, 'stopped');
  assert.equal(bySubject('orders.paid').lastError, null);

  // Nothing may remain in the collecting state
  assert.equal(next.some((s) => s.status === 'collecting'), false);
});

test('interruptAllSessions is a no-op (same reference) when nothing is collecting', () => {
  const started = startSession([], 'orders.created');
  const sessions = stopSession(started.sessions, started.session.id);
  assert.equal(interruptAllSessions(sessions, 'lost'), sessions);
  assert.equal(interruptAllSessions([], 'lost').length, 0);
});

test('interrupted sessions do not resume or accept messages', () => {
  const { sessions, session } = startSession([], 'orders.created');
  const interrupted = interruptSession(sessions, session.id, 'boom');

  // Messages arriving after the interrupt are dropped
  const after = recordMessage(interrupted, session.id, makeMessage('orders.created', 'late'));
  assert.equal(after.find((s) => s.id === session.id).messageCount, 0);

  // findActiveSession must not treat an interrupted session as resumable —
  // the user has to subscribe again, which creates a fresh session.
  assert.equal(findActiveSession(after, 'orders.created'), undefined);
  const restarted = startSession(after, 'orders.created');
  assert.equal(restarted.reused, false);
  assert.equal(restarted.session.status, 'collecting');
});

// ---------------------------------------------------------------------------
// Export: metadata + detail, count consistent, empty/interrupted allowed
// ---------------------------------------------------------------------------

test('export carries session metadata and message detail with a consistent count', () => {
  const started = new Date('2026-11-13T09:00:00Z');
  const { sessions, session } = startSession([], 'orders.created', undefined, started);
  let next = recordMessage(sessions, session.id, makeMessage('orders.created', 'one'));
  next = recordMessage(next, session.id, makeMessage('orders.created', 'two'));
  next = stopSession(next, session.id);

  const exported = buildSessionExport(next.find((s) => s.id === session.id));

  assert.equal(exported.session.subject, 'orders.created');
  assert.equal(exported.session.status, 'stopped');
  assert.equal(exported.session.startedAt, started.toISOString());
  assert.ok(exported.session.endedAt);
  assert.equal(exported.session.messageCount, exported.messages.length);
  assert.equal(exported.messages.length, 2);
  assert.deepEqual(
    exported.messages.map((m) => m.data).sort(),
    ['one', 'two'],
  );
});

test('exporting an empty session is allowed and reports zero messages', () => {
  const { sessions, session } = startSession([], 'quiet.subject');
  const exported = buildSessionExport(sessions.find((s) => s.id === session.id));

  assert.equal(exported.session.status, 'collecting');
  assert.equal(exported.session.messageCount, 0);
  assert.deepEqual(exported.messages, []);
  assert.equal(exported.session.lastMessageAt, null);
  assert.equal(exported.session.lastError, null);
});

test('exporting an interrupted session reflects the status and the failure reason', () => {
  const { sessions, session } = startSession([], 'orders.created');
  let next = recordMessage(sessions, session.id, makeMessage('orders.created', 'one'));
  next = interruptSession(next, session.id, 'Connection to NATS server lost');

  const exported = buildSessionExport(next.find((s) => s.id === session.id));

  assert.equal(exported.session.status, 'interrupted');
  assert.equal(exported.session.lastError, 'Connection to NATS server lost');
  assert.equal(exported.session.messageCount, 1);
  assert.equal(exported.messages.length, 1);
  assert.equal(exported.session.messageCount, exported.messages.length);
});

// ---------------------------------------------------------------------------
// Housekeeping invariants
// ---------------------------------------------------------------------------

test('message count can never diverge from retained detail (cap included)', () => {
  const { sessions, session } = startSession([], 'busy.subject');
  let next = sessions;
  for (let i = 0; i < MAX_SESSION_MESSAGES + 50; i += 1) {
    next = recordMessage(next, session.id, makeMessage('busy.subject', `m${i}`));
  }
  const updated = next.find((s) => s.id === session.id);
  assert.equal(updated.messages.length, MAX_SESSION_MESSAGES);
  assert.equal(updated.messageCount, updated.messages.length);
  // Newest retained
  assert.equal(updated.messages[0].data, `m${MAX_SESSION_MESSAGES + 49}`);
});

test('clearing messages resets the count but keeps the session', () => {
  const { sessions, session } = startSession([], 'orders.created');
  let next = recordMessage(sessions, session.id, makeMessage('orders.created', 'one'));
  next = clearSessionMessages(next, session.id);

  const cleared = next.find((s) => s.id === session.id);
  assert.equal(next.length, 1);
  assert.equal(cleared.status, 'collecting');
  assert.equal(cleared.messageCount, 0);
  assert.equal(cleared.messages.length, 0);
});

test('sessions are independent from custom-topic bookmarks (in-memory only, no persistence)', () => {
  // The session module must not touch localStorage: sessions vanish on reload
  // and bookmark deletion cannot affect them.
  const { sessions } = startSession([], 'bookmarked.subject');
  assert.equal(typeof globalThis.localStorage, 'undefined',
    'test environment must not provide localStorage to the session module');
  assert.equal(sessions.length, 1);
  assert.equal(createSession('x').status, 'collecting');
});
