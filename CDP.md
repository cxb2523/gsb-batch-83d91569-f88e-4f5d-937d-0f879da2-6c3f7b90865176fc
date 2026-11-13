# Custom CDP methods

This document is the reference for the commands, events and types this browser adds to the Chrome DevTools Protocol (CDP). Everything here is additional to stock Chromium's protocol; the stock domains are documented at https://chromedevtools.github.io/devtools-protocol/ and are not repeated.

The additions live in three domains:

- **Browser**: reading a URL without a tab (`agentFetch`), browser-wide network recording (`startRecording` and friends), and, in the release binary, the browser's settled fingerprint (`getFingerprint`).
- **Input**: pointer, keyboard and form-control actions carried out whole, inside the browser, with human timing (`moveTo`, `scrollBy`, `performDrag`, `dispatchKeystrokes`, `selectOptions`, `chooseFiles`, ...).
- **Page**: one-call page perception (`captureAgentSnapshot`), element handles that work across frames (`resolveAgentNode`, `agentHitCheck`, `agentNodesAlive`), live-region and layer reports (`agentAnnouncements`, `agentReport`), waiting for a page to settle (`agentSettle`), history steps that answer when landed (`agentNavigateToHistoryEntry`), and a shared-memory frame stream (`startFrameStream`).

## How to call them

- **Discovery.** The browser lists every custom command, event and type in its protocol JSON at `http://127.0.0.1:<port>/json/protocol`, next to the stock ones. Any CDP client that can send a raw method name can call them: `CDPSession.send(...)` in Puppeteer or Playwright, a raw WebSocket, a CDP wrapper library, or the DevTools front end's protocol monitor.
- **Release binary and source build.** Everything here is in the binary on the Releases page. A browser built from the published patches has every item except `Browser.getFingerprint`, which reports the fingerprint identity layer whose source is not published; it is marked **release binary only** below.
- **Experimental.** Every item here is marked `experimental` in the protocol. Names and fields may change between releases; the protocol JSON of the build you run is the authority.
- **Which target.** The `Browser` domain commands (`Browser.agentFetch`, `Browser.agentFetchCancel`, `Browser.getFingerprint`, `Browser.startRecording`, `Browser.stopRecording`, `Browser.recordingMask`, `Browser.recordingStatus`) exist **only on the browser target**: the WebSocket at the `webSocketDebuggerUrl` that `/json/version` reports. Sent on a page session they answer with a "method not found" error. The `Input` and `Page` commands run on a **page session**: a session attached to a page target (from `/json/list`, or `Target.attachToTarget` with `flatten: true`). Elements in out-of-process iframes are handled for you: the commands take the element's backend node id together with the id of the frame whose renderer holds it, and route the call themselves (see "Naming an element" below).
- **Long-running commands answer once, when done.** Most Input and Page commands here carry out a whole action (a move, a click, a scroll, a wait) and reply when it has ended, not when it was dispatched. Each carries a `timeoutMs` with a default and a cap, listed per command. A reply's `outcome` string says how the action ended; the possible values are listed per command.
- **Events.** `Input.actionOutcome` is sent to the session whose command armed it. `Input.permissionPromptDismissed` is sent on the page's session whenever the browser dismisses one of its permission prompts. `Browser.recordingEnded` is sent on the browser session.
- **Platform.** `Page.startFrameStream`, `Page.updateFrameStream` and `Page.stopFrameStream` are Windows only.
- **Switches.** Some methods depend on command-line switches the browser was started with. Each dependency is noted on the method, and the table at the end of this document collects them.

### Conventions shared by the Input and Page commands

- **Coordinates.** Unless a field says otherwise, points and boxes are in CSS pixels of the main frame's viewport (viewport-relative, the same space `Input.dispatchMouseEvent` takes). Elements in iframes, cross-origin ones included, are composed into that space.
- **Naming an element.** Two handles exist.
  - `agentNodeId` is a browser-minted integer that `Page.captureAgentSnapshot` gives every listed element. It is stable for the element's life in its document, unique across every frame of the page and never reused by another element of any document. `Page.resolveAgentNode`, `Page.agentHitCheck` and `Page.agentNodesAlive` take it.
  - `backendNodeId` with `frameId` names the element the way its own renderer knows it: the backend node id in the renderer of the frame's *local root*, and that local root's frame id. `Page.resolveAgentNode` returns both (`backendNodeId`, `localRootFrameId`); for an element in the page itself the frame id is the main frame's. The Input commands take this form, as does `Page.agentHitCheck` when no `agentNodeId` is given.
