"use strict";

// Collection verdict for a target page.
//
// Pure classification logic, no Playwright, no network: turns what an attempt
// observed into one of five verdicts so a caller can decide whether to retry,
// change identity or stop.
//
//   ok              the expected, publicly available page
//   challenged      a challenge stood in the way and the page handler cleared it (closed -> open)
//   blocked         the site refused this visitor (failed handling, 403/503, block/verify page)
//   not-public      the target redirected to a sign-in wall; the data is not public
//   oxylabs-network an upstream network error (X-Error-Description on a response)
//
// The decision only uses generic HTTP signals (status code, response headers,
// final URL, body text) and the page handler's state machine. It never keys on
// vendor-specific markup, fingerprint headers or product names embedded in a
// page. The one header it looks at, X-Error-Description, is the generic
// "upstream network error on this response" signal the platform documents.

const OK = "ok";
const CHALLENGED = "challenged";
const BLOCKED = "blocked";
const NOT_PUBLIC = "not-public";
const OXYLABS_NETWORK = "oxylabs-network";
const VERDICTS = [OK, CHALLENGED, BLOCKED, NOT_PUBLIC, OXYLABS_NETWORK];

// Page-handler states (window message "oxylabs-page-status").
const IDENTIFYING = "identifying";
const CLOSED = "closed";
const OPEN = "open";
const FAILED = "failed";

// HTTP walls the target itself raises. 401/404 etc. are deliberately not here.
const BLOCK_STATUSES = new Set([403, 503]);

// Generic "you are refused" wording, independent of any bot-management vendor.
const BLOCK_PATTERN = /access denied|verify you are human/i;

// A sign-in wall in the final URL: /login, /signin, /sign-in (path boundary).
const LOGIN_PATH_PATTERN = /\/(login|signin|sign-in)(?:\/|$|\?)/i;

// True when a response carries the upstream network-error header. Header names
// are case-insensitive; Playwright lowercases them but other clients may not.
function hasErrorHeader(headers) {
  if (!headers) return false;
  const hit = Object.keys(headers).find((k) => k.toLowerCase() === "x-error-description");
  return hit !== undefined && headers[hit] !== "" && headers[hit] != null;
}

function isLoginUrl(finalUrl) {
  return Boolean(finalUrl) && LOGIN_PATH_PATTERN.test(finalUrl);
}

function isBlockContent(statusCode, bodyExcerpt) {
  if (BLOCK_STATUSES.has(statusCode)) return true;
  return Boolean(bodyExcerpt) && BLOCK_PATTERN.test(bodyExcerpt);
}

// Classify one observed page.
//
//   headers:        response headers of the main document (object/Map or null)
//   finalUrl:       URL after all redirects
//   statusCode:     HTTP status of the main document (number or null)
//   bodyExcerpt:    leading slice of the rendered body (string or null)
//   terminalState:  the page handler's waited-out state, or null when the
//                   handler was off (page_handler=false): { status, error?,
//                   challenged?, sawClosed? }
//
// Returns one of the VERDICTS. Precedence, first match wins:
//   1. X-Error-Description ............ oxylabs-network
//   2. final URL on a login path ...... not-public
//   3. terminal failed, or a 403/503 /
//      "access denied" / "verify you are human" page ... blocked
//   4. a closed -> open transition .... challenged
//   5. everything else ................ ok
function classifyPage(headers, finalUrl, statusCode, bodyExcerpt, terminalState) {
  // 1. Upstream network failure on this response. Checked first: a network
  //    error is not the site's answer, regardless of what else was observed.
  if (hasErrorHeader(headers)) return OXYLABS_NETWORK;

  // 2. A sign-in wall means the content is only for logged-in users and is
  //    out of scope for public-data collection. No retry can make it public.
  if (isLoginUrl(finalUrl)) return NOT_PUBLIC;

  const state = terminalState || {};
  const status = state.status;
  const sawChallenge = Boolean(state.challenged || state.sawClosed);

  // 3. A wall the site itself raised: the handler gave up (failed with an
  //    error), or the page is still a 403/503 / access-denied / human-check
  //    page even though the handler reported "open".
  if (status === FAILED || isBlockContent(statusCode, bodyExcerpt)) return BLOCKED;

  // 4. The handler saw a challenge (closed) and the page became usable
  //    afterwards (open). Keep page_handler=true for this target.
  if (status === OPEN) return sawChallenge ? CHALLENGED : OK;

  // 5. The handler was on (a state object was supplied) but never reported a
  //    usable terminal state - e.g. the 90 s wait timed out, or only a
  //    transient identifying/closed was captured. Usability was never
  //    confirmed: treat as blocked so the caller rotates identity instead of
  //    accepting an unverified page. A plain page_handler=false attempt passes
  //    no state object at all and is not affected (it falls through to ok).
  if (terminalState) return BLOCKED;

  // 6. Plain attempt (no handler) with no wall: a usable public page.
  return OK;
}

module.exports = {
  OK,
  CHALLENGED,
  BLOCKED,
  NOT_PUBLIC,
  OXYLABS_NETWORK,
  VERDICTS,
  IDENTIFYING,
  CLOSED,
  OPEN,
  FAILED,
  hasErrorHeader,
  isLoginUrl,
  isBlockContent,
  classifyPage,
};
