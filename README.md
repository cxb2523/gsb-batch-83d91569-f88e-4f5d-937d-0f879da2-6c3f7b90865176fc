# Chromaphore Browser — Chromium for AI agents
[![Discord](https://img.shields.io/discord/1499516872758923264?logo=discord&label=Discord)](https://discord.gg/EdRx3832Hw)

**Support:** [Discussions](https://github.com/nodriver-project/Chromaphore-Browser/discussions) · [Releases](https://github.com/nodriver-project/Chromaphore-Browser/releases)

A Chromium build for AI browser agents, with a fingerprint identity you control.

For agents, it carries out whole actions inside the browser with human timing (a click, a drag, typing, picking an option or a date), sees a page in one call, keeps element handles that work across frames and survive re-reads, waits for a page to settle, reads URLs without opening a tab, and records everything the browser loads. All of it is driven over the Chrome DevTools Protocol, from any CDP client.

For identity, it reports itself to sites as Google Chrome, answers in headless mode as a headed window on the same machine would, and can present a different machine altogether (GPU, canvas, audio, fonts, screen, hardware, time zone), random for each launch or reproducible from a seed. The spoofing happens inside the browser, not through injected JavaScript, so there is no `Object.defineProperty` wrapper for a page to detect.

**Windows only.** Download the binary from the [Releases page](../../releases); the agent features can also be built from the patches in [`patches/`](patches) (see [Source and binary](#source-and-binary)).

**On a Mac?** There's no macOS build yet. Star or watch this repo (**Watch → Custom → Releases**) to hear when one comes out.

---

## Contents

- [Download](#download)
- [What's in it](#whats-in-it)
- [Automation: custom CDP methods](#automation-custom-cdp-methods)
- [Fingerprint identity](#fingerprint-identity)
- [Answers like Google Chrome](#answers-like-google-chrome)
- [Headless](#headless)
- [Privacy defaults](#privacy-defaults)
- [Built-in extras](#built-in-extras)
- [Command-line switches](#command-line-switches)
- [Install](#install)
- [Source and binary](#source-and-binary)
- [Building from source](#building-from-source)
- [Intended use](#intended-use)
- [License](#license)

---

## Download

Grab the latest build from the [Releases page](../../releases):

| File | Description |
|---|---|
| `Chromaphore-<release>-chromium<chromium>-windows-x64-setup.exe` | Installer with Windows integration |
| `Chromaphore-<release>-chromium<chromium>-windows-x64-portable.zip` | Portable, no installation |
| `register-browser.ps1` | Registers the portable copy with Windows as a browser (optional) |

Each release carries two versions: Chromaphore's own and the Chromium it is built on, as in `Chromaphore-1.0.0-chromium156.0.8078.47-windows-x64-portable.zip`. Chromaphore's major version goes up only when a release breaks something people rely on: a custom DevTools command or field removed without an alias, or a fingerprint seed that no longer gives the same identity. Releases up to Chromium 153 used the earlier names and are kept as they were. The SHA-256 of each file is in its release notes.

The release notes also link a VirusTotal scan of the browser's own files (`chrome.exe`, `chrome.dll`, `chrome_elf.dll`), and [Install](#install) says what to do if Windows SmartScreen warns.

## What's in it

- **Actions done whole, with human timing.** Pointer moves planned like a hand's, clicks, wheel scrolls, drags (native and pointer-based), typing with realistic key timing, key chords, paste, and form controls (`<select>`, date and time fields, colour pickers, file choosers), each one command that answers when the action has ended and says what it led to (navigations, new tabs, blocked popups).
- **Page perception in one call.** `Page.captureAgentSnapshot` lists the interactive elements across every frame, cross-origin ones included, with their boxes, names and roles, the open layers (dialogs, menus, listboxes), what changed since the last look, live-region announcements, and optionally a marked screenshot with secrets blacked out.
- **Handles that last.** Each listed element gets an id that stays valid for its life in the document and works across frames; the browser re-locates it, checks whether a press would reach it, and says when it is gone.
- **Waiting that knows the page.** `Page.agentSettle` waits until the page has finished reacting to an action (requests, animations, DOM changes, navigations), or for a selector, text or URL.
- **Reading without a tab.** `Browser.agentFetch` reads a URL in a page that is never shown, renders and settles HTML and returns it as Markdown with its outline, links and metadata, or makes a real `fetch()` from the site's origin for an API call.
- **Recording.** `Browser.startRecording` writes every request, response, body and websocket frame the browser carries, from every process, into a HAR and an index, optionally with every script the pages compiled, with secrets you name masked.
- **A fingerprint identity.** Off by default; one switch or one setting gives the browser a coherent machine of its own (see [Fingerprint identity](#fingerprint-identity)).

## Automation: custom CDP methods

The browser adds 33 commands and 3 events to the Chrome DevTools Protocol, in the Browser, Input and Page domains. They are listed in the protocol JSON at `http://127.0.0.1:<port>/json/protocol` and callable from any CDP client (Puppeteer or Playwright through `CDPSession.send(...)`, Selenium's CDP bridge, a CDP wrapper library, a raw WebSocket). Every one of them is documented, with parameters, returns and examples, in **[`CDP.md`](CDP.md)**. In short:

| Domain | What it adds |
|---|---|
| `Browser` | `agentFetch` / `agentFetchCancel` (read a URL in a page that is never shown, HTML extracted as Markdown), `startRecording` / `stopRecording` / `recordingMask` / `recordingStatus` (a HAR with bodies, sockets and compiled scripts, with secrets masked), event `recordingEnded`, and `getFingerprint` (the identity the browser presents, read without touching any page) |
| `Input` | `moveTo`, `revealElement`, `scrollBy`, `performDrag`, `dispatchMousePath`, `dispatchKeystrokes`, `dispatchKeyChord`, `dispatchPaste`, `selectOptions`, `fillDateTime`, `pickColor`, `chooseFiles`, `probeMovementPersona`, and a `carry` mode for the stock `setInterceptDrags`; events `actionOutcome`, `permissionPromptDismissed` |
| `Page` | `captureAgentSnapshot` / `agentFinishCapture` (one-call perception with layers, deltas, live regions and secret redaction), `resolveAgentNode`, `agentHitCheck`, `agentNodesAlive`, `agentAnnouncements`, `agentSettleArm` / `agentSettle`, `agentReport`, `agentNavigateToHistoryEntry`, `startFrameStream` / `updateFrameStream` / `stopFrameStream` (frames into shared memory) |

Every item is marked experimental: names and fields may change between releases, and the protocol JSON of the build you run is the authority. Renamed fields keep their old names as deprecated aliases for at least one release.

## Fingerprint identity

Fingerprint spoofing is **off by default**. Turn it on at **`chrome://browser-settings`**:

- **Off**: no spoofing (the machine's real values).
- **Auto**: a fresh random identity each launch.
- **Fixed seed**: a stable identity derived from a number you choose (the same number reproduces the same identity across launches).

An identity is drawn whole from a pool of machine profiles, so its parts agree with each other: a GPU that exists, the processor count and memory such a machine has, a screen at a scale Windows uses, fonts and languages that belong together. Your choice is saved and applied on **every** launch, however the browser is started: a clicked link, a shortcut, or as your default browser. Restart the browser after changing it. The page is equivalent to the `--fingerprint-seed` switch below; a `--fingerprint-seed` on the command line overrides the saved value for that one launch.

Which mode you want depends on the goal. **Auto** breaks correlation between sessions and suits general browsing. **Fixed seed** keeps you consistent to sites that would find a machine whose hardware changes daily more suspicious than one that never changes at all.

`Browser.getFingerprint` reports the identity a running browser presents, every part of it, without running script in any page.

## Answers like Google Chrome

A Chromium build that calls itself Chromium is easy to tell from Chrome, and sites answer it with more captchas. This build answers as Google Chrome on Windows does, with or without an identity:

- **Brand and version.** The user agent and client hints carry the Google Chrome brand. The full version reported is a Chrome release the stable channel serves now (read at most once a day from Google's version-history service and kept per profile, never going backwards), so it matches what Chrome users of the same major report.
- **Automation.** `navigator.webdriver` stays false under `--headless`, `--enable-automation`, `--remote-debugging-pipe` and `--remote-debugging-port=0` (the port ChromeDriver asks for). The "Chrome is being controlled by automated test software" bar that Chrome shows while a DevTools client is attached never appears, since it would change the window's inner height; the same bar that `--enable-automation` itself adds is Chrome's and still appears, so leave that switch out.
- **Features Chrome has and Chromium lacks:** the Google voices in `speechSynthesis.getVoices()`, PlayReady 3000 in `navigator.mediaCapabilities.decodingInfo`, `hrefTranslate`, payment apps (`PaymentManager`, `canMakePayment`), and the built-in AI APIs (`LanguageModel`, `Summarizer`, `LanguageDetector`) answering as Chrome does on the same machine (with an identity, on the machine it claims). `LanguageDetector` uses Chrome's own language detection model, which ships with the build.

`--use-chromium-defaults` turns all of this off for a launch, together with the privacy preset below: the browser then reports itself as Chromium.

## Headless

`--headless=new` answers as a headed window on the same machine: the screen and its work area come from the primary monitor (not 800x600), a window without `--window-size` is maximized as Chrome's would be, the page has focus, and WebGL and WebGPU report the real GPU. With an identity, `--fingerprint-screen=auto` gives the identity's own screen instead, its taskbar fitted to the host's. Chromium's own switches work as usual: `--screen-info`, `--window-size` and `--window-position` for the display, `--use-fake-device-for-media-stream` for media devices, and the `WebRtcIPHandling` policy for WebRTC addresses.

## Privacy defaults

A telemetry-off and privacy preset is applied on **every** launch, with no flags or shortcuts needed. It turns off pings, usage and crash reporting, background networking and the address bar's AI Mode (whose eligibility check contacts Google at every launch), and **keeps Manifest V2 extension support enabled**, so [uBlock Origin](https://github.com/gorhill/ublock) works as it did before Chrome 127.

One request is made on purpose despite the preset: the daily read of the stable channel's current versions described above (from `versionhistory.googleapis.com`; it goes through a proxy given with `--proxy-server`, but not through one set by an extension or a profile setting). `--use-chromium-defaults` or an explicit `--fingerprint-brand-version-long` turns it off.

To launch with stock Chromium behaviour instead, add `--use-chromium-defaults` (Safe Browsing stays off regardless).

### Security tradeoff: Safe Browsing is disabled

The preset **turns off Google Safe Browsing**, which is what normally warns you about phishing pages and malware downloads. This removes a layer of protection for everyday browsing; it is off to speed up page loads and cut network use.

## Built-in extras

- **Markdown viewer.** `.md` and `.markdown` files, local or served as `text/markdown`, open in a built-in read-only viewer (GitHub-style rendering, math, syntax-highlighted code, light and dark themes), the way PDFs open in Chrome's PDF viewer. It works offline and never writes anything. The installer registers the browser as a handler for both extensions, so it can be chosen as the default app for Markdown under **Settings → Apps → Default apps**; the portable zip gets the same registration from `register-browser.ps1`.
- **More than one picture-in-picture window.** Every tab's video can have its own picture-in-picture window at the same time; a new one opens in the next free corner of the screen.
- **Multiview.** The media menu's **Send to Multiview** button collects up to four videos from different tabs into one `chrome://multiview` tab laid out to give the videos the most room.
- **DRM.** The release bundles the Widevine CDM. The Windows software PlayReady CDM is offered to `primevideo.com` and `amazon.com` (`--software-playready-sites` adds hosts); every other site sees stock Chrome's EME answers.

## Command-line switches

Most people won't need these: the privacy defaults are automatic and the identity is set at `chrome://browser-settings`. The switches below are for finer control. Pass one by adding it to the **Target** field of your browser shortcut, or to the command line your automation launches. A shortcut's switches apply to launches from *that* shortcut only, while the privacy defaults and the saved identity seed apply to every launch however the browser is started.

Notation in the **Modes** column: `explicit` means a literal value; `auto` randomizes once per launch; `seed:N` derives deterministically from the integer N (the same N on two launches gives identical values).

The **Seed** column says whether the switch follows `--fingerprint-seed` (or the seed saved at `chrome://browser-settings`) when it is not given itself. Switches without a ✓ take effect only when passed.

<details>
<summary><b>Master and preset switches</b></summary>

| Switch | Modes | Description |
|---|---|---|
| `--fingerprint-seed=auto\|<int>` | auto, integer | The master seed behind every switch with a ✓ below, and the pointer's movement persona when `--movement-persona-seed` is absent. `auto` draws one random seed per launch; `<int>` (a 32-bit signed integer) is reproducible across launches. Usually saved at `chrome://browser-settings` instead; a command-line value overrides the saved one for that launch. |
| `--use-chromium-defaults` | presence-only | Opt out of the always-on preset for this launch: stock Chromium behaviour, the Chromium brand, no served-version read. |

</details>

<details>
<summary><b>Identity switches that follow the seed</b></summary>

These derive from the identity's profile (a coherent machine picked from an embedded pool) or from the seed itself. Each also accepts its own `auto`, `seed:N` or a literal value.

| Switch | Modes | Seed | What it changes |
|---|---|---|---|
| `--fingerprint-gpu-vendor=<string>` | auto, seed:N, explicit | ✓ | `gl.getParameter(UNMASKED_VENDOR_WEBGL)`, and the WebGL limits that follow the vendor (such as `MAX_VERTEX_UNIFORM_VECTORS`). |
| `--fingerprint-gpu-renderer=<string>` | auto, seed:N, explicit | ✓ | `gl.getParameter(UNMASKED_RENDERER_WEBGL)`, an ANGLE renderer string. |
| `--fingerprint-webgpu-vendor=<string>` | auto, seed:N, explicit | ✓ | `(await navigator.gpu.requestAdapter()).info.vendor`, derived from the WebGL renderer through Dawn's GPU database. |
| `--fingerprint-webgpu-architecture=<string>` | auto, seed:N, explicit | ✓ | `…info.architecture`, derived the same way. `info.subgroupMinSize` and `subgroupMaxSize` follow the claimed architecture where that range holds the real GPU's, so a page that measures one sees no contradiction. |
| `--fingerprint-hardware-concurrency=<int>` | auto, seed:N, explicit | ✓ | `navigator.hardwareConcurrency`. |
| `--fingerprint-device-memory=<int>` | auto, seed:N, explicit | ✓ | `navigator.deviceMemory`, snapped to a value Chrome reports (2, 4, 8, 16 or 32). |
| `--fingerprint-audio-context=<sr,bl,ol,mcc>` | auto, seed:N, explicit | ✓ | `new AudioContext()`: `sampleRate`, `baseLatency`, `outputLatency`, `destination.maxChannelCount`. |
| `--fingerprint-battery=<charging,level,ct,dt>` | auto, seed:N, explicit | ✓ | `navigator.getBattery()`. A desktop identity is always plugged in; a laptop's values are drawn. |
| `--fingerprint-brand=<string>` | auto, seed:N, explicit | ✓ | `navigator.userAgentData.brands[].brand`. Default `Chrome`, reported as Google Chrome, with or without a seed. |
| `--fingerprint-brand-version=<int>` | auto, seed:N, explicit | ✓ | The major version in the user agent. Default: the real one. |
| `--fingerprint-brand-version-long=<full>` | auto, seed:N, explicit | ✓ | `getHighEntropyValues(['fullVersionList'])`. Default: a version the stable channel serves now. |
| `--canvas-curve-noise=<float>` | auto, seed:N, explicit | ✓ | Sub-pixel perturbation of Canvas 2D curves (bezier, arc, quadratic), from 0.003 to 0.015. |
| `--canvas-blur-noise=<float>` | auto, seed:N, explicit | ✓ | Multiplicative perturbation of Gaussian blur sigmas (`shadowBlur`, `ctx.filter = 'blur(...)'`), from 0.005 to 0.03. |
| `--canvas-gradient-noise=<float>` | auto, seed:N, explicit | ✓ | Additive perturbation of Canvas 2D gradient colour-stop offsets, from 0.003 to 0.02. |
| `--webgl-shader-noise=<float>` | auto, seed:N, explicit | ✓ | Sub-LSB perturbation of WebGL fragment shaders' natural-variance constructs, from 0.001 to 0.003. |
| `--browser-font-bundle=<seed-string>` | auto, seed:N, explicit | ✓ | Loads fonts only from a bundle in `browser_fonts/` beside `chrome.exe`; changes `document.fonts` and text widths. A seed-derived bundle also sets `navigator.languages` and Accept-Language. |
| `--fingerprint-refresh-rate=<hz>` | auto, seed:N, explicit | ✓ | The display refresh rate as pages measure it through `requestAnimationFrame` (Windows). The browser paces its own vsync at that rate, capped to the real monitor's while the window is visible. |

The four noise switches draw their `auto` and `seed:N` values from the claimed GPU's vendor and architecture rather than from the seed alone: identities that claim one GPU family draw alike, as real machines with one GPU family do, and the seed picks one of a few variants, as driver versions split them. Without a claimed GPU the seed alone draws the value.

</details>

<details>
<summary><b>Identity switches taken only when passed</b></summary>

These exist but do not follow `--fingerprint-seed`. Pass them with `=auto`, `=seed:N`, or a literal value.

| Switch | Modes | What it changes |
|---|---|---|
| `--fingerprint-screen=<w,h,aw,ah,at,cd[,dpr]>` | auto, seed:N, explicit | `screen.width/height/availWidth/availHeight/availTop/colorDepth`, plus `window.devicePixelRatio` (optional 7th field). `auto` and `seed:N` use the identity's own screen, its taskbar fitted to the host's. |
| `--fingerprint-screen-position=<x,y>` | auto, seed:N, explicit | `window.screenX/screenY`; derived as a maximized window's corner. |
| `--fingerprint-media-features=<scheme,motion,contrast,colors,gamut>` | auto, seed:N, explicit | CSS `matchMedia`: `prefers-color-scheme`, `prefers-reduced-motion`, `prefers-contrast`, `forced-colors`, `color-gamut`. |
| `--fingerprint-media=<mics,webcams,speakers>` | auto, seed:N, explicit | `navigator.mediaDevices.enumerateDevices()` counts per kind. Before permission, any non-zero count shows as one entry per kind, as in Chrome. |
| `--fingerprint-history-length=<int>` | auto, seed:N, explicit | `history.length`; derived from 1 to 5. |
| `--fingerprint-connection=<eff,dl,rtt,sd,type>` | auto, seed:N, explicit | `navigator.connection` and the `Downlink`, `RTT` and `ECT` client hints: `effectiveType` (`slow-2g`, `2g`, `3g` or `4g`), downlink in Mbps, RTT in ms, saveData, connection type. Without it a seeded browser reports Chrome's own network estimate. |
| `--fingerprint-text-rendering=gamma:<float>,contrast:<float>` | explicit only | Skia text gamma and contrast (Windows). |
| `--fingerprint-device-type=laptop\|desktop` | explicit only | Whether the identity is a laptop or a desktop, for a tool that stores identities; the refresh rate and battery are drawn for it. |
| `--webgl-shader-noise-k=<name=value,...>` | explicit only | Tuning aid: per-construct multipliers for `--webgl-shader-noise`. Not derived from the seed. |

</details>

<details>
<summary><b>Proxy-consistent switches</b></summary>

These don't fit the seed model. Set them to match the proxy or VPN exit you use: a fingerprint that claims `America/New_York` while your traffic exits in Frankfurt is more identifying than no spoofing at all.

| Switch | Modes | Effect |
|---|---|---|
| `--fingerprint-timezone=<IANA>` | explicit only | The time zone (e.g. `America/New_York`). |
| `--fingerprint-geolocation=<lat,lon,acc>` | explicit only | `navigator.geolocation.getCurrentPosition()`. |
| `--webrtc-ip4=<ip>` | explicit only | The IPv4 address in WebRTC ICE candidates and SDP. |
| `--webrtc-ip6=<ip>` | explicit only | The IPv6 address in WebRTC ICE candidates and SDP. |
| `--fingerprint-accept-language=<BCP-47>` | explicit only | Forces the HTTP `Accept-Language` header; no effect while a font bundle is active, since the bundle sets the header. |

</details>

<details>
<summary><b>Automation and utility switches</b></summary>

| Switch | Effect |
|---|---|
| `--movement-persona-seed=<int64>` | The seed of the human-movement persona that plans pointer paths for the custom Input methods. Absent: derived from `--fingerprint-seed` when that is given, otherwise random for each browser run. |
| `--private-clipboard` | The browser keeps its own in-memory clipboard: copy, cut and paste work inside this browser and never read or overwrite the clipboard of the person at the machine. Required by `Input.dispatchPaste`. |
| `--dismiss-permission-prompts` | Permission prompts (camera, microphone, location, notifications, File System Access, ...) are dismissed unseen after a random 1-5 s, as a person closing them would, with nothing stored for the site; the client is told through `Input.permissionPromptDismissed`. |
| `--cancel-print-preview` | A page's `window.print()` runs the normal scripted-print flow, but the preview is closed unseen after a random 1-4 s, as if cancelled; `Page.printToPDF` is unaffected. |
| `--cancel-payment-request` | A payment sheet nobody will see is closed after a random 1-2 s with Chrome's own `AbortError`, as a person closing it would; without it a page's `show()` waits, as Chrome's does while its sheet is open. |
| `--auto-decline-webauthn` | WebAuthn and passkey prompts are declined with `NotAllowedError` after a random 1-5 s, one ceremony at a time as Chrome holds them; for runs where no authenticator is attached and a hanging prompt would stall the session. |
| `--show-cdp-cursor` | Draws the CDP-driven cursor while a DevTools client is attached. Useful for watching automation. |
| `--software-playready-sites=<host,...\|*>` | Extra hosts (subdomains included) allowed to use the software PlayReady CDM besides `primevideo.com` and `amazon.com`; `*` allows every origin. Every other origin sees stock Chrome's EME answers. |

</details>

## Install

### Installer (recommended)

1. Download `Chromaphore-<release>-chromium<chromium>-windows-x64-setup.exe` and run it. A newer installer upgrades an earlier Chromaphore install in place. Installs from before the rename ("Anti-Fingerprint Chromium") are a separate program to Windows; uninstall one by hand from **Settings → Apps**.
2. Choose an install location (or accept the default) and all-users vs. just-me.
3. It installs the browser, adds Start Menu / desktop shortcuts, and registers it with Windows as a web browser.
4. To make it your default: tick **"Choose … as your default browser"** on the last wizard page, or later open **Settings → Apps → Default apps**, find **Chromaphore**, and set it for `http`, `https`, and `.html`. The same page lets you make it the default app for `.pdf` and `.md` files.

Uninstall from **Settings → Apps** like any normal program.

Windows SmartScreen may warn on first run ("Windows protected your PC", unknown publisher), since the build isn't code-signed yet. To run it anyway, click **More info → Run anyway**. Before you do, you can check that the file is the one published here: run `Get-FileHash .\<file name>` in PowerShell and compare the hash with the SHA-256 in the release notes.

### Portable (zip)

1. Extract the zip anywhere and run `chrome.exe`, no installation required.
2. *(Optional)* To make the portable copy selectable as your default browser, download `register-browser.ps1` from the same release, put it in the extracted folder and run it there in an **elevated** PowerShell (or add `-PerUser` to register for just your account, no admin needed), then set it in **Settings → Default apps**. Undo any time with `register-browser.ps1 -Unregister`.

## Source and binary

The binary on the Releases page is the whole browser, free to use: everything this README describes is in it. Its source is published in [`patches/`](patches) except for the fingerprint identity layer: the identity switches above, `chrome://browser-settings` and `Browser.getFingerprint`. That part stays closed so detection vendors cannot simply read how the spoofing works. It is no perfect defence, but it raises their cost.

If you would rather not run a binary you cannot fully inspect, build the browser yourself from `patches/`: you get every automation feature, the Google Chrome parity and the headless behaviour described above, without the fingerprint identity.

## Building from source

`build.py` does the whole job: it clones [ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows) at the pinned tag, checks out the matching Chromium release with its tooling, fetches the toolchain downloads, applies the curated ungoogled patches followed by this project's patch series, and runs the build.

```
python build.py [-j N] [--widevine-dir DIR] [--package]
```

Requirements, the same as for ungoogled-chromium-windows: Windows 10 or 11 x64, Visual Studio 2026 with the C++ workload and the Windows SDK version Chromium pins (10.0.28000 for this release), Python 3 with the `clang` module (`python -m pip install clang==21.1.7`; V8's build uses it, and the script checks for it first), Git, 7-Zip, around 55 GB of free disk space and 32 GB or more of RAM. A full build takes several hours. Run it from a regular prompt; the script sets up the Visual Studio environment itself. A second run skips the checkout and patching and goes straight to the build; `--clean` starts over.

The Widevine CDM is not in this repository. Pass `--widevine-dir` with a directory holding the CDM's `LICENSE` and `win/x64/manifest.json`, `widevinecdm.dll` and `widevinecdm.dll.sig` to bundle one you obtained yourself. Without it the build disables Widevine, and the browser still plays PlayReady content.

The language detection model `LanguageDetector` uses is copied by the build from Chromium's own source tree (`components/test/data/translate/valid_model.tflite`) into `LanguageDetection\` beside `chrome.exe`, and packaging ships it.

The installer and portable zip on the Releases page are packaged separately; `--package` runs the stock ungoogled-chromium-windows packaging instead, which produces an installer and a zip under `build/ungoogled-chromium-windows/build/`.

## Intended use

This is built for browser agents and for people who want control over what their browser discloses: agents that work on a person's behalf, privacy-conscious browsing, testing how your own sites respond to varied client configurations, security research, and automation against systems you own or are authorized to access.

It isn't built for evading bans, operating fake accounts at scale, or circumventing access controls on services you don't own. Those uses tend to violate the terms of service of whatever you're pointing it at, and in some jurisdictions bypassing technical access restrictions carries legal exposure beyond a terms violation. What you do with it is on you.

## Contributing

Bug reports and feature requests are welcome via [Issues](../../issues). Fingerprint-detection reports are especially useful: if a site tells this browser from stock Chrome, open an issue with the site and what gave it away.

## Credits

Built on [Chromium](https://www.chromium.org/). The Safe Browsing removal draws on the [ungoogled-chromium](https://github.com/ungoogled-software/ungoogled-chromium) project's work.

## License

- **The patches** in this repository are BSD-3-Clause, see [`LICENSE`](LICENSE): anyone may build, change and share a browser made from them, keeping the copyright notice.
- **The release binaries** are under [`LICENSE-BINARY.md`](LICENSE-BINARY.md): free to use for any purpose, personal or commercial, on any number of machines. Share the link to the Releases page rather than the files, and don't modify the binaries or reverse engineer their closed parts.

Chromium itself is BSD-3-Clause and bundles components under other licenses; those obligations carry over to this derivative. Third-party notices are listed at `chrome://credits` within the running browser. The curated patches under `patches/ungoogled/` come from [ungoogled-chromium](https://github.com/ungoogled-software/ungoogled-chromium) and [ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows), also BSD-3-Clause. The language detection model is a file of Chromium's own source tree outside `third_party/`, which Chromium's convention places under its BSD-3-Clause license.