- **"The hand."** Several Input commands move the pointer "as a hand does": the browser plans each movement from a human-movement persona it derives from a seed (`--movement-persona-seed`; without it, in the release binary, the fingerprint identity's `--fingerprint-seed`; otherwise a random seed for each browser run), and the hand picks where on a target it lands, how long it rests before pressing and how long a button stays down. `Input.probeMovementPersona` exposes the persona's fields. No planned path leaves the view.
- **Where the pointer is.** The browser keeps the pointer where the last mouse path left it. Each pointer command takes `pointerX`/`pointerY` for the case where no mouse path has put it anywhere yet.
- **`hit`, `hitKind`, `reason`.** When an action is refused because something else would take the press, the reply names what the press would reach in `hit`: an element as `tag#id` or `tag.class` (then its text when short), with where it is when it belongs to another document ("the page's div#ov" over an element in a frame, "div#panel in another frame"). A cover that is an open layer the element is not in (a listbox, a menu, a dialog) is named by that layer, e.g. `listbox "City"`, as is that layer's veil, the backdrop beside its box, e.g. `dialog "Choose a plan"`; `hitKind` then gives the layer's kind (`listbox`, `menu`, `dialog`, `alert`, `popover`, `picker`, or `panel` for a veil's layer with no role). `reason` carries the hit check's verdict in `Page.agentHitCheck`'s words (`covered`, `nothing`, `otherFrame`, `noPointer`, `inert`, `disabled`, `hidden`). These fields mean the same across the commands below; the verdicts are defined once under `Page.agentHitCheck`.
- **`actionOutcome`.** Input actions that press, type, pick or drop return a `Page.ActionOutcome`: what the action led to (navigations of the tab, new tabs, popups refused, a frame asking to print). With `followNavigation` (default `true` on most commands) the reply waits, for at most about 3 s, for a cross-document navigation the action started to end; without it the reply still says what started. Whatever happens later, until the next action arms, comes as `Input.actionOutcome` events carrying the same `actionId`.
- **Arms, reports and settling.** Every Input action "arms" a watch on the page from its dispatch; the action's `actionId` names that arm. `Page.agentSettle` waits for the page to go quiet after an arm, and `Page.agentReport` reads what the action led to on the page (live regions, layers). For an action that is not input (a navigation, a script, a wait), `Page.agentSettleArm` arms one by hand.

### How each entry is laid out

Each command has a heading, a short description of what it does and when to use it, a **Parameters** list (name, type, required or optional, meaning), a **Returns** list in the same form, a JSON example request, and, where the protocol makes the shape clear, an example response (the `result` object). Events and shared types follow the commands of their domain. Enum values, defaults and caps are given exactly as the protocol declares them.

## Contents

- [Browser domain](#browser-domain): `agentFetch`, `agentFetchCancel`, `getFingerprint` (release binary only), `startRecording`, `stopRecording`, `recordingMask`, `recordingStatus`; event `recordingEnded`; types `AgentFetchRedirect`, `AgentFetchOutlineItem`, `AgentFetchLink`.
- [Input domain](#input-domain): `dispatchMousePath`, `moveTo`, `revealElement`, `scrollBy`, `performDrag`, `setInterceptDrags` (new `carry` parameter), `dispatchKeystrokes`, `dispatchKeyChord`, `dispatchPaste`, `selectOptions`, `fillDateTime`, `pickColor`, `chooseFiles`, `probeMovementPersona`; events `actionOutcome`, `permissionPromptDismissed`; types `MousePathPoint`, `MousePathEnd`, `MouseWheelNotch`, `MoveEnd`, `PlanRect`, `WheelScroller`, `DragScroll`, `SelectOption`, `NoTypos`, `FieldReading`.
- [Page domain](#page-domain): `captureAgentSnapshot`, `agentFinishCapture`, `resolveAgentNode`, `agentHitCheck`, `agentNodesAlive`, `agentAnnouncements`, `agentSettleArm`, `agentSettle`, `agentReport`, `agentNavigateToHistoryEntry`, `startFrameStream`, `updateFrameStream`, `stopFrameStream`; types for snapshots, deltas, layers, live regions, redaction, node life, reports, action outcomes and settling.
- [Switches the custom methods depend on](#switches-the-custom-methods-depend-on).

---

## Browser domain

All commands in this section are **browser target only**. `Browser.agentFetch` and `Browser.stopRecording` are asynchronous: their reply comes when the work has finished.

### `Browser.agentFetch`: read a URL without a tab

Reads a URL the way a tab would, in a page that is never shown and never appears as a target. An HTML response is rendered, allowed to settle and extracted as Markdown in the renderer; any other response is taken as it is, before anything commits. Giving a method other than GET, a header the caller may set, or a body makes the call an *API call*: a real `fetch()` from a document of the URL's origin. The page's own strings in the reply (`title`, `lang`, `outline`, `links`, `facts`) are cut on a character boundary: URLs at 8 KiB, any other at 64 KiB. A session runs six calls at once and up to 64 more wait their turn; a call past those is refused with "too many agentFetch calls are waiting". Use it to read a page or call an endpoint without creating, showing or managing a tab.

Parameters:
- `url`: string, required. The URL to read.
- `mode`: string, optional. `auto` (default): render HTML, take anything else as it is. `raw`: take every response as it is.
- `method`: string, optional. The HTTP method. Anything other than GET makes the call an API call.
- `headers`: object, optional. Request headers for an API call (header name to value). The browser's own headers (User-Agent, Sec-*, Accept-Language, Cookie, Origin, Referer, ...) cannot be set: they are dropped, and do not make the call an API call.
- `body`: string, optional. The API call's request body; makes the call an API call. One larger than 16 MiB is refused ("body is larger than 16 MiB").
- `referrer`: string, optional. The API call's document URL; by default the URL's origin.
- `timeoutMs`: integer, optional. Time allowed for the whole call, counted from when it starts running (not while it waits its turn); default 30000, from 1000 to 60000.
- `settleMs`: integer, optional. How long the page may take to settle: one budget for the documents that replace one another, each given at least 3000 of it, and the whole budget again after a cleared challenge; default 10000, from 500 to 30000.
- `saveTo`: string, optional. Absolute path for a body written to a file: a binary one, or text past 8 MiB. Otherwise one is chosen under the profile.
- `links`: boolean, optional. Return every link on the page (at most 5000), not only the ones the Markdown carries.
- `fetchId`: string, optional. An id for `Browser.agentFetchCancel`.

Returns:
- `outcome`: string. `ok`, `challenge`, `blocked`, `error`, `timeout` or `cancelled`.
- `error`: string, optional. The error, when there is one.
- `status`: integer, optional. The HTTP status.
- `finalUrl`: string, optional. The URL after redirects.
- `redirects`: array of `AgentFetchRedirect`, optional. One entry per redirect hop.
- `contentType`: string, optional.
- `charset`: string, optional.
- `headers`: object, optional. The final response headers, lowercased; `set-cookie` carries the cookie names only.
- `kind`: string. What the body is: `html`, `text`, `json`, `xml`, `binary` or `none`.
- `title`: string, optional. The page title.
- `lang`: string, optional. The page language.
- `readerable`: boolean, optional. Whether the page was judged readable article content.
- `extractor`: string, optional. Which extractor produced `markdown`: `readability`, `structural`, or `none` when no Markdown came out.
- `markdown`: string, optional. The rendered HTML page as Markdown.
- `outline`: array of `AgentFetchOutlineItem`, optional. The headings in `markdown`.
- `facts`: object, optional. `meta`, `og`, `twitter`, `jsonld[]` and Readability's `byline`/`siteName`/...
- `links`: array of `AgentFetchLink`, optional. The links found.
- `signals`: object, optional. Detection inputs for the caller's own classifier.
- `challenge`: object, optional. A challenge or block the fetch met: `vendor`, `kind` (`auto`, `interactive` or `ban`), `rule`, `evidence[]`; for a challenge also `cleared` and `waitedMs`; for a block that is a rate limit also `rateLimited` and `retryAfter`.
- `text`: string, optional. A body taken as it is (any body that is not rendered, and every body in `raw` mode), decoded to UTF-8, up to 8 MiB.
- `savedTo`: string, optional. Where a binary body was written.
- `bytes`: number, optional. The body size.
- `truncated`: boolean, optional. Whether the body was cut.
- `timings`: object. Milliseconds from the call: `navigate`, `firstCommit` (a page that replaced itself), `commit`, `dcl`, `settle`, `extract`, `fetch` (an API call), `total`; and `restarts`.

Example: read a page as Markdown.

```json
{
  "method": "Browser.agentFetch",
  "params": {
    "url": "https://example.com/article",
    "links": true,
    "timeoutMs": 20000
  }
}
```

Example response (abridged):

```json
{
  "outcome": "ok",
  "status": 200,
  "finalUrl": "https://example.com/article",
  "redirects": [],
  "contentType": "text/html",
  "charset": "utf-8",
  "kind": "html",
  "title": "An article",
  "lang": "en",
  "readerable": true,
  "extractor": "readability",
  "markdown": "# An article\n\nFirst paragraph...",
  "outline": [{ "level": 1, "text": "An article", "offset": 0 }],
  "links": [
    { "url": "https://example.com/", "text": "Home", "region": "nav", "inMarkdown": false }
  ],
  "timings": { "navigate": 12, "commit": 210, "dcl": 380, "settle": 900, "extract": 920, "total": 925, "restarts": 0 }
}
```

Example: an API call (a POST with a header and a body).

```json
{
  "method": "Browser.agentFetch",
  "params": {
    "url": "https://api.example.com/v1/items",
    "method": "POST",
    "headers": { "Content-Type": "application/json" },
    "body": "{\"name\":\"x\"}",
    "referrer": "https://api.example.com/app",
    "fetchId": "items-1"
  }
}
```

### `Browser.agentFetchCancel`: cancel a fetch

Ends a running or queued `Browser.agentFetch` with outcome `cancelled`. The fetch is named by the `fetchId` the caller gave it.

Parameters:
- `fetchId`: string, required. The `fetchId` passed to `Browser.agentFetch`.

Returns:
- `cancelled`: boolean. Whether a fetch of that id was found and cancelled.

```json
{
  "method": "Browser.agentFetchCancel",
  "params": { "fetchId": "items-1" }
}
```

```json
{ "cancelled": true }
```

### `Browser.getFingerprint`: what this browser shows pages

**Release binary only.** Returns everything this browser settled on for pages to see: the brand, user agent and client hints, the GPU and WebGPU, the hardware, the screen and refresh rate, the device type, battery, media devices and media features, history length, connection, WebRTC address, time zone and place, languages, font bundles, voices, audio, text rendering, the canvas and WebGL noise, the seeds, and every fingerprint switch as the browser holds it. It is read in the browser process alone, so it answers while every tab is frozen, and no page sees the call. Use it to record or verify the identity a browser instance presents without running script in any page.

Parameters: none.

Returns:
- `fingerprint`: object. `chromiumVersion` (string) and `headless` (boolean), then one object per part, each as the browser settled it; a value that is not spoofed is the real one where the browser can know it:
  - `seed`: `requested`, `master` (when requested), `persona`.
  - `brand`: `spoofed`, `name`, `version`, `fullVersion`, `userAgent`, `clientHints` (`brands`, `fullVersionList`, `fullVersion`, `platform`, `platformVersion`, `architecture`, `bitness`, `model`, `mobile`, `wow64`, `formFactors`).
  - `gpu`: `vendor`, `renderer`, `maxVertexUniformVectors`, `webgpuVendor`, `webgpuArchitecture`.
  - `hardware`: `concurrency`, `concurrencySpoofed`, `concurrencySource`, `realConcurrency`, `deviceMemory`, `deviceMemorySpoofed`, `realMemoryMiB`.
  - `screen`: `spoofed`, `source`, `width`, `height`, `availWidth`, `availHeight`, `availTop`, `availLeft`, `colorDepth`, `devicePixelRatio`, `devicePixelRatioSpoofed`, `screenX`, `screenY`, `display` (`width`, `height`, `workAreaWidth`, `workAreaHeight`, `scaleFactor`, `colorDepth`, `frequency`, `internal`), `windowSize`, `windowPosition`, `screenInfo`, `refreshRate`, `refreshRateSpoofed`.
  - `device`: `type`, `battery` (`spoofed`, `source`, `charging`, `level`, `chargingTime`, `dischargingTime`), `mediaDevices` (`spoofed`, `source`, `microphones`, `webcams`, `speakers`, `listsMicrophone`, `listsWebcam`, `listsSpeaker`), `mediaFeatures` (`spoofed`, `prefersColorScheme`, `prefersReducedMotion`, `prefersContrast`, `forcedColors`, `colorGamut`), `historyLength`.
  - `network`: `connection` (`spoofed`, `effectiveType`, `downlinkMbps`, `rttMs`, `saveData`, `type`), `webrtc` (`spoofed`, `ip4`, `ip6`).
  - `place`: `timezone`, `timezoneSpoofed`, `geolocation` (`latitude`, `longitude`, `accuracy`).
  - `languages`: `navigatorLanguages`, `acceptLanguage`, `acceptLanguageSource`, `textRendering` (`gamma`, `contrast`, `spoofed`).
  - `fonts`: `bundleActive`, `seedDerived`, `bundles`, `fileCount`, `languages`.
  - `voices`: the synthesis voices as a page lists them.
  - `audio`: `spoofed`, `sampleRate`, `baseLatency`, `outputLatency`, `maxChannelCount`.
  - `noise`: `canvasCurve`, `canvasBlur`, `canvasGradient`, `webglShader`, `webglShaderK`.
  - `switches`: every fingerprint switch as the process holds it, by name.

```json
{
  "method": "Browser.getFingerprint"
}
```

### `Browser.startRecording`: record every load and websocket

Records every load and websocket this browser carries, in every process, into a directory: `recording.har` with the headers and the bodies, `requests.txt` as a grep index, `bodies/` for anything large, `sockets.ndjson` for websocket events, `pages.json`, at the `full` level `scripts/` with `scripts.json`, and `summary.md` to read first. The browser reports from points inside itself, so nothing about how a page loads changes and no page can see the recording. One recording at a time; it also ends itself at the time limit or the size cap (see `Browser.recordingEnded`).

Parameters:
- `level`: string, required. `network`: every request and response, with headers, cookies, timings and bodies. `full`: the same, plus every script every renderer compiled while recording, `eval` and `new Function` code included, under `scripts/` (one file per distinct text, secrets masked) with `scripts.json` saying which document in which frame compiled which. A script compiled before the recording began is not replayed; the page's own worlds are recorded and isolated worlds are not. A classic script compiled with no name (what DevTools or a tool evaluates in the page, and a page's own `setTimeout` string or `javascript:` URL) is kept under kind `nameless`, apart from the page's named code.
- `path`: string, optional. An absolute directory, which the browser creates. Without one, a fresh directory under the profile.
- `minutes`: integer, optional. The recording ends itself after this many minutes; default 15, at most 120.
- `mask`: object, optional. Values to hide from the files, as label to value. Matched exactly, in plain, percent-encoded, JSON-escaped (as `JSON.stringify` writes it inside a string) and base64 form; a value under six characters is named in the summary instead of masked.
- `maxTextBodyBytes`: integer, optional. Per-entry limit on a text body; default 4194304.
- `maxBinaryBodyBytes`: integer, optional. Per-entry limit on a binary body; default 524288.
- `maxFrameBytes`: integer, optional. Per-entry limit on a websocket frame; default 65536.
- `maxTotalBytes`: integer, optional. The body and frame bytes a recording takes in before it ends itself at `sizeCap` (headers and the files' own overhead are not counted); default 1073741824.

Returns:
- `recordingId`: string. The id to pass to `stopRecording` and `recordingMask`.
- `path`: string. The directory being written.
- `endsAt`: number. When the time limit will end it, in ms since the epoch; 0 without one.

```json
{
  "method": "Browser.startRecording",
  "params": {
    "level": "full",
    "path": "C:\\captures\\session-42",
    "minutes": 30,
    "mask": { "session token": "eyJhbGciOi..." }
  }
}
```

```json
{
  "recordingId": "r-1",
  "path": "C:\\captures\\session-42",
  "endsAt": 1761650000000
}
```

### `Browser.stopRecording`: end the recording

Ends the recording and answers once its files are closed. A recording already ending on its own (the time limit, the size cap) is waited for the same way; a second stop while one waits is refused ("that recording is already stopping").

Parameters:
- `recordingId`: string, required. From `startRecording`.

Returns:
- `path`: string. The recording's directory.
- `entries`: number. Entries recorded.
- `scripts`: number. Script reports taken in, at the `full` level; 0 otherwise.
- `bytes`: number. Bytes taken in.
- `summary`: string. One line: the entries, the scripts at the full level, the bytes and what ended it. `summary.md` in the directory carries the whole account.

```json
{
  "method": "Browser.stopRecording",
  "params": { "recordingId": "r-1" }
}
```

### `Browser.recordingMask`: mask more values

Adds values for the running recording to hide from here on, as label to value. Use it when a secret becomes known after the recording started (a token issued mid-session). Matching follows `startRecording`'s `mask` rules.

Parameters:
- `recordingId`: string, required.
- `values`: object, required. Label to value.

Returns:
- `applied`: boolean. Whether the mask was applied to the recording.

```json
{
  "method": "Browser.recordingMask",
  "params": {
    "recordingId": "r-1",
    "values": { "api key": "sk-live-..." }
  }
}
```

### `Browser.recordingStatus`: the recording under way

Describes the recording in progress. Without one, `recording` is `false` and the other fields are empty or zero.

Parameters: none.

Returns:
- `recording`: boolean.
- `recordingId`: string.
- `level`: string. `network` or `full`.
- `path`: string.
- `entries`: number.
- `scripts`: number.
- `bytes`: number.
- `endsAt`: number. In ms since the epoch; 0 without a time limit.

```json
{
  "method": "Browser.recordingStatus"
}
```

```json
{
  "recording": true,
  "recordingId": "r-1",
  "level": "full",
  "path": "C:\\captures\\session-42",
  "entries": 412,
  "scripts": 37,
  "bytes": 18231044,
  "endsAt": 1761650000000
}
```

### Event `Browser.recordingEnded`

Sent when a recording ended. `reason` is `stopped`, `timeLimit`, `sizeCap`, `networkServiceGone`, `shutdown` or `error`; every one but `stopped` is news to whoever started it, since the recording ended itself.

Parameters:
- `recordingId`: string.
- `reason`: string. `stopped`, `timeLimit`, `sizeCap`, `networkServiceGone`, `shutdown` or `error`.
- `path`: string. The recording's directory.
- `summary`: string. The one-line summary, as `stopRecording` returns it.

```json
{
  "method": "Browser.recordingEnded",
  "params": {
    "recordingId": "r-1",
    "reason": "timeLimit",
    "path": "C:\\captures\\session-42",
    "summary": "1203 entries, 61 scripts, 54 MB; ended at the time limit"
  }
}
```

### Browser domain types

#### `Browser.AgentFetchRedirect`

One redirect hop of `Browser.agentFetch`.

- `url`: string. The URL redirected to.
- `status`: integer. The redirect's HTTP status.

#### `Browser.AgentFetchOutlineItem`

A heading in `Browser.agentFetch`'s Markdown.

- `level`: integer. 1 to 6.
- `text`: string. The heading text.
- `offset`: integer. UTF-16 code-unit offset of the heading line in `markdown`.

#### `Browser.AgentFetchLink`

A link `Browser.agentFetch` found.

- `url`: string.
- `text`: string. The link text.
- `region`: string. Where on the page: `main`, `nav`, `header`, `footer`, `aside` or `none`.
- `inMarkdown`: boolean. Whether `markdown` already carries this link.

---

## Input domain

The Input commands run on a page session. Every command below except `Input.probeMovementPersona` and `Input.setInterceptDrags` is asynchronous: it answers once the action has ended. The pointer commands (`moveTo`, `revealElement`, `scrollBy`, `performDrag`, `selectOptions`, `fillDateTime`, `pickColor`, `chooseFiles`) share the conventions listed at the top of this document: the hand, the pointer's position, `hit`/`hitKind`/`reason`, and `actionOutcome`. The common parameters are:

- `intent`: `default`, `confirm`, `navigate`, `casual` or `precise`. Given to `moveTo` and, "as `Input.moveTo`'s", to the commands that move the hand on their way to a control.
- `speedMultiplier`: divides the hand's movement times (default 1).
- `pointerX`, `pointerY`: where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: whether the answer waits for a cross-document navigation the action started to end (at most about 3 s).
- `timeoutMs`: how long the action may take; the default and range differ per command.

### `Input.dispatchMousePath`: batched mouse movement

Dispatches `mouseMoved` events along a path at a polling rate, as a synthetic gesture targeted at the frame under each point, then optionally turns the wheel and presses, releases or clicks at the last point in the same gesture. One call replaces N per-segment `Input.dispatchMouseEvent` round-trips: the browser dispatches the events at a fixed interval of `1000 / pollingRateHz` ms, so polling rates of 500-1000 Hz are reachable. Use it when the client plans the trajectory itself; use `Input.moveTo` to let the browser's hand plan it.

Parameters:
- `path`: array of `MousePathPoint`, required. Positions to move through in sequence, in CSS pixels of the main frame's viewport.
- `pollingRateHz`: integer, required. Hardware polling rate in Hz (e.g. 125, 500, 1000). Events are dispatched at a fixed interval of `1000 / pollingRateHz` milliseconds.
- `button`: `MouseButton`, optional. The button held for the duration of the path (default `none`). Without a held button the moves are hovers: no drag starts and no pointer capture is granted, so a native control stays where the press landed. Set it to drag along the path.
- `modifiers`: integer, optional. Keys held along the path and through its end: Alt=1, Ctrl=2, Meta/Command=4, Shift=8 (default 0).
- `end`: `MousePathEnd`, optional. A press, a release or clicks at the last point, in the same gesture as the moves, so they take the same route real input takes.
- `wheel`: array of `MouseWheelNotch`, optional. Wheel turns at the last point, after the moves and before the end: each a real notch (100 px, one tick), phased and latched by the browser as a real wheel is. A held button is held through them.
- `followNavigation`: boolean, optional. With an `end`: whether the answer waits for a cross-document navigation it started to end (at most about 3 s; default true).

Returns:
- `actionOutcome`: `Page.ActionOutcome`, optional. What the end led to; present only with an `end`.

Example: move along a path, then click at the last point.

```json
{
  "method": "Input.dispatchMousePath",
  "params": {
    "path": [{ "x": 100, "y": 100 }, { "x": 105, "y": 102 }, { "x": 110, "y": 105 }],
    "pollingRateHz": 500,
    "end": { "action": "click", "button": "left", "delayMs": 80, "holdMs": 60 }
  }
}
```

Example: drag with the left button held, then two wheel notches down at the end.

```json
{
  "method": "Input.dispatchMousePath",
  "params": {
    "path": [{ "x": 300, "y": 400 }, { "x": 320, "y": 405 }, { "x": 360, "y": 410 }],
    "pollingRateHz": 250,
    "button": "left",
    "wheel": [{ "notchesY": 1 }, { "notchesY": 1, "delayMs": 120 }]
  }
}
```

### `Input.moveTo`: move the pointer like a hand, and optionally press

Moves the pointer as the hand does (the browser's movement persona): to an element, a box or a point, and on arrival optionally presses, releases or clicks. The hand picks where on an element or box it lands, how long it rests before pressing and how long the button stays down. An element's press is hit-checked first, as a real press would be routed: when something else would take it, nothing is pressed and the answer says what. No path leaves the view. It answers once the move (and the end) is done. This is the usual way to click an element found by `Page.captureAgentSnapshot`.

Parameters:
- `backendNodeId`: integer, optional. An element: its backend node id, as `Page.resolveAgentNode` gives it. Goes with `frameId`.
- `frameId`: string, optional. The element's local root frame, as `Page.resolveAgentNode`'s `localRootFrameId` gives it.
- `aimX`, `aimY`: number, optional. With an element or a box: where on its visible part to land, as fractions across it; absent, the hand's own pick.
- `box`: `PlanRect`, optional. A box, in CSS pixels of the main frame's viewport: the hand picks a point inside it.
- `x`, `y`: number, optional. A point, in CSS pixels of the main frame's viewport.
- `intent`: string, optional. `default`, `confirm`, `navigate`, `casual` or `precise`.
- `end`: `MoveEnd`, optional. What the hand does on arrival. With no target, it is done where the pointer is.
- `modifiers`: integer, optional. Modifier keys held through the move and the end (Alt=1, Ctrl=2, Meta/Command=4, Shift=8).
- `speedMultiplier`: number, optional.
- `check`: boolean, optional. With an element and a press or click: hit-check it before pressing (default true).
- `timeoutMs`: number, optional. How long it may take, in ms (default 15000, 1000-60000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. With a press, release or click: whether the answer waits for a cross-document navigation it started to end (at most about 3 s; default true). Without, the answer still says what started.

Returns:
- `outcome`: string. One of:
  - `arrived`, `pressed`, `released`, `clicked`: the move, and the end asked for, were done.
  - `covered`: something else would take the press; nothing was pressed.
  - `hidden`: none of the element or box shows; reveal it first. With `reason` `notDisplayed`: nothing of it is laid out; with `reason` `vanished`: it lost its box while the hand was on its way, as when a menu holding it closed.
  - `gone`: the element is no longer in the page.
  - `unreachable`: a point outside the view, an element that will not take a press, or one that kept moving from under the hand.
  - `interrupted`: other pointer input came first. Once the end is on its way, the answer is what it does.
  - `timeout`.
- `x`, `y`: number. Where the pointer is now (or once what is on its way has played), in CSS pixels of the main frame's viewport.
- `hit`: string, optional. For `covered`, `unreachable` or `hidden` decided by the hit check: what lies over the point, when it can be named; another document's content is said with where it is ("the page's div#ov", "div#panel in another frame"). A cover in an open layer the element is not in is named by that layer (`listbox "City"`), as is one on that layer's veil, the backdrop beside its box (`dialog "Choose a plan"`); its kind is in `hitKind`. For `pressed` or `clicked`: the part of the element with a control of its own the press landed on, which took it first (a link inside a card), when it did. For `unreachable` with reason `inert`: what switched it off, when it can be named, as `Page.agentHitCheck`'s `hit` says it.
- `hitKind`: string, optional. For `covered`, when `hit` names an open layer the element is not in: that layer's kind: `listbox`, `menu`, `dialog`, `alert`, `popover` or `picker`, or `panel` for a veil's layer with no role. For `unreachable` with reason `inert`, when `hit` names the modal dialog or full-screen element: `dialog`, `alert` or `fullscreen`.
- `reason`: string, optional. Why: the hit check's verdict (`covered`, `nothing`, `otherFrame`, `noPointer`, `inert`, `disabled`, `hidden`) when it decided; `notDisplayed` for an element in the page with nothing of it laid out; `vanished` for one that lost its box while the hand was on its way; else a sentence.
- `corrections`: integer. Re-aims after the element moved under the hand.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the press, release or click led to (navigations of the tab, new tabs, popups refused); present only when the end went out.

Example: click an element resolved from a snapshot.

```json
{
  "method": "Input.moveTo",
  "params": {
    "backendNodeId": 1234,
    "frameId": "5B3A2C...",
    "end": { "action": "click" },
    "intent": "confirm"
  }
}
```

Example response:

```json
{
  "outcome": "clicked",
  "x": 412.6,
  "y": 288.1,
  "corrections": 0,
  "durationMs": 643,
  "actionOutcome": {
    "actionId": 17,
    "handled": true,
    "waitedMs": 1290,
    "events": [
      { "kind": "navigation", "atMs": 41, "state": "started", "url": "https://example.com/next", "mainFrame": true, "frameId": "5B3A2C..." },
      { "kind": "navigation", "atMs": 1203, "state": "committed", "url": "https://example.com/next", "mainFrame": true, "frameId": "5B3A2C..." }
    ]
  }
}
```

Example: a refused press.

```json
{
  "outcome": "covered",
  "x": 412.6,
  "y": 288.1,
  "hit": "dialog \"Choose a plan\"",
  "hitKind": "dialog",
  "reason": "covered",
  "corrections": 0,
  "durationMs": 512
}
```

Example: move to a point with no end, or press and hold.

```json
{
  "method": "Input.moveTo",
  "params": { "x": 640, "y": 360, "intent": "casual" }
}
```

```json
{
  "method": "Input.moveTo",
  "params": {
    "backendNodeId": 1234,
    "frameId": "5B3A2C...",
    "end": { "action": "press", "button": "left" },
    "modifiers": 8
  }
}
```

### `Input.revealElement`: scroll an element into view with the wheel

Brings an element into view as a hand does before it reaches for it: the wheel turned where the pointer is (spins of notches, the scroll waited out, the last ones a notch at a time) until the element is clear of the edges of the window and of every box that scrolls it, or as near as the wheel brings it. An element that already shows, and that a press where a hand would land on it reaches, is left where it is. Where the wheel at the pointer would scroll something that does not hold the element, the hand first moves (as `Input.moveTo` moves it) to a place where it would, at most three times. Use it before `Input.moveTo` when a target is off-screen or clipped by a scrolling box.

Parameters:
- `backendNodeId`: integer, required. The element's backend node id.
- `frameId`: string, required. Its local root frame, as `Page.resolveAgentNode`'s `localRootFrameId` gives it (the main frame's id for an element in the page itself).
- `aimX`, `aimY`: number, optional. The point on it to bring into view, as fractions of its box (default 0.5).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere since the last drag; otherwise it is where the last one left it. Named as `Input.moveTo` names it.
- `x`, `y`: number, optional, **deprecated**. The same as `pointerX` and `pointerY`, under the names this command alone used; `pointerX` and `pointerY` win when both are given. To be removed in a later release.
- `timeoutMs`: number, optional. How long it may take, in ms (default 15000).

Returns:
- `outcome`: string. One of:
  - `shown`: `x` and `y` are where a hand can land on it. An element in no state to be pressed where it shows (inert, as everything outside an open modal is; disabled; or invisible) is also answered `shown`, with `landVerdict` saying which.
  - `blocked`: the wheel brings it no nearer, from where the pointer was nor from where the hand moved to, and it does not show.
  - `covered`: something lies over every place it could be brought to, or over it where the wheel leaves it.
  - `gone`.
  - `timeout`.
  - `interrupted`: other pointer input, or another `revealElement`, came first.
- `x`, `y`: number, optional. The landing point, in CSS pixels of the main frame's viewport.
- `calm`: boolean, optional. With `shown`: whether that point is clear of every scroller's edges, not merely in view.
- `elementX`, `elementY`, `elementWidth`, `elementHeight`: number, optional. The element's box now, in CSS pixels of the main frame's viewport.
- `notches`: integer, optional. The wheel notches turned.
- `windowScrolledX`, `windowScrolledY`: number, optional. How far the window scrolled, in CSS px (positive down or right).
- `boxScrolledX`, `boxScrolledY`: number, optional. How far the nearest scrolling box that holds the element scrolled, in CSS px (positive down or right).
- `box`: string, optional. That scrolling box.
- `covering`: string, optional. With `covered`: what lies over it. A cover in an open layer the element is not in is named by that layer (`listbox "City"`), as is one on that layer's veil, the backdrop beside its box (`dialog "Choose a plan"`).
- `coveringKind`: string, optional. With `covered`, when the last look named an open layer: its kind, as `Input.moveTo`'s `hitKind`. Not given for what lies over every place the element could be brought to.
- `pointerX`, `pointerY`: number, optional. Where the pointer is now (the hand may have moved to turn the wheel where it scrolls what holds the element), in CSS pixels of the main frame's viewport, when that is known.
- `shows`: boolean, optional. With `covered`: whether it shows where it is now (24 px of it each way, or all of it when smaller, inside every box and frame that holds it), so what covers it is on top of it in view. `covered` can be said before any notch, wherever the element is: `false` when it does not show.
- `boxFirst`: boolean, optional. Whether the box (`boxScrolledX`/`Y`) scrolled before the window did, so a reply can name them in the order they scrolled; absent when nothing scrolled, or when both did between two readings.
- `landVerdict`: string, optional. With `shown`: what a press at `x` and `y` meets, as the reveal's last look there found it, in `Page.agentHitCheck`'s words: `reached`, `label`, `covered`, `noPointer`, `inert`, `hidden`, `disabled`, `nothing` or `otherFrame`. `shown` is also answered for an element in no state to be pressed there (which no wheel changes) and, when it is where it should be, for whatever its own document lays over it there: this says which. Absent when no look ran at that landing (an element that does not show, or that the page hides from a frame of another process), or when the answer is a frame element's stage's.
- `landHit`: string, optional. With `landVerdict`: what the look met there, described as a hit is.
- `landHitKind`: string, optional. With `landVerdict`: the kind of the open layer `landHit` is in, as `Page.agentHitCheck`'s `hitKind`.

```json
{
  "method": "Input.revealElement",
  "params": { "backendNodeId": 1234, "frameId": "5B3A2C...", "aimY": 0.4 }
}
```

Example response:

```json
{
  "outcome": "shown",
  "x": 388.2,
  "y": 503.7,
  "calm": true,
  "elementX": 320,
  "elementY": 480,
  "elementWidth": 140,
  "elementHeight": 48,
  "notches": 6,
  "windowScrolledX": 0,
  "windowScrolledY": 600,
  "pointerX": 402.5,
  "pointerY": 377.9,
  "landVerdict": "reached"
}
```

### `Input.scrollBy`: turn the wheel to scroll

Turns the wheel as a hand does to scroll by about `amount` CSS px one way: over an element when one is given (the hand first moves onto the part of it that shows, as `Input.moveTo` moves it, and the landing is checked as a press there would be), else where the pointer is. The scroller is the one the wheel latches there: the innermost box under the pointer with room that way, the box where `overscroll-behavior` stops the chain, or the window. It makes spins of notches at the pace asked, waits the scroll out, turns the last notches one at a time, until it has moved the amount to the nearest notch or reached its end; never on past its end. Wheel notches only: the pointer moves only when the page brings another box under it, and no modifier rides on them. What the scroll leads to is watched from its first notch. It answers once.

Parameters:
- `direction`: string, required. `up`, `down`, `left` or `right`.
- `amount`: integer, optional. CSS px (default 400; 1 to 1000000).
- `pace`: string, optional. `read` (default): spins of one to three notches at a reader's pace. `flick`: longer, quicker spins, for a jump.
- `backendNodeId`: integer, optional. An element to scroll over, as `Page.resolveAgentNode` gives it. Goes with `frameId`.
- `frameId`: string, optional. The element's local root frame.
- `findScroller`: boolean, optional. With no element, when nothing under the pointer scrolls that way and the page cannot scroll that way at all: whether the hand moves over the box that can scroll furthest (default true).
- `speedMultiplier`: number, optional.
- `timeoutMs`: number, optional. How long it may take, in ms (default 30000; 1000 to 120000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the scroll started to end (at most about 3 s; default false). Without, the answer still says what started.

Returns:
- `outcome`: string. One of:
  - `scrolled`: it moved.
  - `end`: already at its end that way; no notch turned.
  - `still`: the wheel turned and what it latched did not move, though it had room: the page takes the wheel there.
  - `none`: nothing at the pointer scrolls that way, nor does the page, nor (with `findScroller`) any box.
  - `hidden`: none of the element shows; nothing moved (`reason` as `Input.moveTo`'s: `notDisplayed`, `hidden`, `vanished`, or a sentence).
  - `covered`: a press at the landing would meet something else, named in `hit`, with the verdict in `reason` (`covered`, `otherFrame`, `nothing`, `inert`); no notch turned. With `inert`, `hit` and `hitKind` are what switched it off, as `Input.moveTo`'s.
  - `unreachable`: the hand could not get onto the element (it kept moving from under the hand, or the landing could not be hit-tested), said in `reason`; no notch turned.
  - `gone`.
  - `interrupted`: other pointer input came first; the figures say how far it got.
  - `timeout`: the same.
- `notches`: integer. The wheel notches turned.
- `before`, `after`: `WheelScroller`, optional. The scroller the wheel turned: before the first notch, and after the last, read once the scroll had run out.
- `pageBefore`, `pageAfter`: number, optional. The main frame's window along the axis, from its visual start, in CSS px, when the scroller is not it and is in the main frame's process.
- `pageFirst`: boolean, optional. Whether the page moved before the scroller did; absent when only one moved, or both between two readings.
- `movedOver`: string, optional. With `findScroller`: the box the hand moved over.
- `hit`: string, optional. See conventions.
- `hitKind`: string, optional. For `covered`, when `hit` names an open layer the element is not in: that layer's kind, as `Input.moveTo`'s `hitKind`.
- `reason`: string, optional.
- `scrollerId`: integer, optional. The scroller's `DOMNodeId` in its local root (a window's: its document's): with that local root, the key a listing names it by.
- `scrollerAgentNodeId`: integer, optional. The scroller as the document's id space holds it, listed by a capture, or the main scroller one named: its `agentNodeId`. Absent when it holds none (a window has none); a scroll never mints one. The own window of a frame of another process goes by its frame element's, when a listing listed that element.
- `scrollerLabel`: string, optional. The scroller's label, under the same rule.
- `pointerX`, `pointerY`: number. Where the pointer is now, in CSS pixels of the main frame's viewport.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the scroll led to (navigations of the tab, new tabs, popups refused); present once a notch went out.

```json
{
  "method": "Input.scrollBy",
  "params": { "direction": "down", "amount": 800, "pace": "flick" }
}
```

Example response:

```json
{
  "outcome": "scrolled",
  "notches": 8,
  "before": { "name": "", "page": true, "position": 0, "raw": 0, "max": 4210, "length": 720 },
  "after": { "name": "", "page": true, "position": 800, "raw": 800, "max": 4210, "length": 720 },
  "pointerX": 640,
  "pointerY": 377.9,
  "durationMs": 1470,
  "actionOutcome": { "actionId": 18, "handled": true, "waitedMs": 1480, "events": [] }
}
```

Example: scroll inside a pane, over an element.

```json
{
  "method": "Input.scrollBy",
  "params": {
    "direction": "down",
    "amount": 300,
    "backendNodeId": 2210,
    "frameId": "5B3A2C..."
  }
}
```

### `Input.performDrag`: a whole drag, planned from the page

Carries out a drag whole, as a hand does: the pointer goes to what is grabbed, presses, moves, turns the wheel under itself while it moves where a scroll is needed, waits the scroll out, lands on the target, checks it is over it, rests and lets go. The page decides the kind: a native drag (a `dragstart` not cancelled) is carried with `dragover`s and dropped; any other with mouse moves with the button held, and released (pointer libraries, sliders). The path is planned from the page: every autoscroll band is crossed quickly, rests happen only where nothing scrolls, and the hand moves as the browser's movement persona does. It answers once, after the drag has ended; a failure ends the drag first (a native one is called off, a pointer one is let go where it was grabbed). Use it for sortable lists, drop zones, sliders and canvas widgets.

Parameters:
- `grabNodeId`: integer, optional. What to grab, as an element: its backend node id, as `Page.resolveAgentNode` gives it. Goes with `grabFrameId`.
- `grabFrameId`: string, optional. The grabbed element's local root frame.
- `grabX`, `grabY`: number, optional. What to grab, as a point in CSS pixels of the main frame's viewport.
- `grabFractionX`, `grabFractionY`: number, optional. Where on the grabbed element to press, as fractions of its box (default its middle; a range input's thumb).
- `targetNodeId`: integer, optional. Where to let go, as an element; goes with `targetFrameId`, aimed at `aimX`/`aimY` of its box.
- `targetFrameId`: string, optional. The target element's local root frame.
- `aimX`, `aimY`: number, optional. Where on the target element to let go, as fractions of its box (default 0.5).
- `slot`: enum, optional. For a sortable list: let go over the target's slot as it was before the drag moved anything: `on` (its middle), `before` (its first third) or `after` (its last third). Default `on`.
- `fractionX`, `fractionY`: number, optional. Where to let go, as a fraction of the grabbed element's box as it is at the release.
- `pointX`, `pointY`: number, optional. Where to let go, as a point in CSS pixels of the main frame's viewport.
- `value`: number, optional. Where to let go, for a range input: the value to reach.
- `modifiers`: integer, optional. Alt=1, Ctrl=2, Meta/Command=4, Shift=8, held through the drag.
- `pressHoldMs`: number, optional. A rest after the press before the hand moves, in ms (0-5000), for a widget that starts a drag only on a long press.
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `speedMultiplier`: number, optional. Divides the hand's movement times (default 1).
- `timeoutMs`: number, optional. How long it may take, in ms (default 30000, 1000-120000).
- `followNavigation`: boolean, optional. Whether the answer to a drop or a release waits for a cross-document navigation it started to end (at most about 3 s; default true).

Exactly one way of saying where to let go is used: an element (`targetNodeId` + `targetFrameId`), a fraction of the grabbed element's box (`fractionX`/`fractionY`), a point (`pointX`/`pointY`), or a `value` for a range input.

Returns:
- `outcome`: string. `dropped` (a native drag dropped on the target), `released` (a pointer drag let go at the landing), `refused` (the page would not take the drop: `dragleave` and `dragend` instead), `covered`, `blocked` (the target could not be brought into view: its scroller is at its end, it shows only in an edge zone of a box that will not scroll, or the carry could not reach it; `reason` says which), `unreachable`, `moved` (the target kept moving away as the wheel turned, or while it was carried to), `missed` (the pointer could not be put over the target: something else was there, named in `hit`, or it could not stay clear of what it had to avoid), `gone`, `timeout`, `cancelled` (the drag ended from outside, or a `dragstart` came after a pointer carry had begun), or `interrupted` (other pointer input came first; right after the press, the release may reach the page as a click).
- `kind`: string. `native`, `pointer`, or `none` (nothing was pressed).
- `reason`: string, optional. With any outcome but `dropped` and `released`: why, in a sentence naming what and where. For `unreachable` before any press: the press check's verdict on the grabbed element when it is in no state to be pressed (`inert`, `disabled` or `hidden`) or not rendered where it would be grabbed (`nothing`). For `missed`: `inert` when the target is inert there.
- `x`, `y`: number, optional. Where the pointer let go (or is), in CSS pixels of the main frame's viewport.
- `hit`: string, optional. What lies under that point. With reason `inert`: what switched it off instead, when it can be named, as `Page.agentHitCheck`'s `hit`, with its kind in `hitKind`.
- `hitKind`: string, optional. When `hit` names an open layer the grabbed element (`covered`) or the target (`missed`) is not in: that layer's kind, as `Input.moveTo`'s `hitKind`.
- `reached`: boolean, optional. Whether the release point was checked over the target before the button came up.
- `grabIndexBefore`, `grabIndexAfter`: integer, optional. The grabbed element's place among its siblings before and after (1-based).
- `siblingCount`: integer, optional. How many siblings there are.
- `list`: string, optional. The grabbed element's list.
- `grabText`: string, optional. The grabbed element's text.
- `grabMovedX`, `grabMovedY`: number, optional. How far the grabbed element's box moved from the press to after the release, in CSS px (positive right or down): for a free-moving element a pointer drag carried, which has no list place or value to read.
- `slotReached`: boolean, optional. With `slot`: whether the grabbed element ended on the side of the target asked for, in the list's order.
- `valueBefore`, `valueAfter`: string, optional. The grabbed element's value (or `aria-valuenow`) before and after.
- `valueReached`: number, optional. For a range input asked for a `value`: the value the release point gives.
- `hitValueBefore`, `hitValueAfter`: string, optional. The value of what lies under the release point, before and after.
- `fractionXReached`, `fractionYReached`: number, optional. Where across the box let go over (the target's for an element, the grabbed element's for a fraction) the release point lies.
- `scrolled`: array of `DragScroll`, optional. Every scroller that moved during the drag, net.
- `unexpected`: array of `DragScroll`, optional. The scrolls the drag did not ask for (a page or a library scrolling on its own, a band the plan did not foresee).
- `notches`: integer, optional. The wheel notches turned.
- `putBack`: boolean, optional. A pointer drag that was called off was let go where it was grabbed.
- `durationMs`: number. How long the drag took, in ms.
- `replans`: integer, optional. How many times the plan was made again.
- `corrections`: integer, optional. How many times the landing was corrected.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the drop or the release led to; present only when it went out.

Example: reorder a sortable list (drop item A after item B).

```json
{
  "method": "Input.performDrag",
  "params": {
    "grabNodeId": 3101,
    "grabFrameId": "5B3A2C...",
    "targetNodeId": 3104,
    "targetFrameId": "5B3A2C...",
    "slot": "after"
  }
}
```

Example response:

```json
{
  "outcome": "dropped",
  "kind": "native",
  "x": 455.3,
  "y": 612.8,
  "hit": "li.item \"Task B\"",
  "reached": true,
  "grabIndexBefore": 1,
  "grabIndexAfter": 4,
  "siblingCount": 6,
  "list": "ul#tasks",
  "grabText": "Task A",
  "slotReached": true,
  "fractionXReached": 0.48,
  "fractionYReached": 0.81,
  "scrolled": [{ "box": "the page", "dx": 0, "dy": 240 }],
  "notches": 3,
  "durationMs": 2810,
  "replans": 1,
  "corrections": 0,
  "actionOutcome": { "actionId": 19, "handled": true, "waitedMs": 310, "events": [] }
}
```

Example: set a range input to a value.

```json
{
  "method": "Input.performDrag",
  "params": { "grabNodeId": 4410, "grabFrameId": "5B3A2C...", "value": 75 }
}
```

### `Input.setInterceptDrags`: `carry` an intercepted drag

Stock `Input.setInterceptDrags` (which makes the browser report drags as `Input.dragIntercepted` events instead of starting a system drag) gains one parameter.

Parameters:
- `enabled`: boolean, required. Stock: whether drags are intercepted.
- `carry`: boolean, optional. Holds an intercepted drag from the moment it starts, as the system's drag loop does (`dragenter` where it started, then a `dragover` every 53-73 ms) until `Input.performDrag` carries it on or ends it, or interception is turned off, which calls it off (default: false).

Returns: nothing.

```json
{
  "method": "Input.setInterceptDrags",
  "params": { "enabled": true, "carry": true }
}
```

### `Input.dispatchKeystrokes`: batched typing with realistic timing

Types a string with realistic timing and optional typos and corrections. One call replaces a per-key `dispatchKeyEvent` loop, so per-key round-trip latency cannot limit the typing rate. Scheduling and dispatch happen in the browser process; the call returns once the full schedule has run. Focus the field first (for example with `Input.moveTo` and a click); the keys go to whatever has focus.

Parameters:
- `text`: string, required. Text to type. May contain `\n` (mapped to Enter). Non-ASCII characters are dispatched as text-only key events with no virtual key code.
- `speedMultiplier`: number, optional. Multiplies all time intervals (> 0). 1.0 is baseline typing speed; values > 1 type faster. Default 1.0.
- `keystrokeDelayMin`, `keystrokeDelayMax`: integer, optional. Inter-keystroke delay range (ms), before speed scaling. Defaults are 60 / 260.
- `keyHoldMin`, `keyHoldMax`: integer, optional. Key hold duration range (ms) between keyDown and keyUp. People hold a key about 70-120 ms; the default range is 65-130. After the speed multiplier a hold is never under 45 ms, nor the range's top under 70 ms.
- `contextAware`: boolean, optional. When true, applies bigram / repeat / punctuation timing adjustments (common English bigrams 30% faster, repeats 20% faster, post-space/punctuation 20% slower). Default true.
- `thinkingPauseProbability`: number, optional. Per-character chance of a "thinking pause" before the keystroke. Default 0 (no pauses).
- `thinkingPauseMin`, `thinkingPauseMax`: integer, optional. The pause's range, in ms.
- `typoProbability`: number, optional. Per-character chance of injecting a typo + correction sequence. Default 0 (no typos). Realistic values are around 0.01-0.03.
- `seed`: number, optional. RNG seed for deterministic typo placement. Same seed + same params + same text produces the same event schedule. Default: a fresh time-derived seed each call. A negative value seeds as its magnitude.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the keys started to end (at most about 3 s; default true).
- `readBack`: boolean, optional. Whether the answer says what the focused field held before the first key and once the keys were handled and it had held still for 150 ms (at most 300 ms more); default false.
- `noTypos`: `NoTypos`, optional. No typo is made in a field this rule holds for, whatever `typoProbability` says. The field the keys start in is read first.

Returns:
- `typosCorrected`: integer. How many typos were made and then corrected with Backspace. The page saw each wrong character until it was deleted.
- `fieldBefore`: `FieldReading`, optional. With `readBack`: the field before the first key.
- `fieldAfter`: `FieldReading`, optional. With `readBack`: the field after the keys. Absent when the keys left the document (an Enter that submitted).
- `actionOutcome`: `Page.ActionOutcome`, optional. What the keys led to.

```json
{
  "method": "Input.dispatchKeystrokes",
  "params": {
    "text": "hello world",
    "speedMultiplier": 1.2,
    "typoProbability": 0.02,
    "thinkingPauseProbability": 0.05,
    "thinkingPauseMin": 400,
    "thinkingPauseMax": 1200,
    "readBack": true,
    "noTypos": {
      "inputTypes": ["password", "email"],
      "autocompleteTokens": ["one-time-code", "cc-number"],
      "autocompletePrefixes": ["cc-"],
      "inputModes": ["numeric"],
      "maxLengthAtMost": 6
    }
  }
}
```

Example response:

```json
{
  "typosCorrected": 1,
  "fieldBefore": { "kind": "value", "backendNodeId": 812, "frameId": "5B3A2C...", "length": 0, "selected": 0, "readonly": false, "disabled": false, "strict": false },
  "fieldAfter": { "kind": "value", "backendNodeId": 812, "frameId": "5B3A2C...", "length": 11, "selected": 0, "readonly": false, "disabled": false, "strict": false },
  "actionOutcome": { "actionId": 20, "handled": true, "waitedMs": 2140, "events": [] }
}
```

### `Input.dispatchKeyChord`: a modifier chord

Presses a key chord on the typing session's path: modifiers go down as left-hand keys (Ctrl, Shift, Alt, Meta), then the key with them, then all come up, with a hand's timing. Use it for shortcuts (Ctrl+A, Ctrl+Z, Shift+Tab) and, with `phase`, to hold modifiers around a mouse click.

Parameters:
- `modifiers`: integer, required. Alt=1, Ctrl=2, Meta/Command=4, Shift=8.
- `key`: string, optional. The key pressed with the modifiers: one character, such as `"v"` or `"a"`, or a key name: `Enter`, `Tab`, `Backspace`, `Escape`, `Delete`, `Insert`, `Home`, `End`, `PageUp`, `PageDown`, `ArrowLeft`, `ArrowUp`, `ArrowRight`, `ArrowDown`, `F1`-`F12`, `Space`, `CapsLock`, `NumLock`, `ScrollLock` (the lock itself is the machine's, and does not change). With Shift a character reports its shifted form, and one that only Shift reaches is pressed with Shift. Omit it to press only the modifiers.
- `phase`: enum, optional. `full` (default): everything goes down and comes up. `down`: only the modifiers go down, and stay down, the last one repeating its keydown as a held key does (after about half a second, then about thirty a second) until the next key input; the call returns once they are down. `up`: held modifiers come up. A ctrl+click is `down`, a mouse click, then `up`.
- `speedMultiplier`: number, optional. Multiplies all timings, as for `dispatchKeystrokes` (default 1.0).
- `followNavigation`: boolean, optional. With a key: whether the answer waits for a cross-document navigation it started to end (at most about 3 s; default true).

Returns:
- `actionOutcome`: `Page.ActionOutcome`, optional. What a chord with a key led to; none for modifiers alone.

```json
{
  "method": "Input.dispatchKeyChord",
  "params": { "modifiers": 2, "key": "a" }
}
```

A ctrl+click:

```json
{ "method": "Input.dispatchKeyChord", "params": { "modifiers": 2, "phase": "down" } }
{ "method": "Input.moveTo", "params": { "backendNodeId": 1234, "frameId": "5B3A2C...", "end": { "action": "click" } } }
{ "method": "Input.dispatchKeyChord", "params": { "modifiers": 2, "phase": "up" } }
```

### `Input.dispatchPaste`: paste text as a person does

Pastes text the way a person does: puts it on this browser's own clipboard and presses Ctrl+V, so the page sees a trusted paste with the text in its `clipboardData`. **Requires `--private-clipboard`**: the call is refused unless the browser runs with it, since it would otherwise overwrite the machine's clipboard. Use it for long text, or for editors that treat typed and pasted input differently.

Parameters:
- `text`: string, required. The text to paste.
- `speedMultiplier`: number, optional. Multiplies the key timing, as for `dispatchKeystrokes` (default 1.0).
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the paste started to end (at most about 3 s; default true).
- `readBack`: boolean, optional. Whether the answer says what the focused field held before the Ctrl+V and after it: read again until it holds the text and holds still, or for at most 1.5 s, since an editor with a document model of its own applies a paste when it is ready; default false.

Returns:
- `fieldBefore`: `FieldReading`, optional. With `readBack`: the field before, as for `dispatchKeystrokes`.
- `fieldAfter`: `FieldReading`, optional. With `readBack`: the field after, with `contains` set.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the paste led to.

```json
{
  "method": "Input.dispatchPaste",
  "params": { "text": "A long paragraph...", "readBack": true }
}
```

```json
{
  "fieldBefore": { "kind": "editor", "backendNodeId": 905, "frameId": "5B3A2C...", "editor": "Monaco", "strict": false },
  "fieldAfter": { "kind": "editor", "backendNodeId": 905, "frameId": "5B3A2C...", "editor": "Monaco", "contains": true },
  "actionOutcome": { "actionId": 21, "handled": true, "waitedMs": 180, "events": [] }
}
```

### `Input.selectOptions`: pick options of a `<select>`

Picks options of a `<select>` the way a person does, as one action: brings it into view, opens a dropdown with the hand's click, reads the list and moves to the option for as long as a person would, and picks it through the list's own code (the page sees no move while the list is open). In a list box, or a dropdown drawn in the page (`appearance: base-select`), it clicks the options themselves, with Ctrl held for each after the first in a multiple one; a dropdown whose list does not open is stepped with the keys on the focused select. Each value matches an option by its value, then the text it shows, then `"Text (value)"`; nothing is touched unless every one matches an enabled option that shows. The pick is the action watched (the opening press is not). It answers once.

Parameters:
- `backendNodeId`: integer, required. The select, as `Page.resolveAgentNode` gives it.
- `frameId`: string, required. Its local root frame.
- `values`: array of string, required. One for a dropdown; the exact set for a multiple list box.
- `intent`: string, optional. As `Input.moveTo`'s, for the hand's moves.
- `speedMultiplier`: number, optional.
- `timeoutMs`: number, optional. How long it may take, in ms (default 15000; 1000 to 60000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the pick started to end (default true).

Returns:
- `outcome`: string. One of:
  - `picked`: done. With a `reason`, once all of the pick went out: `replaced` (the page replaced the select after it) or `navigated` (the frame went, its navigation in `actionOutcome`); `selected` is then as the pick made it.
  - `already`: it showed exactly that; nothing was pressed.
  - `missing`: a value names no option, or only a disabled or a hidden one.
  - `disabled`: the select itself is disabled.
  - `single`: several values for a control that holds one.
  - `notSelect`: not a select.
  - `gone`.
  - `covered`, `hidden`, `unreachable`: a press of the hand refused, as `Input.moveTo`'s (`hit` and `reason`).
  - `keysFailed`: the key route failed; see `keysStopped`.
  - `interrupted`: `reason` `navigated`, `input` or `reset`; `optionsGone` (an option the pick was to click went from the page, as when an `onchange` made the options anew, and the select is still there; `selected` is as it is now); or `gone` (the select went; `selected` is as the last reading before that).
  - `timeout`.
- `way`: string. How it was picked: `popup` (its native list), `popover` (a base-select picker), `listbox`, `keys`, or `none`.
- `whyKeys`: string, optional. With way `keys`: why the list did not open: `windowInactive`, `tabHidden` or `notOpened`.
- `keysRoute`: string, optional. With way `keys`: `arrows`, `homeEnd` (Home or End, then arrows) or `typeAhead`.
- `keysStopped`: string, optional. With `keysFailed`: `noFocus`, `noMove`, `lostFocus` or `gone`.
- `keysMoved`: boolean, optional. With `keysFailed`: whether the keys moved its selection.
- `multiple`: boolean. Whether the select allows several options.
- `selected`: array of `SelectOption`. What is selected now, in list order.
- `deselected`: array of `SelectOption`. What was selected before and is not now.
- `missing`: array of string. Values naming no option.
- `disabledMatches`: array of string. Values naming only a disabled option.
- `hidden`: array of string. Values naming only a hidden (`display: none`) option.
- `options`: array of string. The first 25 options, as `"Text (value)"`, with `" [disabled]"` and `" [hidden]"` marked.
- `optionCount`: integer.
- `hit`: string, optional. See conventions.
- `hitKind`: string, optional. For `covered`, when `hit` names an open layer the select is not in: that layer's kind, as `Input.moveTo`'s `hitKind`.
- `reason`: string, optional.
- `x`, `y`: number. Where the hand is now, in CSS pixels of the main frame's viewport.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the pick led to (navigations of the tab, new tabs, popups refused); present once the pick, a key or an option's click went out.

```json
{
  "method": "Input.selectOptions",
  "params": { "backendNodeId": 2710, "frameId": "5B3A2C...", "values": ["CA"] }
}
```

Example response:

```json
{
  "outcome": "picked",
  "way": "popup",
  "multiple": false,
  "selected": [{ "index": 5, "text": "California", "value": "CA" }],
  "deselected": [{ "index": 0, "text": "Choose a state", "value": "" }],
  "missing": [],
  "disabledMatches": [],
  "hidden": [],
  "options": ["Choose a state ()", "Alabama (AL)", "Alaska (AK)", "Arizona (AZ)", "Arkansas (AR)", "California (CA)"],
  "optionCount": 51,
  "x": 530.4,
  "y": 334.9,
  "durationMs": 1930,
  "actionOutcome": { "actionId": 22, "handled": true, "waitedMs": 240, "events": [] }
}
```

### `Input.fillDateTime`: fill a date or time field

Fills a date or time field (an input of type `date`, `time`, `datetime-local`, `month` or `week`, drawn with its parts) as a person does: the value is checked against the field before anything moves, the field is brought into view, its first part is clicked by the hand, each part is typed (its digits, zero-padded; a month by name its number; AM and PM stepped with ArrowUp; ArrowRight, or Tab in a right-to-left field, where focus does not move on by itself) with no typo, never a separator or a space, and the field is read until it holds the value. The parts go in the field's own order. What the fill leads to is watched from the click. It answers once.

Parameters:
- `backendNodeId`: integer, required. The field, as `Page.resolveAgentNode` gives it.
- `frameId`: string, required. Its local root frame.
- `value`: string, required. As the field's `value` attribute takes it: `2024-05-03` (date), `14:30` or `14:30:15` (time), `2024-05-03T14:30` (datetime-local), `2024-05` (month), `2024-W18` (week).
- `intent`: string, optional. As `Input.moveTo`'s, for the hand's click.
- `speedMultiplier`: number, optional.
- `timeoutMs`: number, optional. How long it may take, in ms (default 15000; 1000 to 60000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the fill started to end (default true).

Returns:
- `outcome`: string. One of:
  - `filled`: it holds the value.
  - `already`: it showed it; nothing was pressed.
  - `notTemporal`: not such a field, or one drawn without parts.
  - `disabled`, `readonly`.
  - `badValue`: not a value of its type; `reason` gives the form.
  - `outOfRange`: the field would not take it, nothing pressed: `reason` `min`, `max` or `step`; `noPart`, with `part`: it shows no second or millisecond the value has; or a part cannot take its piece: `part`, and `reason` `range` or `pinned`.
  - `covered`, `hidden`, `unreachable`: the hand's click refused, as `Input.moveTo`'s (`hit`, `hitKind`, `reason`).
  - `gone`.
  - `keysFailed`: the keys stopped at `part`: `reason` `noFocus`, `notTaken`, `noAdvance` or `lostFocus`.
  - `changed`: its parts were made anew while it was filled.
  - `mismatch`: every key went out and the field does not hold the value.
  - `interrupted`: `reason` `navigated`, `input`, `reset` or `gone`.
  - `timeout`.
- `kind`: string, optional. The field's type, once read.
- `reason`: string, optional.
- `hit`: string, optional.
- `hitKind`: string, optional.
- `part`: string, optional. `year`, `month`, `day`, `hour`, `minute`, `second`, `millisecond`, `ampm` or `week`.
- `complete`: boolean, optional. The field as last read: whether it holds a whole value.
- `badInput`: boolean, optional. Whether a part holds a value while the whole is none.
- `rangeUnderflow`, `rangeOverflow`, `stepMismatch`: boolean, optional. Its validity's range and step flags. The reply never carries the field's value.
- `x`, `y`: number. Where the hand is now, in CSS pixels of the main frame's viewport.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the fill led to (navigations of the tab, new tabs, popups refused); present once the click went out.

```json
{
  "method": "Input.fillDateTime",
  "params": { "backendNodeId": 3310, "frameId": "5B3A2C...", "value": "2024-05-03T14:30" }
}
```

```json
{
  "outcome": "filled",
  "kind": "datetime-local",
  "complete": true,
  "badInput": false,
  "rangeUnderflow": false,
  "rangeOverflow": false,
  "stepMismatch": false,
  "x": 248.0,
  "y": 402.5,
  "durationMs": 2650,
  "actionOutcome": { "actionId": 23, "handled": true, "waitedMs": 190, "events": [] }
}
```

### `Input.pickColor`: set a colour field

Sets a colour field (an input of type `color`) as a person does: the field is read before anything moves, brought into view and clicked by the hand; once its picker shows, a pause as a person choosing takes, then the colour is picked in it through the picker's own commit (what a typed hex code and Enter run: one trusted `input`, then `change` once the picker has closed), and the field is read until it holds the colour. What the pick leads to is watched from when it goes out. It answers once; a picker it opened and did not pick in is closed with nothing chosen.

Parameters:
- `backendNodeId`: integer, required. The field, as `Page.resolveAgentNode` gives it.
- `frameId`: string, required. Its local root frame.
- `value`: string, required. The colour as `#rrggbb`, either case.
- `intent`: string, optional. As `Input.moveTo`'s, for the hand's click.
- `speedMultiplier`: number, optional.
- `timeoutMs`: number, optional. How long it may take, in ms (default 15000; 1000 to 60000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the pick started to end (default true).

Returns:
- `outcome`: string. One of:
  - `picked`: it holds the colour. Or, when it was not read back after the pick, with `reason` `replaced` (the page made the field anew), `navigated` (the tab went on) or `unread` (other input or the time cut the reading short).
  - `already`: it held it; nothing was pressed.
  - `notColor`: not such a field.
  - `disabled`.
  - `covered`, `hidden`, `unreachable`: the hand's click refused, as `Input.moveTo`'s (`hit`, `hitKind`, `reason`).
  - `notOpened`: the click went out and no picker showed: `reason` `tabHidden`, `windowInactive` or `notOpened`; or it closed before the pick: `closed`.
  - `gone`.
  - `mismatch`: the pick went out and the field does not hold the colour.
  - `interrupted`: `reason` `navigated`, `input`, `reset` or `gone`.
  - `timeout`.
- `reason`: string, optional.
- `hit`: string, optional.
- `hitKind`: string, optional.
- `x`, `y`: number. Where the hand is now, in CSS pixels of the main frame's viewport.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the pick led to (navigations of the tab, new tabs, popups refused); present once the pick went out.

```json
{
  "method": "Input.pickColor",
  "params": { "backendNodeId": 3350, "frameId": "5B3A2C...", "value": "#3366ff" }
}
```

```json
{
  "outcome": "picked",
  "x": 198.2,
  "y": 455.0,
  "durationMs": 3120,
  "actionOutcome": { "actionId": 24, "handled": true, "waitedMs": 210, "events": [] }
}
```

### `Input.chooseFiles`: answer a file chooser

Chooses files for a file field as a person does. The paths are checked before anything moves: each one absolute, there and readable; one folder for a folder field (`webkitdirectory`), files for any other; one file for a field that takes one. The element named is clicked by the hand: a file input a press reaches, else its first label that shows, or any element that opens a chooser (a button, a link). The file chooser the page opens from that click is answered with the files after a pause as a person picking them takes (1 to 3 s), through the browser's own answer to a chooser: the page gets read access to them, then `input` and `change`. A folder is listed in the browser, files only, as Chrome lists one. The chooser is answered whether the tab shows or not, and in a headless browser. What the choice leads to is watched from the click. It answers once; a chooser it does not answer is cancelled, as a person closing the dialog does (the page gets `cancel`). Refused when the client lacks local file access, as `DOM.setFileInputFiles` is.

Parameters:
- `backendNodeId`: integer, required. What opens the chooser, as `Page.resolveAgentNode` gives it: a file input, its label, or a button or link that opens one.
- `frameId`: string, required. Its local root frame.
- `files`: array of string, required. Absolute paths: the files, or one folder for a folder field. Each path once: a path named twice is refused.
- `intent`: string, optional. As `Input.moveTo`'s, for the hand's click.
- `speedMultiplier`: number, optional.
- `timeoutMs`: number, optional. How long it may take, in ms (default 30000; 1000 to 120000).
- `pointerX`, `pointerY`: number, optional. Where the pointer is, in CSS pixels of the main frame's viewport, for when no mouse path has put it anywhere yet.
- `followNavigation`: boolean, optional. Whether the answer waits for a cross-document navigation the choice started to end (default true).

Returns:
- `outcome`: string. One of:
  - `chosen`: the field holds the files, by name, or a folder's as many as were listed. Or, when not read back after the files went to the chooser, with `reason` `detached` (its field is not in the page), `replaced` (the page made the field anew), `navigated` (the tab went on) or `unread` (other input or the time cut the reading short, or the page was too large to find the field in).
  - `missing`: a path is not there or cannot be read, or (`reason` `empty`) a folder holding no file; `path` names it.
  - `notFolder`: a folder field given a file (`path` names it); or more than one folder (`reason` `oneFolder`; `path` names the second).
  - `folder`: a file field given a folder (`path`).
  - `single`: several files for a field that takes one.
  - `disabled`.
  - `hiddenInput`: a file input that shows no box to press (none, one clipped away, or one under 4 px) and no label that does: name the element that opens it instead (see `opener`).
  - `covered`, `hidden`, `unreachable`: the hand's click refused, as `Input.moveTo`'s (`hit`, `hitKind`, `reason`). A refused press on the field itself is tried once more on its label that shows.
  - `noChooser`: the click went out and no chooser opened within 5 s, the life of the click's activation: the page did nothing with it, or used another picker such as `showOpenFilePicker`. The click reached the element named, so `hit` is left out.
  - `otherField`: the chooser came from another file input than the one named, or from a frame outside the element named's local root (another process), and was cancelled; `field`, `hit` and `count` are left out.
  - `gone`.
  - `mismatch`: the chooser was answered and the field does not hold the files; `reason` `empty`: it holds none, as a page that uploads on change and empties the field leaves it.
  - `interrupted`: `reason` `navigated` (also when the chooser's frame went before the files did), `input`, `reset` or `gone`.
  - `timeout`.
  The `single`, `notFolder` and `folder` checks are made again on the chooser itself when the element named was not the field: the chooser is then cancelled.
- `reason`: string, optional.
- `hit`: string, optional.
- `hitKind`: string, optional.
- `path`: string, optional. The path a refusal is about, as given.
- `field`: string, optional. The file input the chooser came from, described as a hit is (none for one not in the page, and for `otherField`).
- `mode`: string, optional. What the field takes: `single`, `multiple` or `folder`.
- `accept`: string, optional. The field's `accept` as it gives it (`.png`, `image/*`), or the chooser's accepted types; a person's dialog filters on it.
- `opener`: string, optional. With `hiddenInput`: the nearest element around the field that shows and listens for a press, which may open it, described as a hit is.
- `pressed`: string, optional. What the hand pressed when it was not the element named: the field's label that shows, pressed in the field's place (a field with no box to press, or one whose press was refused), described as a hit is (`label "Upload resume"`).
- `count`: integer, optional. How many files the field holds as last read (a folder's files for a folder field).
- `x`, `y`: number. Where the hand is now, in CSS pixels of the main frame's viewport.
- `durationMs`: number.
- `actionOutcome`: `Page.ActionOutcome`, optional. What the choice led to (navigations of the tab, new tabs, popups refused); present once the click went out.

```json
{
  "method": "Input.chooseFiles",
  "params": {
    "backendNodeId": 3601,
    "frameId": "5B3A2C...",
    "files": ["C:\\Users\\me\\Documents\\resume.pdf"]
  }
}
```

```json
{
  "outcome": "chosen",
  "field": "input#resume",
  "mode": "single",
  "accept": ".pdf,.docx",
  "pressed": "label \"Upload resume\"",
  "count": 1,
  "x": 301.7,
  "y": 522.3,
  "durationMs": 3480,
  "actionOutcome": { "actionId": 25, "handled": true, "waitedMs": 220, "events": [] }
}
```

### `Input.probeMovementPersona`: the hand's persona

A test probe of the hand. Answers the human-movement persona the browser derives from a seed, every field: the 31 persona fields in draw order, the approach hesitation's three per-persona parameters and the tremor's harmonics. One seed, one hand: a client that models the same persona can compare its own derivation field for field, so a path planned on either side is one hand. Seeds travel as decimal strings because a protocol integer is 32-bit and a number loses precision above 2^53, while the seed is a full int64. Doubles go out unaltered.

Parameters:
- `seed`: string, optional. The seed, a decimal int64 (default: the browser's own persona seed: `--movement-persona-seed`; without it, in the release binary, the master `--fingerprint-seed`; otherwise the random seed this browser run drew).

Returns:
- `seed`: string. The seed the persona was derived from, a decimal int64.
- The 31 persona fields, in draw order: `speedFactor`, `curvatureBias`, `tremorAmplitude`, `tremorFrequencyCenter`, `clickOffsetBiasX`, `clickOffsetBiasY`, `pauseMeanMs`, `pauseLogSd`, `overshootProbability`, `idleDriftAmplitude`, `peakVelocityPosition`, `fittsA`, `fittsB`, `fittsNoise`, `clickDriftAmplitude`, `clickHoldMeanMs`, `clickHoldSdMs`, `activityDensityThreshold`, `keyboardToMouseDelayMs`, `mouseToKeyboardDelayMs`, `postIdleSlowdownThresholdMs`, `firstInteractionDelayMs`, `driftIntervalMs`, `driftRadius`, `driftCorrelation`, `gripShiftIntervalMs`, `gripShiftSize`, `scrollMomentumDecay` (all `number`), `scrollBurstLength` (integer), `scrollCursorDriftScale` (number), `pollingRateHz` (integer).
- `approachAdjustments`: integer. The approach hesitation's number of direction changes.
- `approachAmplitudePx`: number. Their amplitude in px.
- `approachNearStopMs`: number. The near-stop in ms.
- `tremorX`, `tremorY`: array of number. The tremor generator's harmonics, one axis each: nine values, the three frequencies (Hz), then the three amplitudes (px), then the three phases (radians).
- `tremorBroadbandScale`: number. The broadband noise scale, in px.

```json
{
  "method": "Input.probeMovementPersona",
  "params": { "seed": "8838290034121" }
}
```

### Event `Input.actionOutcome`

Something an action led to after its answer (a navigation's start or end, a new tab, a popup refused) until the next action arms. Sent to the session whose command armed it. Pair it with the `actionId` of the `actionOutcome` in that command's reply.

Parameters:
- `actionId`: integer. The action's id, as its answer's `actionOutcome` gave it.
- `event`: `Page.ActionEvent`. What happened.

```json
{
  "method": "Input.actionOutcome",
  "params": {
    "actionId": 17,
    "event": { "kind": "navigation", "atMs": 3410, "state": "committed", "url": "https://example.com/next", "mainFrame": true, "frameId": "5B3A2C..." }
  }
}
```

### Event `Input.permissionPromptDismissed`

The browser closed a permission prompt of this page unanswered, as a person closing it would. **Requires `--dismiss-permission-prompts`**: that switch makes the browser dismiss each prompt after a random 1-5 s, and this event is sent when it does, whatever action is under way or none.

Parameters:
- `permissions`: array of string. What was asked, by Chrome's names for it: `geolocation`, `notifications`, `camera_stream`, `mic_stream`, `clipboard`, `file_system`, ...
- `origin`: string. The origin that asked.
- `crossOrigin`: boolean. Whether that origin differs from the top page's: a frame of another origin asked.
- `frameId`: string. The frame that asked; the page's main frame when not known.
- `shownMs`: number. How long the prompt stood before it was closed, in ms.

```json
{
  "method": "Input.permissionPromptDismissed",
  "params": {
    "permissions": ["notifications"],
    "origin": "https://example.com",
    "crossOrigin": false,
    "frameId": "5B3A2C...",
    "shownMs": 2870
  }
}
```

### Input domain types

#### `Input.MousePathPoint`

A point along a mouse movement path.

- `x`: number. X coordinate relative to the main frame's viewport in CSS pixels.
- `y`: number. Y coordinate relative to the main frame's viewport in CSS pixels.

#### `Input.MousePathEnd`

What happens at the end of a mouse path, once the pointer has arrived (`Input.dispatchMousePath`'s `end`).

- `action`: enum, required. `press`: the button goes down and stays down. `release`: a held button comes up. `click`: down and up, `clickCount` times.
- `button`: `MouseButton`, optional. The button pressed or released (default `left`).
- `clickCount`: integer, optional. Clicks in a row, for action `click`: 2 is a double click (default 1).
- `delayMs`: number, optional. The pause from the last move to the first press or release, in milliseconds (default 0).
- `holdMs`: number, optional. How long each click's button stays down, in milliseconds (default 0).
- `gapMs`: number, optional. The pause from one click's release to the next click's press, in milliseconds (default 0).

#### `Input.MouseWheelNotch`

One turn of the mouse wheel, at the end of a mouse path.

- `notchesX`: integer, optional. Notches turned sideways: positive scrolls right (default 0).
- `notchesY`: integer, optional. Notches turned: positive scrolls down (default 0).
- `delayMs`: number, optional. The pause before this turn, in milliseconds (default 0).

#### `Input.MoveEnd`

What `Input.moveTo`'s hand does on arrival. Unlike `MousePathEnd`, it carries no timings: the hand picks them.

- `action`: enum, required. `press`: the button goes down and stays down. `release`: a held button comes up. `click`: down and up, `clickCount` times.
- `button`: `MouseButton`, optional. The button (default `left`).
- `clickCount`: integer, optional. Clicks in a row, for `click`: 2 is a double click (default 1, at most 3).

#### `Input.PlanRect`

A rectangle, `Input.moveTo`'s `box`: in CSS pixels of the main frame's viewport.

- `x`, `y`, `width`, `height`: number.

#### `Input.WheelScroller`

One scroller along `Input.scrollBy`'s axis.

- `name`: string. Named as covers are (`tag#id` or `tag.class`, then its text when short); empty for the main frame's window. A frame's window is named by its frame element; a frame of another process's by that element's role (`Iframe`) when a listing listed it, else empty.
- `page`: boolean. Whether it is the main frame's window.
- `position`: number. Along the axis, in CSS px, from its visual start (a reversed box counts from where it begins on screen). Distances are taken from this.
- `raw`: number. Along the axis, in CSS px, as `scrollTop` or `scrollLeft` gives it.
- `max`: number. As far as it goes, in CSS px.
- `length`: number. How long it shows along the axis, in CSS px.

#### `Input.DragScroll`

How far a scroller moved during `Input.performDrag`, net, in CSS px (positive down or right).

- `box`: string. `"div#L"`, or `"the page"`.
- `dx`, `dy`: number.

#### `Input.SelectOption`

An option of a `<select>`, in `Input.selectOptions`' `selected` and `deselected`.

- `index`: integer. Its index in the select's list.
- `text`: string.
- `value`: string.

#### `Input.NoTypos`

The rule a typing call gives for fields where a wrong character costs something, so none is made there. A field matches when its input type is one of `inputTypes`, one of its `autocomplete` tokens is one of `autocompleteTokens` or starts with one of `autocompletePrefixes`, its `inputmode` is one of `inputModes`, or its `maxlength` is 1 to `maxLengthAtMost`.

- `inputTypes`: array of string, optional.
- `autocompleteTokens`: array of string, optional.
- `autocompletePrefixes`: array of string, optional.
- `inputModes`: array of string, optional.
- `maxLengthAtMost`: integer, optional.

#### `Input.FieldReading`

What the focused field holds, read by its own renderer: facts only, never its value. Returned by `dispatchKeystrokes` and `dispatchPaste` with `readBack`.

- `kind`: string. `value` (an input or a textarea), `editable` (a contenteditable host), `editor` (the hidden input of a CodeMirror, Ace or Monaco editor), `temporal` (a date or time field: an input of type date, time, datetime-local, month or week, whichever of its parts has focus), `other` (focus is on something that holds no text), `none` (nothing but the page has focus).
- `backendNodeId`: integer, optional. The field, as `Page.resolveAgentNode` names one: its backend node id in its own frame.
- `frameId`: `Page.FrameId`, optional. That frame.
- `length`: integer, optional. `value` and `editable`: characters it holds.
- `selected`: integer, optional. `value` and `editable`: characters selected in it.
- `readonly`, `disabled`: boolean, optional. `value` and `temporal`: as the field says.
- `maxLength`: integer, optional. `value`: its `maxlength`, when it has one.
- `editor`: string, optional. `editor`: `CodeMirror`, `Ace` or `Monaco`.
- `what`: string, optional. `other`: what has focus, as a refusal names an element (`button#save "Save"`).
- `tag`: string, optional. `other`: its tag.
- `inputType`: string, optional. `other`: an input's type.
- `complete`: boolean, optional. `temporal`: whether it holds a whole value.
- `badInput`: boolean, optional. `temporal`: whether a part holds a value while the whole is none (`validity.badInput`).
- `part`: string, optional. `temporal`: the part with focus (`year`, `month`, `day`, `hour`, `minute`, `second`, `millisecond`, `ampm` or `week`). Never a value.
- `strict`: boolean, optional. The call's `noTypos` rule holds for it: no typo was made in it.
- `contains`: boolean, optional. `dispatchPaste`: the text pasted is in it, line breaks compared as `\n`; absent when it was not looked for (a field over 2,000,000 characters).
- `moved`: boolean, optional. After the call: the field the reading before it found is still in the page and no longer has focus; focus moved on by itself, as a code split across boxes does.

---

## Page domain

The Page commands run on a page session. `captureAgentSnapshot`, `agentNodesAlive`, `agentAnnouncements`, `agentReport`, `resolveAgentNode`, `agentHitCheck`, `agentSettle` and `agentNavigateToHistoryEntry` are asynchronous: they answer once every frame has been read, or the wait has ended. A few terms recur:

- **Document and listing.** A page's *document* is what the main frame has committed; `documentId` names its id space (the same after a back/forward cache restore). Every `captureAgentSnapshot` is a *listing* of that document, named by `listingId`; the document's last three listings can serve as the baseline of a delta.
- **Local root.** The frames of one renderer process. A page with out-of-process iframes has several; replies say how many local roots did not answer in time (`unansweredFrames`), and a few fields are given in a local root's own coordinates.
- **Layers.** A modal, a drawer, a menu, a popover: something open on top of the page. `captureAgentSnapshot` with `scope` `on` or `all` lists them bottom to top, and reports judge the stack against the one last read for the document (the *baseline stack*).
- **Live regions.** `aria-live` regions, roles `alert`/`status`/`log`, and `<output>`. The browser keeps what they said around each action.

### `Page.captureAgentSnapshot`: one-call page perception

Captures one agent-perception frame: the interactive elements across all frames (cross-origin iframes and open or closed shadow DOM included), with geometry composed into the root viewport and cross-context occlusion flags, plus an OOPIF-aggregated screenshot. Elements that are in the viewport, interactive and not obscured are *marked*: they get a short label (`a1`, `a2`, ...) and a distinct outline colour drawn on the screenshot, so a caller can name a target unambiguously. A hidden page is brought to the front first (`broughtForward`); a page frozen by `setWebLifecycleState` fails at once. Use it instead of an accessibility-tree walk plus per-frame coordinate math.

Parameters:
- `format`: enum, optional. Screenshot compression format: `jpeg`, `png` or `webp` (defaults to `png`).
- `quality`: integer, optional. Compression quality 0-100 (`jpeg`/`webp` only).
- `offscreenMode`: enum, optional. How to report elements outside the root viewport: `none` (drop them), `summary` (off-screen, only what can be acted on, is named, or is a progress bar or meter), `full` (all). Defaults to `summary`.
- `includeScreenshot`: boolean, optional. Include the screenshot in the response (defaults to true).
- `screenshotMaxPixels`: integer, optional. The image's largest area in pixels. It is brought to CSS-pixel resolution, then scaled down to fit; never up. 0 keeps the device resolution. Defaults to 1125000 (about 1.5k model tokens).
- `scope`: enum, optional. The layers open on the page (a modal, a drawer, a popover). `on`: report them, and leave out what a click cannot reach; `all`: report them, everything listed. Defaults to `off`.
- `since`: string, optional. A `listingId` from this document; the reply then carries `delta` when it is one of the document's last three listings, taken with the same `scope` and `offscreenMode`.
- `holdForSecrets`: boolean, optional. The caller holds secrets: the reply carries `redaction`, the frozen frame's painted text, and no screenshot; `agentFinishCapture` gives the image once the caller says what to black out. Without it, card fields and frames that could not be checked are blacked, and the image comes with the reply.
- `marks`: boolean, optional. `false` leaves the listing's outlines and badges off the image, the page as it is; the listing keeps its labels and colours. Defaults to true.
- `clip`: `Viewport`, optional. A rectangle of the root viewport to keep, in DIPs as the elements' boxes are given (the view's CSS px at zoom 100%); the rest is cut from the full-resolution copy after the redaction and before the scale, in the browser, with nothing changed on the page. The stock `Page.Viewport` type's `scale` is ignored. One that meets none of the view withholds the image (`clipOutside`).

Returns:
- `url`: string. Page URL at capture time.
- `title`: string. Page title at capture time.
- `viewport`: `AgentSnapshotViewport`. Viewport and scroll geometry.
- `elements`: array of `AgentSnapshotElement`. Interactive elements, composed into root-viewport space; at most 1500 (see `elementsCut`).
- `screenshot`: binary (base64), optional. The OOPIF-aggregated screenshot; present with `includeScreenshot`.
- `snapshotToken`: string. Cheap change-detection token over the URL, geometry and element identities.
- `layers`: array of `AgentLayer`, optional. With scope `on` or `all`: the layers open on the page, bottom to top.
- `hidden`: array of `AgentHiddenGroup`, optional. With scope `on`: what was left out, by what it is behind.
- `listingId`: string. Names this listing; usable as a later capture's `since`.
- `documentId`: string. Names the document's id space (the same after a back/forward cache restore).
- `baseline`: boolean, optional. Present when `since` was given: whether it matched.
- `delta`: `AgentSnapshotDelta`, optional. What changed since the listing named by `since`.
- `regions`: array of `AgentLiveRegion`. The live regions with text now.
- `heard`: array of `AgentHeard`. What the regions said since the last action.
- `unansweredFrames`: integer. Local roots that gave no answer.
- `redaction`: `AgentRedaction`, optional. With `holdForSecrets` and an image: what the frozen frame drew of text, for `agentFinishCapture`'s answer.
- `screenshotWithheld`: enum, optional. Why there is no screenshot this time. `pageTooLarge`: the text of the page's own frame that is searched (what can show, and the text around it) passed what is searched while secrets are held, or the walk past it ran out of time. `mainFrameNotFrozen`: its frame could not be held still for the copy in the tries the capture had time for. `inputDuringCopy`: input that moves the drawing came during the last of them. `captureExpired`: the capture was not finished in time. `blank`: the page is `about:blank` with nothing in it. `clipOutside`: the clip asked for met none of the view.
- `framesBlacked`: integer, optional. Frames painted solid in the screenshot, as they could not be checked; absent for none.
- `scroller`: `AgentSnapshotScroller`, optional. The page's main scroller; absent when nothing scrolls, or when `lockedBehindLayer` says why.
- `lockedBehindLayer`: integer, optional. With layers: a blocking layer is on top and nothing inside it scrolls: its index into `layers`. `scroller` is then absent; `viewport`'s scroll fields stay the document's.
- `documentLocked`: boolean, optional. The page's document is scroll locked: `overflow` hidden or clip on `<html>` or `<body>`, or either fixed on a window that cannot scroll. Absent when it is not.
- `broughtForward`: boolean, optional. The page was hidden, and was brought to the front for the capture; absent when it was not.
- `elementsCut`: integer, optional. Interactive elements left out past the 1500 a capture composes (the rest of the listing's order); absent when none were.

```json
{
  "method": "Page.captureAgentSnapshot",
  "params": { "format": "webp", "quality": 80, "offscreenMode": "summary", "scope": "on" }
}
```

Example response (abridged):

```json
{
  "url": "https://example.com/checkout",
  "title": "Checkout",
  "viewport": { "width": 1280, "height": 720, "deviceScaleFactor": 1, "scrollX": 0, "scrollY": 0, "scrollWidth": 1280, "scrollHeight": 2140, "screenshotScale": 1 },
  "elements": [
    {
      "backendNodeId": 812, "agentNodeId": 41, "frameId": "5B3A2C...", "role": "textbox", "name": "Email", "value": "",
      "tag": "input", "interactive": true, "interactiveReason": "form-control",
      "states": ["visible", "enabled", "focusable", "editable", "required"],
      "x": 320, "y": 180, "width": 400, "height": 40, "inViewport": true, "obscured": false,
      "label": "a1", "marked": true, "color": "red", "reads": "Email"
    },
    {
      "backendNodeId": 1234, "agentNodeId": 42, "frameId": "5B3A2C...", "role": "button", "name": "Pay now",
      "tag": "button", "interactive": true, "interactiveReason": "role",
      "states": ["visible", "enabled", "focusable"],
      "x": 320, "y": 640, "width": 160, "height": 48, "inViewport": true, "obscured": false,
      "label": "a2", "marked": true, "color": "blue", "reads": "Pay now"
    }
  ],
  "screenshot": "UklGRi4AAABXRUJQ...",
  "snapshotToken": "9f2c1a...",
  "layers": [],
  "hidden": [],
  "listingId": "L-7",
  "documentId": "D-3",
  "regions": [],
  "heard": [],
  "unansweredFrames": 0,
  "scroller": { "positionX": 0, "positionY": 0, "maxX": 0, "maxY": 1420, "lengthX": 1280, "lengthY": 720, "x": 0, "y": 0, "width": 1280, "height": 720, "isPage": true, "wheelReaches": true }
}
```

Example: a second capture with a delta against the first.

```json
{
  "method": "Page.captureAgentSnapshot",
  "params": { "offscreenMode": "summary", "scope": "on", "since": "L-7", "includeScreenshot": false }
}
```

```json
{
  "url": "https://example.com/checkout",
  "title": "Checkout",
  "viewport": { "width": 1280, "height": 720, "deviceScaleFactor": 1, "scrollX": 0, "scrollY": 0, "scrollWidth": 1280, "scrollHeight": 2140 },
  "elements": [ "..." ],
  "snapshotToken": "0b77e4...",
  "layers": [
    { "kind": "dialog", "name": "Choose a plan", "head": "Choose a plan. Basic. Pro. Close.", "how": "top-layer", "blocking": true, "nodeId": 77, "frameId": "5B3A2C...", "elementCount": 3, "behindCount": 12 }
  ],
  "hidden": [ { "behind": "Choose a plan", "layer": 0, "inView": 9, "offscreen": 3 } ],
  "listingId": "L-8",
  "documentId": "D-3",
  "baseline": true,
  "delta": {
    "unchanged": false,
    "added": [ { "agentNodeId": 58, "why": "new" }, { "agentNodeId": 59, "why": "new" }, { "agentNodeId": 60, "why": "new" } ],
    "removed": [ { "agentNodeId": 42, "label": "a2", "role": "button", "name": "Pay now", "why": "covered", "wasInView": true, "baselineIndex": 1, "behindLayer": 0 } ],
    "changed": [],
    "reordered": [],
    "focus": { "agentNodeId": 58, "label": "a18" },
    "layersOpened": [0],
    "layersClosed": [],
    "announcements": [],
    "partial": false
  },
  "regions": [],
  "heard": [],
  "unansweredFrames": 0,
  "lockedBehindLayer": 0
}
```

Example: hold the image for redaction, then finish it (see `agentFinishCapture`).

```json
{
  "method": "Page.captureAgentSnapshot",
  "params": { "holdForSecrets": true, "marks": false }
}
```

### `Page.agentFinishCapture`: the image of a held capture

Returns a held capture's image (`captureAgentSnapshot` with `holdForSecrets`), with the runs and fields the caller found to hold secrets blacked out, then scaled and marked as the capture's would have been. Fails `captureExpired` for an unknown capture, one over 10 s old, or a page that changed document; `frames` must answer every frame of the redaction.

Parameters:
- `captureId`: string, required. From the capture's `redaction.captureId`.
- `frames`: array of `AgentFinishFrame`, required. One per entry of `redaction.frames`, by index: the runs that show part of a secret, and the fields that hold one.

Returns:
- `screenshot`: binary (base64). The image.
- `screenshotScale`: number. Image pixels per CSS pixel.

```json
{
  "method": "Page.agentFinishCapture",
  "params": {
    "captureId": "C-12",
    "frames": [
      { "runs": [14, 15], "fields": [2] },
      { "runs": [], "fields": [] }
    ]
  }
}
```

### `Page.resolveAgentNode`: re-locate a snapshot element

Resolves an `agentNodeId` of this document to the element's current border box in the root viewport's CSS-pixel space, the same units as `AgentSnapshotElement`, and to the handle the Input commands take (`backendNodeId` plus `localRootFrameId`). Works uniformly for elements in cross-origin frames. Fails "the page did not answer" when the renderer holding the element has not answered within 10 s. Use it to confirm a target has not moved between perception and action without paying for a full re-snapshot, and to turn an `agentNodeId` into the `backendNodeId`/`frameId` pair the Input commands want.

Parameters:
- `agentNodeId`: integer, required. From a prior `captureAgentSnapshot`.

Returns:
- `found`: boolean. `false` when the id is unknown or the element is gone or not laid out.
- `x`, `y`, `width`, `height`: number, optional. The border box now.
- `backendNodeId`: `DOM.BackendNodeId`, optional. The element's backend node id in the renderer that holds it, for `DOM.resolveNode` on the session attached to `localRootFrameId`, and for the Input commands' `backendNodeId`.
- `localRootFrameId`: `FrameId`, optional. Id of the local root frame the element lives under: the main frame's id for in-process frames, the out-of-process iframe's target id otherwise. Names the session that can resolve `backendNodeId`, and is the Input commands' `frameId`.

```json
{
  "method": "Page.resolveAgentNode",
  "params": { "agentNodeId": 42 }
}
```

```json
{
  "found": true,
  "x": 320,
  "y": 640,
  "width": 160,
  "height": 48,
  "backendNodeId": 1234,
  "localRootFrameId": "5B3A2C..."
}
```

### `Page.agentHitCheck`: would a press reach this element?

Whether a mouse press at a point would reach an element found by `captureAgentSnapshot`, or one named by its node and frame. The point is routed the way a real press is routed, and the element's own renderer runs the hit test a real press runs; no script runs in the page. Fails "the page did not answer" when no answer has come within 10 s. Use it to check a landing point before pressing, or to learn what covers an element. `Input.moveTo` runs this check itself before an element's press.

Parameters:
- `agentNodeId`: integer, optional. The element, by an `agentNodeId` of this document. Or else `backendNodeId` with `frameId`.
- `x`, `y`: number, required. The point, in CSS pixels of the main frame's viewport, as input events take it.
- `backendNodeId`: integer, optional. The element by its backend node id in the renderer of `frameId`'s local root: a selector's match, or a control a form fill found again. A frame element named this way counts a hit in its own frame as one on it, as one named by `agentNodeId` does.
- `frameId`: string, optional. The local root frame for `backendNodeId`.

Returns:
- `verdict`: string. One of:
  - `reached`: the press lands on the element or inside it.
  - `label`: it lands on a `<label>` for it, which passes the click on.
  - `covered`: something else is on top.
  - `noPointer`: the element lets the pointer through (`pointer-events: none`).
  - `inert`: the page has switched it off, as everything outside an open modal dialog is (with none, outside a full-screen element), what an `inert` attribute holds, and a frame's content when its frame element is.
  - `hidden`: it is not visible.
  - `disabled`: it is, or sits in, a disabled form control, which swallows the press.
  - `nothing`: nothing is there to press.
  - `otherFrame`: content from another frame is on top.
  - `gone`: it is no longer in the page.
  For an element in a frame of another process, the page's own content on top is `covered`, and `hit` says so ("the page's div#ov"); another frame's is `otherFrame` ("div#panel in another frame").
- `hit`: string, optional. What the press would reach instead, when that is not the element. For `reached`: the part of it with a control of its own the press lands on (a link inside a card), when it does. A cover in an open layer the element is not in is named by that layer (`listbox "City"`), as is one on that layer's veil, the backdrop beside its box (`dialog "Choose a plan"`). For `inert`: what switched it off, when it can be named: the modal dialog or full-screen element open outside it, named as its layer is, or the element whose `inert` attribute holds it (`div#main`), with where it is for a frame's content ("the page's div#main").
- `hitKind`: string, optional. When `hit` names an open layer the element is not in: that layer's kind: `listbox`, `menu`, `dialog`, `alert`, `popover` or `picker`, or `panel` for a veil's layer with no role. Not given for content of another frame process. For `inert`, when `hit` names the modal dialog or full-screen element: `dialog`, `alert` or `fullscreen`.

```json
{
  "method": "Page.agentHitCheck",
  "params": { "agentNodeId": 42, "x": 400, "y": 664 }
}
```

```json
{ "verdict": "covered", "hit": "dialog \"Choose a plan\"", "hitKind": "dialog" }
```

### `Page.agentNodesAlive`: are these elements still there?

Whether elements are still in this document, by `agentNodeId` or label; one answer per id, then per label, in order. No script runs in the page. Use it to validate a set of handles cheaply before acting, or to learn where an element went (off-screen, behind a layer, covered).

Parameters:
- `agentNodeIds`: array of integer, optional.
- `labels`: array of string, optional. Labels as a listing gave them (`a1`, `a2`, ...).
- `layers`: boolean, optional. Also read the page's layer stack (the frames that show a tenth of the view, 300 ms each), so that `behindOpen` can be answered. The stack is not kept as the baseline; `agentAnnouncements` with `layers`, a report or a capture judge it and keep it.

Returns:
- `documentId`: string.
- `nodes`: array of `AgentNodeLife`. One per id, then one per label, in order.

```json
{
  "method": "Page.agentNodesAlive",
  "params": { "agentNodeIds": [41, 42], "labels": ["a7"], "layers": true }
}
```

```json
{
  "documentId": "D-3",
  "nodes": [
    { "agentNodeId": 41, "label": "a1", "state": "alive", "role": "textbox", "name": "Email", "placement": "view", "rendered": true, "reads": "Email" },
    { "agentNodeId": 42, "label": "a2", "state": "alive", "role": "button", "name": "Pay now", "placement": "behind", "behind": { "kind": "dialog", "name": "Choose a plan", "frameId": "5B3A2C...", "nodeId": 77 }, "rendered": true, "behindOpen": true },
    { "label": "a7", "state": "gone" }
  ]
}
```

### `Page.agentAnnouncements`: live regions and what they said

The live regions of every frame, and what they said since the last action. Use it after an action to read toasts, status text and validation messages without parsing the whole page, and, with `layers`, to judge the layer stack.

Parameters:
- `layers`: boolean, optional. Also read the page's layer stack (the frames that show a tenth of the view, in the same 300 ms, which the answer then waits for), judge it against the stack this document last read, as `agentReport` does, and keep it as the next baseline: a layer told here is a kept one for the next report, its closing animation waited out as any.

Returns:
- `documentId`: string.
- `regions`: array of `AgentLiveRegion`. The regions with text now.
- `heard`: array of `AgentHeard`. What they said since the last action.
- `unansweredFrames`: integer.
- `layers`: array of `AgentLayer`, optional. With `layers`: the stack judged, bottom to top; a frame not read keeps its own, neither opened nor closed. Absent when this document had no stack read before (the next report then tells every layer open) or was replaced meanwhile.
- `layersOpened`: array of integer, optional. Indices into `layers` not in the baseline stack.
- `layersClosed`: array of `AgentLayer`, optional. In the baseline stack and not open now, as they were read then.
- `layersReworded`: array of `AgentLayerReworded`, optional. Kept since the baseline, its head changed.

```json
{
  "method": "Page.agentAnnouncements",
  "params": { "layers": true }
}
```

```json
{
  "documentId": "D-3",
  "regions": [
    { "regionId": 3, "frameId": "5B3A2C...", "kind": "status", "assertive": false, "text": "3 results" }
  ],
  "heard": [
    { "key": "r3-2", "region": { "regionId": 3, "frameId": "5B3A2C...", "kind": "status", "assertive": false, "text": "3 results" }, "gone": false, "agoMs": 840, "changes": 2, "replaced": "Searching..." }
  ],
  "unansweredFrames": 0,
  "layers": [],
  "layersOpened": [],
  "layersClosed": [],
  "layersReworded": []
}
```

### `Page.agentSettleArm`: arm a settle for a non-input action

Arms a settle for an action that is not input (a navigation, a script, a wait): call it just before acting, then `agentSettle` with its `armId`. Input actions arm their own (their `actionId`).

Parameters: none.

Returns:
- `armId`: integer. To pass to `agentSettle` or `agentReport`.

```json
{ "method": "Page.agentSettleArm" }
```

```json
{ "armId": 31 }
```

### `Page.agentSettle`: wait for the page to settle

Waits until the page has settled after an action (first until `until` is met, when given) and says what was still changing if it did not. The page counts as settled when, through the quiet window, what the agent reads stayed the same in every frame, no navigation was pending, no request the action caused (or one started after it) was running, and no finite animation with 1.5 s or less to run was running in view. A hidden page is brought to the front first (the report's `broughtForward`); a page frozen by `setWebLifecycleState` fails at once. Use it between an action and the next capture instead of a fixed sleep.

Parameters:
- `armId`: integer, optional. An Input action's `actionId`, or `agentSettleArm`'s `armId`; absent: armed now. One that is not the current action is an error.
- `until`: `Until`, optional. What to wait for first; any one of its conditions met meets it, and the page settles after it.
- `quietMs`: integer, optional. The quiet window in ms: default 150 (0 to 5000).
- `capMs`: integer, optional. The cap in ms: default 1500 (0 to 30000). A main-frame commit during the settle restarts the cap, once.
- `timeoutMs`: number, optional. How long `until` is waited for, from the call, in ms: default 10000, at most 60000.
- `report`: boolean, optional. Also return the action's report (`actionReport`), each frame's part read once it has settled; none once another action armed. A frame's part may take 400 ms past its settle: one later still counts as a frame that did not answer.
- `controls`: boolean, optional. With `report`, the report also carries the page's control census (`controls`).

Returns:
- `settle`: `SettleReport`.
- `untilSeen`: boolean, optional. Present when `until` was given: whether it was met.
- `untilAfterMs`: number, optional. From the action to when `until` was met, in ms.
- `actionReport`: `AgentActionReport`, optional. With `report`.

```json
{
  "method": "Page.agentSettle",
  "params": {
    "armId": 17,
    "until": { "text": "Order confirmed" },
    "quietMs": 200,
    "capMs": 3000,
    "report": true
  }
}
```

```json
{
  "settle": { "settled": true, "afterMs": 1320, "stillChanging": [], "shownChange": 14, "domChanged": true },
  "untilSeen": true,
  "untilAfterMs": 1180,
  "actionReport": {
    "documentId": "D-4",
    "armId": 17,
    "regions": [{ "regionId": 1, "frameId": "5B3A2C...", "kind": "status", "assertive": false, "text": "Order confirmed" }],
    "heard": [{ "key": "r1-1", "region": { "regionId": 1, "frameId": "5B3A2C...", "kind": "status", "assertive": false, "text": "Order confirmed" }, "gone": false, "agoMs": 140 }],
    "layers": [],
    "layersOpened": [],
    "layersClosed": [],
    "layersReworded": [],
    "navigated": true,
    "unansweredFrames": 0
  }
}
```

Example: wait for a selector to appear, in a given frame, without a prior action.

```json
{
  "method": "Page.agentSettle",
  "params": {
    "until": { "selector": "#results .row", "state": "visible", "frameId": "5B3A2C..." },
    "timeoutMs": 15000
  }
}
```

Example: a settle that did not finish.

```json
{
  "settle": {
    "settled": false,
    "afterMs": 1500,
    "stillChanging": [
      { "kind": "request", "what": "/api/search (changed)" },
      { "kind": "animation", "what": "div#spinner, 2.4 s left" }
    ],
    "shownChange": 0,
    "domChanged": true
  }
}
```

### `Page.agentReport`: the action's report

The action's report, read right after its Input reply: each frame's part read now (on its arm's pipe, after the arm), and a layer still animating (kept since the baseline or new, blank and blocking) read again after it, up to `layerExitMs`. Use it when you want what the action led to on the page (live regions, layers, the state of the elements it touched) without waiting for a settle; `agentSettle` with `report` gives the same report once the page has settled.

Parameters:
- `armId`: integer, required. The current action's `actionId`, or `agentSettleArm`'s `armId`; another, or one a later action replaced while it was read, is an error.
- `layerExitMs`: integer, optional. 0 to 1000 (default 0): how long such a layer may be waited for.
- `agentNodeIds`: array of integer, optional. Elements the action acted on, read with the report (its `nodes`): what they are and read now.

Returns:
- `report`: `AgentActionReport`.

```json
{
  "method": "Page.agentReport",
  "params": { "armId": 17, "layerExitMs": 300, "agentNodeIds": [42] }
}
```

### `Page.agentNavigateToHistoryEntry`: a history step that answers when landed

`navigateToHistoryEntry` answered once the step has landed: the entry has become the last committed one, in whichever frame and process the step committed (a frame's step is cloned from the page's entry, so `getNavigationHistory` cannot tell it apart). The entry already current answers `committed` at once, without navigating. Use it for back/forward steps you want to wait on, including steps that only an iframe commits.

Parameters:
- `entryId`: integer, required. Unique id of the entry to navigate to (from `Page.getNavigationHistory`).
- `timeoutMs`: number, optional. How long to wait for the step, in ms: default 10000, at most 60000.

Returns:
- `outcome`: enum. `committed`: the entry is the last committed one. `failed`: its navigation ended without committing. `replaced`: the page committed another entry, or a newer call came first. `timeout`: the wait ran out.
- `url`: string. The last committed entry's URL when it answered.

```json
{
  "method": "Page.agentNavigateToHistoryEntry",
  "params": { "entryId": 5, "timeoutMs": 8000 }
}
```

```json
{ "outcome": "committed", "url": "https://example.com/list" }
```

### `Page.startFrameStream`: frames into shared memory (Windows only)

Streams the page's frames, uncompressed, into shared memory for a viewer in another process on this machine. Unlike `startScreencast`, nothing is encoded or sent over the protocol per frame, and the capture itself is throttled to `maxFps` rather than only the delivery. Frames are captured only when the page changes. One stream per session; it ends with `stopFrameStream` or when the session detaches. **Windows only.**

The shared-memory section holds a 4096-byte header and three frame slots of 32-bit BGRA pixels, rows packed. Header, little-endian:

| Offset | Field | Type |
| --- | --- | --- |
| 0 | magic `"NFRM"` | uint32 (`0x4D52464E`) |
| 4 | version | uint32 |
| 8 | slot count | uint32 |
| 12 | header size | uint32 |
| 16 | slot size in bytes | uint64 |
| 24 | latest: `sequence << 2 \| slot` | uint64 |
| 32 + 32·i | per slot i: sequence (odd while being written) | uint64 |
| 40 + 32·i | width | uint32 |
| 44 + 32·i | height | uint32 |
| 48 + 32·i | stride | uint32 |
| 52 + 32·i | reserved | uint32 |
| 56 + 32·i | capture time, microseconds since the Unix epoch | int64 |

The event is signalled after each frame is published. A reader waits on the event, reads `latest`, checks that the slot's sequence is even and unchanged across its copy, and reads the slot's pixels.

Parameters:
- `maxWidth`: integer, required. Largest frame width wanted, in physical pixels. Frames are scaled down to fit, never up, and never beyond the page's size when the stream began.
- `maxHeight`: integer, required. Largest frame height wanted, in physical pixels.
- `maxFps`: integer, required. Most frames per second, 1 to 60.

Returns:
- `sharedMemoryName`: string. Name of the file mapping holding the frames.
- `frameEventName`: string. Name of the auto-reset event signalled after each frame.
- `sharedMemorySize`: integer. Size of the file mapping in bytes.
- `slotWidth`: integer. Largest frame width the slots can hold, in physical pixels.
- `slotHeight`: integer. Largest frame height the slots can hold, in physical pixels.

```json
{
  "method": "Page.startFrameStream",
  "params": { "maxWidth": 1280, "maxHeight": 720, "maxFps": 30 }
}
```

```json
{
  "sharedMemoryName": "Local\\nfrm-7f3a...",
  "frameEventName": "Local\\nfrm-7f3a...-frame",
  "sharedMemorySize": 11063296,
  "slotWidth": 1280,
  "slotHeight": 720
}
```

### `Page.updateFrameStream`: change a stream's limits

Changes a running frame stream's limits, as when its viewer is resized.

Parameters:
- `maxWidth`: integer, required.
- `maxHeight`: integer, required.
- `maxFps`: integer, required.

Returns: nothing.

```json
{
  "method": "Page.updateFrameStream",
  "params": { "maxWidth": 960, "maxHeight": 540, "maxFps": 15 }
}
```

### `Page.stopFrameStream`: stop the stream

Stops the frame stream and releases its shared memory.

Parameters: none. Returns: nothing.

```json
{ "method": "Page.stopFrameStream" }
```

### Page domain types

#### Snapshot geometry and elements

##### `Page.AgentSnapshotViewport`

Viewport and scroll geometry captured with an agent snapshot. All values are in the root frame's CSS-pixel space; `screenshotScale` converts to the pixels of the returned screenshot.

- `width`: integer. Layout viewport width in CSS pixels.
- `height`: integer. Layout viewport height in CSS pixels.
- `deviceScaleFactor`: number. Device pixel ratio (CSS px to device px).
- `scrollX`: number. Horizontal scroll offset in CSS pixels.
- `scrollY`: number. Vertical scroll offset in CSS pixels.
- `scrollWidth`: number. Full scrollable content width in CSS pixels.
- `scrollHeight`: number. Full scrollable content height in CSS pixels.
- `screenshotScale`: number, optional. Image pixels per CSS pixel of the returned screenshot; present with a screenshot.

##### `Page.AgentSnapshotElement`

One interactive element, gathered across all frames (cross-origin OOPIFs and open or closed shadow DOM included). Geometry is composed into the root viewport's CSS-pixel space, so annotations land where the user sees the element.

- `backendNodeId`: `DOM.BackendNodeId`. Stable CDP identity of the element (in its own renderer).
- `agentNodeId`: integer. Browser-minted handle, stable for the element's life in its document and never reused by another element of any document; used with `resolveAgentNode`, `agentHitCheck` and `agentNodesAlive`.
- `frameId`: `FrameId`. Id of the frame that owns this element.
- `role`: string. Computed accessibility role, or the tag-derived role when no ARIA role.
- `name`: string, optional. Accessible name.
- `value`: string, optional. Current value (form controls), if any. A password input reports one bullet per character instead of its contents.
- `description`: string, optional. Accessible description, if any.
- `tag`: string. Lowercased tag name (e.g. `div`, `button`, `input`).
- `interactive`: boolean. Whether the element is considered interactive/actionable.
- `interactiveReason`: string, optional. Why it was classified interactive: `role`, `form-control`, `drag`, `listener`, `cursor` or `tabindex`.
- `states`: array of string. Active state flags: `visible`, `enabled`, `focusable`, `focused`, `editable`, `checked`, `expanded`, `selected`, `disabled`, `readonly`, `required`, `draggable` (something to pick up), `drop-target` (somewhere to let go), `secret` (a card field, its value bullets), `invalid` (with `invalid` below). `disabled`, `checked`, `readonly` and `required` also come from their aria attributes.
- `x`, `y`: number. Border-box X and Y in the root viewport's CSS-pixel space (viewport-relative).
- `width`, `height`: number. Border-box size in CSS pixels.
- `inViewport`: boolean. Whether the border box intersects the root viewport.
- `obscured`: boolean. True when a cross-context hit test at the element's action point lands on other content in any frame, so the element cannot be clicked.
- `shadowHostBackendNodeId`: `DOM.BackendNodeId`, optional. The shadow host's backend node id when this element lives inside a shadow tree.
- `label`: string, optional. Short handle drawn on the screenshot when marked (e.g. `a1`): the agent's id for the element, the same for its whole life in the document, in view or not. Every listed element has one.
- `marked`: boolean. Whether the element is marked (in the viewport, interactive and not obscured), so its label is drawn and it can be acted on now.
- `color`: string, optional. Name of the colour of this element's outline and badge (e.g. `red`). Present only for marked elements; neighbouring marks get colours as far apart as possible so a label binds unambiguously to its box.
- `href`: string, optional. Where this element points, resolved against the document base URL, for `<a>`, `<area>`, `<link>`. Absent when the element has no such attribute.
- `src`: string, optional. The same for `<img>`, `<iframe>`, `<video>`, `<audio>`, `<source>`, `<embed>`, `<script>`.
- `coveredBy`: string, optional. When obscured: what lies over it where a press would land, said with where it is ("the page's div#ov" over an element in a frame, "div#panel in another frame"), or only where when it could not be named; empty when it was not asked. On a marked element: what its own process lays over every part of it a press could reach (its own document's content, or the page's over a same-process frame); it keeps its label, and a press on it is refused. A cover in an open layer the element is not in is named by that layer (`listbox "City"`), as is one on that layer's veil, the backdrop beside its box (`dialog "Choose a plan"`).
- `layer`: integer, optional. Scope `on` or `all`: the innermost entry of `layers` holding it.
- `underLayer`: integer, optional. Scope `on` or `all`, with `coveredBy`: the index in `layers` of the innermost layer holding what lies over it (the cover, or that layer's veil), its own layer included; for the content of a frame in no layer of its own, the layer holding that frame. Absent when none does.
- `invalid`: array of string, optional. Why the page or its own constraints call it invalid: `aria`, `valueMissing`, `typeMismatch`, `patternMismatch`, `tooLong`, `tooShort`, `rangeUnderflow`, `rangeOverflow`, `stepMismatch`, `badInput`, `customError`, `messageShown` (the browser's own warning shows for it). A constraint counts once the field was edited or its form's submit tried, or while it holds a value; `aria-invalid` always. Absent when valid.
- `error`: string, optional. With `invalid`, the page's words for what is wrong: the shown text of its `aria-errormessage` targets, else its custom validity message; 160 characters. Never for a password or card field.
- `reads`: string, optional. What it reads as `agentNodesAlive` reads it (aria-label, labelled-by and label texts, title, placeholder, text), for a later id check to compare like with like. Absent when empty.

##### `Page.AgentSnapshotScroller`

The page's main scroller: the box a scroll of the page means now. It is the page's own window when its document scrolls 16 px or 2% of the viewport height or more; else, of the boxes a user can scroll with room to and the windows of frames whose documents scroll as far, each showing 20 x 20 CSS px or more and open to a hit test, the one that shows the most of itself (a document that scrolls a pixel or two is passed over, so the pane in it reads). With layers (scope `on` or `all`) and a blocking layer open, only what that layer holds. Frames of other processes are judged too.

- `positionX`, `positionY`: number. Where it is along each axis, in CSS px of the scroller: its offset less its minimum, so counted from its visual top-left and growing down and right. A reversed pane (a chat laid out bottom up) that opens at its visual bottom reads `positionY = maxY`.
- `maxX`, `maxY`: number. As far as a user can scroll it along each axis, in CSS px of the scroller; 0 where its overflow is hidden or clip that way.
- `lengthX`, `lengthY`: number. How much of its content shows along each axis, in CSS px of the scroller: `lengthY` is how tall it shows.
- `x`, `y`, `width`, `height`: number. What shows of it, in the root viewport's CSS-pixel space (viewport-relative), as the elements' boxes.
- `name`: string, optional. Its name in the listing when it is listed and named there (a frame's window: its listed frame element's); else, for an element, its aria-label, its first aria-labelledby target's text or its title; else named as covers are (`tag#id` or `tag.class`, then its text when short), a frame's window by its frame element. Absent for the page's own window.
- `role`: string, optional. The listed element's role when it is listed; else the first word of its role attribute, lower-cased, else its tag. Absent for a window whose frame element is not listed.
- `isPage`: boolean. The page's own window: `viewport`'s `scrollX`, `scrollY`, `scrollWidth` and `scrollHeight` say the same.
- `wheelReaches`: boolean. A wheel turned at the middle of what shows would scroll it: false under a veil, a fixed bar or a scroller inside it. Judged in its own process, and by whether the page shows its frame there: what another process lays over it is not seen.
- `layer`: integer, optional. With layers: the innermost entry of `layers` holding it, else the one holding its frame.
- `underLayer`: integer, optional. With layers and `wheelReaches` false: the entry of `layers` over its middle, above `layer` (a list open over the pane), when its own process can tell; absent otherwise.
- `agentNodeId`: integer, optional. A listed element's own; one minted for an element not listed (placement `scroller`); a listed frame element's for a frame's window. Absent for the page's own window, and for a window whose frame element is not listed.
- `label`: string, optional. Its label, under the same rule.

#### Layers

##### `Page.AgentLayer`

A layer open on the page (a modal, a drawer, a menu, a popover) in `captureAgentSnapshot`'s `layers` and an action's report, bottom to top.

- `kind`: string. `dialog`, `alert`, `menu`, `listbox`, `popover`, `fullscreen`, `picker` or `panel`.
- `name`: string. Its author's name (not one that only names the kind), else its `<h1>`, else its title heading, else its text: 60 characters at most.
- `head`: string. Its text, about 600 characters at most; never a field's value.
- `how`: string. How it was found: `top-layer`, `probe`, `veil`, `inert` or `aria`.
- `blocking`: boolean. Whether it shuts off the page behind it: a click there cannot reach the page.
- `nodeId`: integer. Its root's `DOMNodeId` in its frame's process: with `frameId`, what it is while the node lives.
- `frameId`: `FrameId`. The frame whose document holds it.
- `elementCount`: integer, optional. `captureAgentSnapshot` only: listed elements in it (for an entry of the page's own frame, with what the frames it holds list).
- `behindCount`: integer, optional. `captureAgentSnapshot` only: elements left out behind it that a scope `all` listing would list (controls, and what is off-screen).
- `animatingMs`: integer, optional. The longest time left, in ms, of an animation or transition running on it, on what holds it, on its veil or on a large part of it: it may be opening or closing. Absent when none.

##### `Page.AgentHiddenGroup`

Elements `captureAgentSnapshot` left out, with scope `on`, because a click cannot reach them, by what they are behind.

- `behind`: string. The layer's name, or what covers them as `coveredBy` says it.
- `layer`: integer, optional. The index in `layers` when they are behind a layer.
- `inView`: integer. How many were in view, of those a scope `all` listing would list (controls in view, and what is off-screen). Text in view behind it is left out too, uncounted; a group of only such text is not given.
- `offscreen`: integer. How many were off-screen.

##### `Page.AgentLayerRef`

A layer named by its key, as listed.

- `kind`: string.
- `name`: string.
- `frameId`: `FrameId`.
- `nodeId`: integer.

##### `Page.AgentLayerReworded`

A layer kept since the baseline whose head changed.

- `index`: integer. Into the report's, or `agentAnnouncements`', `layers`.
- `headBefore`: string.

#### Live regions

##### `Page.AgentLiveRegion`

A live region (`aria-live`, role `alert`/`status`/`log`, `<output>`).

- `regionId`: integer. Browser-minted, stable for the region's life in its document.
- `frameId`: `FrameId`.
- `kind`: enum. `alert`, `status`, `log`, `output` or `live`.
- `assertive`: boolean.
- `text`: string. 300 characters of its text: the last for `log`, else the first; never a field's value.

##### `Page.AgentHeard`

What a region said since the last action, toasts included.

- `key`: string. Stable across reads of the same entry; unique across the documents of its frame.
- `region`: `AgentLiveRegion`.
- `gone`: boolean. That text is no longer shown at this read.
- `beforeAction`: boolean, optional. Heard before the latest action armed the watch (a press, key, wheel, select, drop or `agentSettleArm`), while an earlier watch still looked and in the 30 s before, and carried on into its record; a read may have returned it already, under the same key. Absent when heard during it.
- `unwatched`: boolean, optional. Recorded by a read's closing pass while no watch looked (between calls), not by the watch; or by the browser's read of the regions alone between calls, after the page's frames.
- `own`: boolean, optional. Heard while no action's own span was open: the page said it by itself (a clock, a carousel, a status it changed later). An action's span runs from its arm (a press, key, wheel, select, drop or `agentSettleArm`) until its report (`agentReport`, after any layer it waits out, or the settle's) read the page, or 30 s when none does. Absent when heard in one.
- `agoMs`: integer. How long before this read it was heard, in ms (for one a read's closing pass recorded: when that pass found it).
- `changes`: integer, optional. How many changes of its region it stands for (absent: 1). A region keeps 3 entries an arm while a watch looks and 1 between calls; past that its newest change takes the place of its latest entry, under a new key, and adds to its count: a clock between calls is one entry, its newest tick, standing for every tick heard.
- `replaced`: string, optional. With `changes`, the text of the entry it took the place of, as `region.text` reads (never a field's value): a clock's last tick but one, or the "Searching..." before "3 results".
- `added`: string, optional. For a `log`, the text its change added (what came after where its text ended, or before where it began for a log that adds at the top) and, with `changes`, what they all added one way; 300 characters from its start, cut at a word and marked "...". Absent when none could be told: rewritten, removed, a change too large to place, a log first seen since the last action (what it held was not seen added), or one past the 32 logs kept for its local root.

#### Deltas

##### `Page.AgentSnapshotDelta`

What changed since the listing named by `captureAgentSnapshot`'s `since`.

- `unchanged`: boolean.
- `added`: array of `AgentDeltaAdded`.
- `removed`: array of `AgentDeltaRemoved`.
- `changed`: array of `AgentDeltaChanged`.
- `reordered`: array of integer. `agentNodeId`s whose order changed.
- `focus`: `AgentDeltaFocus`, optional. Present only when it changed.
- `url`: string, optional. Present only when it changed.
- `title`: string, optional. Present only when it changed.
- `scroll`: `AgentDeltaScroll`, optional. Present only when it changed.
- `layersOpened`: array of integer. Indices into `layers` of entries not open in the baseline.
- `layersClosed`: array of `AgentLayerRef`.
- `announcements`: array of `AgentLiveRegion`.
- `partial`: boolean. A local root gave no answer; its elements are as in the baseline.

##### `Page.AgentDeltaAdded`

- `agentNodeId`: integer.
- `why`: enum. `new`, `shown`, `into_view`, `uncovered` or `appended`. `appended` is what the page added since the document's first listing and left out off-screen until it came into view (`offscreenMode` `none`, or `summary` for one that said nothing). `new` is also given to an element left out off-screen and never listed that is now listed off-screen (named, or made a control) and was on the page at the document's first listing; one a listing showed before is `shown`.

##### `Page.AgentDeltaRemoved`

- `agentNodeId`: integer.
- `label`: string.
- `role`: string.
- `name`: string, optional.
- `why`: enum. `gone`, `hidden`, `out_of_view` or `covered`.
- `wasInView`: boolean.
- `baselineIndex`: integer. Its index in the baseline's `elements`; -1 when not known (carried from a frame that did not answer).
- `behindLayer`: integer, optional. `covered`: the hiding layer's index in the current `layers`.
- `coveredBy`: string, optional. `covered`: what covers it, as `coveredBy` says it, when it is not a layer.

##### `Page.AgentDeltaChanged`

- `agentNodeId`: integer.
- `what`: enum. `name`, `value`, `state`, `role`, `description`, `href`, `error` or `coveredBy`. `error`: the page's words for what is wrong changed while the element stayed invalid. `coveredBy`: what lies over it changed while it kept its place in view or covered (a marked element's mark, unless a click scrolls it out from under; a covered one's cover once named), as `coveredBy` says it; `from` or `to` absent on the side with none.
- `from`, `to`: string, optional.
- `fromStates`, `toStates`: array of string, optional. For `state`.

##### `Page.AgentDeltaFocus`

- `agentNodeId`: integer, optional. Absent: focus left every listed element.
- `label`: string, optional.

##### `Page.AgentDeltaScroll`

The record comes when the document's offsets, the main scroller or its place changed.

- `x`, `y`: integer. The document's scroll, in whole CSS px.
- `agentNodeId`: integer, optional. The main scroller's, as `captureAgentSnapshot`'s `scroller` has it; absent for the page's own window and for a scroller with none.
- `label`: string, optional. The same for its label.

#### Redaction (held captures)

##### `Page.AgentRedaction`

A held capture's text, frame by frame.

- `captureId`: string. For `agentFinishCapture`.
- `frames`: array of `AgentRedactionFrame`.

##### `Page.AgentRedactionFrame`

One document of a frozen frame: its runs in paint order and its text fields. Runs never join across frames. Only the runs a secret could show in are given (they show, something may move them, or their field shows or may move), each with its neighbours up to 65,536 letters and digits each way, cut to those nearest it; runs far apart on the page may follow each other here.

- `runs`: array of `AgentRedactionRun`.
- `fields`: array of `AgentRedactionField`.

##### `Page.AgentRedactionRun`

One painted text run of a frozen frame: one line of one text node, as drawn (password bullets stay bullets; a card field's runs are never given).

- `text`: string.
- `inView`: boolean.

##### `Page.AgentRedactionField`

A text field of a frozen frame, by its runs: `runs[firstRun, endRun)`. One that neither shows nor may move may come with only some of its runs, or none.

- `firstRun`: integer.
- `endRun`: integer.

##### `Page.AgentFinishFrame`

`agentFinishCapture`'s answer for one redaction frame, by index: the runs that show part of a secret, and the fields that hold one.

- `runs`: array of integer. Indices into the frame's `runs`.
- `fields`: array of integer. Indices into the frame's `fields`.

#### Node life and controls

##### `Page.AgentNodeLife`

One answer of `agentNodesAlive`, and one entry of a report's `nodes`.

- `agentNodeId`: integer, optional.
- `label`: string, optional.
- `state`: enum. `alive`: its renderer confirmed it. `gone`: the page no longer holds the id (the node was collected or detached, or the id was dropped past the id space's cap and is not among the newest 10 000 so dropped). `elsewhere`: the page never held the id or label. `unknown`: not confirmed yet, or dropped past the cap and among the newest 10 000 so dropped.
- `role`: string, optional.
- `name`: string, optional.
- `placement`: enum, optional. `view` and `offscreen`: where it is laid out. `dropped`: left out of the listing as off-screen, its id kept so it can come into view. `covered` and `behind`: hidden by another element or by a layer. `unlisted`: connected but not listed. `gone`. `scroller`: the box an action scrolled, listed for that alone.
- `behind`: `AgentLayerRef`, optional. Placement `behind`: the layer that hides it; absent when what hides it is not a layer.
- `rendered`: boolean, optional.
- `reads`: string, optional. What it reads, as on `AgentSnapshotElement`.
- `invalid`: array of string, optional. For an alive node, as on `AgentSnapshotElement`.
- `error`: string, optional. As on `AgentSnapshotElement`.
- `behindOpen`: boolean, optional. With `agentNodesAlive`'s `layers`, for placement `behind`: whether the layer it is behind is open now; absent when its frame was not read.
- `checked`: string, optional. For an alive node, a checkbox or radio input's state (`"true"`, `"false"` or `"mixed"`), else its `aria-checked`; absent when it has none.

##### `Page.AgentControl`

One control of the page in a report's census (`agentSettle`'s `controls`): a field or a button, rendered, with a box and visibility visible, wherever the page has scrolled. A section the page skips while it is off-screen (`content-visibility: auto`) lists what it held when last drawn: none when never drawn. Never its value.

- `backendNodeId`: `DOM.BackendNodeId`. Its node, in the renderer of its frame's local root.
- `localRootFrameId`: `FrameId`. The local root's frame (its devtools frame token), as `Page.resolveAgentNode`'s `localRootFrameId` names it; the control's own frame is not reported here.
- `frameId`: `FrameId`, **deprecated**. The same as `localRootFrameId`, under the name `AgentSnapshotElement` uses for an element's own frame. To be removed in a later release.
- `x`, `y`, `width`, `height`: number. Its box, CSS px, in its local root's coordinates: the page's viewport for a control of the page's own process; stale for one in a section skipped off-screen.
- `kind`: string. `field` or `button`. Links are not controls here, nor an element with role `listbox` (the list a field opens); a `<select>` list box is one.
- `role`: string. `textbox`, `searchbox`, `combobox`, `checkbox`, `radio`, `switch`, `slider`, `spinbutton` or `button`, by its role attribute first; a select as `combobox` or `listbox`; an input with a format of its own by its type (`date`, `time`, `datetime-local`, `month`, `week`, `color`, `file`).
- `label`: string. The first that says something of: a label naming it with `for`, a label holding it, its aria-labelledby targets' text, aria-label, placeholder, title; a button's own text or value; its name attribute. 80 characters; empty for none. Page text, by a DOM rule that can differ from the accessible name.
- `disabled`, `readonly`, `required`, `checked`: boolean, optional.
- `secret`: boolean, optional. A card number or security code field (an agent snapshot's state `secret`).
- `layer`: integer, optional. The index in the report's `layers` of the innermost one holding it: its own frame's, else the page's layer holding its frame. Absent when none does.
- `invalid`: array of string, optional. A field's, as on `AgentSnapshotElement`.
- `error`: string, optional.

#### Reports

##### `Page.AgentActionReport`

What an action led to on the page besides its outcome, judged by the browser from the action's arm: the regions now and what they said, and the layers against the stack the document last read.

- `documentId`: string.
- `armId`: integer. The arm it is judged from: an Input `actionId` or `agentSettleArm`'s `armId`.
- `regions`: array of `AgentLiveRegion`. The regions with text now, as `agentAnnouncements` reads them.
- `heard`: array of `AgentHeard`. What they said since that arm, with what the arm carried on.
- `layers`: array of `AgentLayer`. The layers open now, bottom to top.
- `layersOpened`: array of integer. Indices into `layers` not in the baseline stack; every one when this document had no stack read before.
- `layersClosed`: array of `AgentLayer`. In the baseline stack and not open now, as they were read then.
- `layersReworded`: array of `AgentLayerReworded`. Kept since the baseline, its head changed.
- `baselineAgeMs`: number, optional. When the baseline stack was read, in ms before the arm (negative: after it); absent when this document had no stack read before: then every layer open now is opened, and nothing is closed or reworded.
- `navigated`: boolean, optional. The main frame committed a new document since the arm: nothing else read of the page is reported.
- `printAtMs`: number, optional. A frame of the page asked to print since the arm: ms from the arm to the first ask, after a navigation too. The page waits in `print()` until the print ends, and its frame may give no part.
- `unansweredFrames`: integer. Local roots that gave no part.
- `nodes`: array of `AgentNodeLife`, optional. With `agentReport`'s `agentNodeIds`: one per id, in order, as `agentNodesAlive` answers it; absent after a navigation.
- `controls`: array of `AgentControl`, optional. With `agentSettle`'s `controls`, the page's control census: every local root's controls, frame by frame, in tree order within each. Absent after a navigation, and when no local root gave one.
- `controlsCut`: array of string, optional. With `controls`, the local roots (frame tokens) whose census is short: it stopped (past 400 controls, its walk's budget or its time), or the frame gave none in time. A control of such a frame missing from `controls` may still be there.

#### Action outcomes

##### `Page.ActionOutcome`

What an input action led to, within its answer. Returned by `Input.moveTo`, `dispatchMousePath`, `dispatchKeystrokes`, `dispatchKeyChord`, `dispatchPaste`, `performDrag`, `scrollBy`, `selectOptions`, `fillDateTime`, `pickColor` and `chooseFiles`.

- `actionId`: integer. The browser's id for the action; late events (`Input.actionOutcome`) echo it. It also names the action's arm for `Page.agentSettle` and `Page.agentReport`.
- `handled`: boolean. The renderer answered for the action's last event before the cap.
- `waitedMs`: number. From the dispatch to this answer.
- `events`: array of `ActionEvent`. In the order seen; empty: nothing started.

##### `Page.ActionEvent`

One thing an input action led to.

- `kind`: string. `navigation`, `newTab`, `popupBlocked` or `print` (a frame asked to print; the page waits in `print()` until the print ends). Open: more kinds may follow.
- `atMs`: number. Ms from the action's dispatch (its press, first key, pick or drop) to when this was seen (a navigation: when it reached its state); negative: before it.
- `state`: string, optional. `navigation`: `started`, `committed` or `failed` (a download is `failed` with `isDownload`).
- `url`: string, optional. `navigation`: the URL (`committed`: the final one). `newTab`, `popupBlocked`: the URL asked for.
- `sameDocument`: boolean, optional.
- `mainFrame`: boolean, optional.
- `startedBeforeAction`: boolean, optional. The navigation was already under way when the action was dispatched.
- `frameId`: string, optional. The frame navigated, or (`print`) asked (its devtools frame token).
- `errorText`: string, optional. `failed`: e.g. `ERR_ABORTED`, `ERR_NAME_NOT_RESOLVED`.
- `isDownload`: boolean, optional.
- `title`: string, optional. Only when the browser has one at report time.
- `targetId`: string, optional. `newTab`: its target id.
- `disposition`: string, optional. `newTab`, `popupBlocked`: `newForegroundTab`, `newBackgroundTab`, `newPopup` or `newWindow`, as asked.

#### Settling

##### `Page.SettleReport`

Has the page finished reacting to the action? Settled when, through the quiet window, what the agent reads stayed the same in every frame, no navigation was pending, no request the action caused (or one started after it) was running, and no finite animation with 1.5 s or less to run was running in view.

- `settled`: boolean.
- `afterMs`: number. Settled: from the action to the last change seen, request end, commit or end of a waited-for animation, in ms (0: none), never before `until` was met. Not settled: from the action to when the browser stopped waiting.
- `stillChanging`: array of `SettleChange`. At most 5, named. A settled report may name what never blocks: an animation with more than 1.5 s left, a request running over 2 s.
- `renderingPaused`: boolean, optional. The page drew no frames while its rendering waited for one: never settled.
- `navigated`: boolean, optional. The main frame committed a new document since the action; the settle ran on it, the cap from its commit.
- `broughtForward`: boolean, optional. The page was hidden, and was brought to the front for the settle; absent when it was not.
- `shownChange`: integer, optional. The elements shown now less at the action's arm (rendered, visibility visible, no opacity 0 on them or above them), summed over the page's local roots; absent when one that answered could not count both (past its walk's 50,000-node budget, or over other frames than at the arm). Every settle carries it.
- `domChanged`: boolean, optional. The DOM or the focus moved in some frame since the arm.

##### `Page.SettleChange`

One thing still changing (or, never blocking, still running) when `agentSettle` answered.

- `kind`: string. `request`, `request-ended`, `animation`, `mutation`, `navigation` or `lifecycle`. Open: more kinds may follow.
- `what`: string. A request's path without its query (with its host when not the document's); an element the latest `captureAgentSnapshot` listed, by its label and name (`a12 "Save"`), any other as `tag#id.class`, with `(new)`, `(changed)` or `(gone)`; an animation with its target and the time it has left; a pending navigation; a frame that did not answer.
- `meanwhile`: boolean, optional. A request not tied to the action: started after it, from no interaction.
- `unanswered`: boolean, optional. A frame that gave no reading in time (its renderer busy with a long script or the page held in `print()`, or gone), not a change seen on the page (kind `lifecycle`).

##### `Page.Until`

What `agentSettle` waits for first; any one met meets it, and the page settles after it.

- `text`: string, optional. A case-insensitive, space-collapsed substring of the rendered text, or of an interactive element's aria-label, title, alt or placeholder, in any frame.
- `selector`: string, optional. A CSS selector whose first match in some checked document (every frame's, or `frameId`'s) is as `state` says (`visible` by default); one that does not parse is an error.
- `xpath`: string, optional. An XPath expression in place of `selector` (not both), the same way: the first node it selects, in document order (a text or attribute node is attached, never more); one that does not parse, or returns no node-set (a number, a string or a boolean), is an error. It is evaluated whole at each check (every 100 to 300 ms): keep it narrow on a large page.
- `state`: enum, optional. What `selector` or `xpath` waits for, on the first match: `attached` (it exists), `box` (a box of positive size), `visible` (a box, visibility visible and its own opacity above 0), or `hidden` (no match, or the first is not visible), the last only with `frameId`. A frame not drawn or throttled is checked only for `attached`, and for `hidden` by no match or its frame element not rendered.
- `frameId`: string, optional. A frame of this page: only its document is checked for `selector` or `xpath`. Absent: every frame. One not of this page is an error.
- `appeared`: boolean, optional. Met once a local root shows more elements than at the action's arm (`shownChange`'s count), counted since this call: what a hover makes appear, a hover-intent menu's delay included.
- `goneAgentNodeId`: integer, optional. An `agentNodeId` of this document: met once that element is detached, not rendered or `display: none`; at once when it is gone already.
- `urlChanged`: boolean, optional. The main frame's URL differs from the one at the action.
- `urlContains`: string, optional. The main frame's URL contains this.
- `newTab`: boolean, optional. The page opened a tab or window since the action.

---

## Switches the custom methods depend on

The methods above are available whenever the browser runs; the switches below change what some of them can do or when their events fire. The first group is required for a method to work at all; the second shapes the behaviour the methods describe.

| Switch | What it gates |
| --- | --- |
| `--private-clipboard` | **Required by `Input.dispatchPaste`**, which is refused without it. Presence-only: the browser keeps its own in-memory clipboard instead of the operating system's, so copy, cut and paste (keyboard shortcuts, `execCommand` and the async Clipboard API alike) work within this browser process and never read or overwrite the clipboard of the person at the machine, nor that of any other browser running beside it. The same platform-independent clipboard headless mode always uses. |
| `--dismiss-permission-prompts` | **Required for `Input.permissionPromptDismissed`** to ever fire. Presence-only: permission requests are queued and shown as usual, except that the prompt is never drawn; after a random 1-5 s, the time a person takes to read a prompt and close it, it is dismissed, and the event is sent. No decision is stored for the site; as after a person's dismissals, three of them put it under the 7-day embargo. A request from a background tab waits for the tab to be shown, as the prompt itself would. Also covers File System Access prompts. (The stock `--deny-permission-prompts` denies in the same call and persists the block, as headless mode does; it does not produce the event.) |
| `--movement-persona-seed` | The seed of the pointer's human-movement persona (one browser, one hand); an int64. It is the persona `Input.moveTo`, `revealElement`, `scrollBy`, `performDrag`, `selectOptions`, `fillDateTime`, `pickColor` and `chooseFiles` move with, and the default `seed` of `Input.probeMovementPersona`. Absent: in the release binary, derived from `--fingerprint-seed` when that is given; otherwise a random seed for each browser run. |
| `--fingerprint-seed` | **Release binary only.** The master seed of the fingerprint identity, driving every per-switch `auto` / absent-value derivation, the movement persona's seed included when `--movement-persona-seed` is absent. Accepts `auto` or a 32-bit signed integer, and can be saved at `chrome://browser-settings`. `Browser.getFingerprint` reports it under `seed`, and every other fingerprint switch (`--fingerprint-*`, `--canvas-*-noise`, `--webgl-shader-noise`, `--webrtc-ip4/6`, `--browser-font-bundle`, ...) under `switches`. |
| `--cancel-print-preview` | Shapes the `print` outcome several replies carry (`Page.ActionEvent` kind `print`, `AgentActionReport.printAtMs`, `SettleChange.unanswered`): a page's `window.print()` runs the scripted-print flow with no preview opening, and after a random 1-4 s the preview is closed as its Cancel would close it, so `print()` returns and the frame can answer again. Without it the page waits in `print()` until the preview is dealt with. Presence-only; `Page.printToPDF` is unaffected. |
| `--show-cdp-cursor` | Presence-only. Draws a cursor overlay while a DevTools client is attached, which makes the paths `Input.moveTo`, `dispatchMousePath`, `performDrag` and the other pointer commands take visible on screen. Not required by any method. |
| Local file access of the client | Not a switch, but a gate: `Input.chooseFiles` is refused when the DevTools client lacks local file access, as `DOM.setFileInputFiles` is. |
| Windows | `Page.startFrameStream`, `Page.updateFrameStream` and `Page.stopFrameStream` exist on Windows only. |
| Browser target | `Browser.agentFetch`, `agentFetchCancel`, `getFingerprint`, `startRecording`, `stopRecording`, `recordingMask` and `recordingStatus` answer "method not found" on any session that is not the browser target's. |
