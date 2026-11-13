Sanitized session envelope fixture
=================================

jabama-sessions-detail.html models the exact public HTML envelope inspected in
data/website-inspection/jabama-event-detail.html during the 2026-10-20 hardening
task. The ignored historical HTML was read locally; no request was issued.

Verified structure:
- script calls window.__reactRouterContext.streamController.enqueue with one
  JSON string argument containing an indexed JSON reference table;
- loaderData["routes/events.$id"] owns event, sessions and firstSession;
- event.id agrees with the /events/{id} detail path;
- sessions contains id, eventId, startIso, durationHours, capacityLimit,
  bookedCount, remainingSeats, enabled, inventoryMode, layoutId, timeslots,
  pricePerPerson, unitPrice, hostDiscountPct and platformDiscountPct;
- null is represented by reference -5;
- firstSession repeats the same booking session and is not a new occurrence.

The fixture has synthetic title/description, event/session/layout IDs, host and
URL context. No downloaded HTML, real reviews, account context, analytics
configuration, credentials or session artifacts are committed. The one fake
review sentinel tests that unrelated event fields never enter retained facts.

The source sample had null session prices. Additional test-only mutations cover
multiple sessions, numeric prices, discounts, invalid fields and schema drift;
they are regression inputs, not a claim of broader live source verification.

Only the observed empty-timeslots shape is supported. Nonempty timeslots,
different routes, new session properties and new stream envelopes remain
explicitly unresolved. Public page prices are not inherited by sessions, and
their currency is not inferred from unrelated page structured data.

Cloud hardening (2026-10-29): unsupported sessions additionally report one of
embedded_session_drift_new_properties / _timeslots / _field, and the raw item
keeps only the names of unexpected session properties in
source_session_drift_keys. The two audited pottery pages still need a fresh
public snapshot before any new session shape is supported.

2026-10-29 owner crawl: `soldOut` on all ten Jabama pages and non-empty
`timeslots` on 48751310, 01519540 and 86400491 (Experiences). Names only were
retained; types are unverified. Tests use synthetic values; see
docs/DATA_CONTRACTS.md "Jabama session evidence boundary".

2026-10-29 v3 structural report: soldOut is a boolean; timeslots are objects with
twelve keys (id, sessionId, startAt, endAt, enabled, capacityLimit, bookedCount,
remainingSeats, pricePerPerson, unitPrice, hostDiscountPct, platformDiscountPct).
tests/test_jabama_timeslots.py builds synthetic pages in that shape; no saved HTML
or real identifier is committed. Value relationships await the owner's
`diagnose jabama-timeslots` report.
