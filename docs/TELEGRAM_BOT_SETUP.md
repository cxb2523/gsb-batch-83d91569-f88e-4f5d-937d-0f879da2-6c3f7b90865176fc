# GatherRadar Telegram Bot

`@GatherRadar_Bot` runs on the owner's Windows computer with long polling. No public server,
webhook, tunnel, domain or hosting is needed.

- **Phase 1:** a Persian menu, help, `/whoami`, and a read-only list of the configured sources.
- **Phase 2:**
  - crawl all enabled sources («🔄 کرال همه منابع»);
  - crawl a chosen set of sources («🎯 انتخاب منابع»);
  - receive the Persian Excel workbook («📊 دریافت خروجی»);
  - browse the extracted events as Persian messages;
  - open earlier runs and their outputs («🕘 آخرین اجراها»).

The bot never adds, edits, enables or deletes sources. «📋 مدیریت منابع» and «⚙️ تنظیمات» stay
marked «به‌زودی».

## Architecture

```text
python -m gatherradar telegram run
  └─ telegram_bot/runner.py      settings → single-instance lock → getMe check → long polling
       ├─ settings.py           env vars only; token never printed or logged
       ├─ auth.py               OwnerPolicy: exact numeric owner ID, private chat only
       ├─ handlers.py           global guard (group -1) + per-handler re-check; thin rendering
       ├─ presentation.py       Persian text, inline keyboards, versioned allowlisted callback data
       ├─ services.py           SourceCatalog (read-only) + GatherRadarOperations protocol
       ├─ operations.py         LocalOperations: crawl scope, runs, events, workbook checks
       └─ jobs.py               JobManager: one crawl at a time in a worker thread, persisted status
                                 └─ orchestration.refresh.application_refresh_service → RefreshService
```

- **Same pipeline as the CLI.** A crawl calls the same `RefreshService` wiring as `gatherradar refresh`:
  - the same database (`data/state/gatherradar.sqlite3`), workbook (`data/review/GatherRadar.xlsx`) and exports;
  - defaults of `--limit 5 --days 14`;
  - Instagram media evidence included.

  Bot runs therefore appear in the normal history, keep review decisions, and use the existing XLSX exporter.
- **Read-only browsing.** Events, runs and workbook checks only read:
  - the persisted SQLite review projection;
  - the run index (`تاریخچه اجراها`) of the existing workbook.

  Nothing is rediscovered or renormalized, and a read action never creates a database.
- **Collection runs off the event loop.** Browser capture, OCR, collection, persistence and export run in one non-daemon worker thread; the event loop is never blocked.
- **One job at a time.** A second request is refused and shown the current job's status.
- **Persisted job status.**
  - The job ID equals the GatherRadar run ID.
  - Status is saved atomically to `data/telegram/jobs.json` (last 30 jobs).
  - After a restart, a job that was running is shown as «قطع‌شده» (interrupted), never as finished.
- **Progress hooks.** `RefreshService.run` gained optional `progress` and `should_stop` hooks:
  - progress reports source started/finished, analysis, persistence and export, with no percentages;
  - stopping is checked only before each source and before analysis.
- **Cancellation.**
  - A source in progress (Chrome capture, OCR) and the database/export writes are never interrupted.
  - A cancelled run records manifest status `cancelled` and persists no snapshot. Raw observations already collected stay in the append-only raw store.
  - Stopping the bot (Ctrl+C) asks a running crawl to stop at the next safe boundary and waits for it.

## Security boundary

- **Secrets.**
  - Credentials come only from `GATHERRADAR_TELEGRAM_BOT_TOKEN` and `GATHERRADAR_TELEGRAM_OWNER_ID`.
  - GatherRadar does not read `.env` files. `.env.example` documents the names only, and `.env` is ignored by Git.
  - The token is redacted from every log record.
  - `httpx` and `httpcore` request logging, which contains the token in the URL, is raised to WARNING.
- **Bot identity.** Start-up checks `getMe`; a token for any bot other than `@GatherRadar_Bot` is refused.
- **Owner check.**
  - Every update passes a global guard before any handler. Each handler re-checks the owner, and so does every callback.
  - Callback data is versioned (`gr1:`), limited to 64 bytes and parsed against an allowlist.
  - Source IDs in callbacks are checked against the registry, so forged or stale callbacks return "invalid" and no data.
- **Bootstrap mode.**
  - Until `GATHERRADAR_TELEGRAM_OWNER_ID` is set, the bot answers only `/whoami`, with the sender's numeric ID, in private chats.
  - Every other request gets a short "owner not configured" note.
  - The first `/start` sender never becomes the owner.
- **Strangers and groups.**
  - Other users get "this bot is private" and nothing else: no menus, sources, paths or logs.
  - In groups the bot stays silent, even for the owner.
- **Command menus.** Commands are published per scope: the default menu shows only `/whoami`, and the owner's private chat shows the full list.
- **One instance.**
  - A lock file (`data/telegram/bot.lock`) allows a single local bot process.
  - If another computer is polling the same bot, Telegram reports a `Conflict`; the bot stops and says so.
- **Errors.** The owner sees a short Persian error message; details go only to the local log.

Adding a source in a later phase never implies that an arbitrary website is supported:
- unsupported layouts need an adapter;
- `robots.txt` and access policy always apply (the Davvvat website stays disabled);
- disabling a source is reversible and is preferred over deletion.

## Windows setup (PowerShell, in the repository folder)

1. Install the dependency into the existing virtual environment:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   ```

2. Store the token as a user environment variable. You type it into a hidden prompt; it never
   appears on screen, in history, in GitHub or in chat:

   ```powershell
   $secure = Read-Host 'GatherRadar bot token from BotFather' -AsSecureString
   $plain = [System.Net.NetworkCredential]::new('', $secure).Password
   [Environment]::SetEnvironmentVariable('GATHERRADAR_TELEGRAM_BOT_TOKEN', $plain, 'User')
   Remove-Variable plain, secure
   ```

   Close this PowerShell window and open a new one so the variable is loaded.

   > Windows stores user environment variables in your profile, readable by programs you run.
   > Revoke the token in BotFather (`/revoke`) if this computer is ever compromised.

3. Start the bot in bootstrap mode and get your numeric ID:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

   In Telegram, open `@GatherRadar_Bot` and send `/whoami`. Note the number it returns.
   Stop the bot with `Ctrl+C`.

4. Set the owner ID (replace the digits with your own) and open a new PowerShell window:

   ```powershell
   [Environment]::SetEnvironmentVariable('GATHERRADAR_TELEGRAM_OWNER_ID', '123456789', 'User')
   ```

5. Start the bot:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

6. In `@GatherRadar_Bot`, test `/start`, `/menu` and `/sources`.

7. Stop safely with `Ctrl+C`. The bot finishes the current update, stops polling and releases the lock.

## Manual acceptance checklist

- [ ] Start-up logs `telegram_bot_starting username=@GatherRadar_Bot mode=owner configured`, and no token appears anywhere.
- [ ] `/start` and `/menu` show the Persian main menu:
  - «📚 فهرست منابع» works;
  - only «📋 مدیریت منابع» and «⚙️ تنظیمات» carry «· به‌زودی» and answer «این قابلیت در مرحله بعد فعال می‌شود.»
- [ ] `/sources` lists Instagram and Website sources separately, with active/inactive state. Davvvat Website shows as inactive (robots).
- [ ] Tapping a source shows its ID, type, state and public URL. «↩️» returns to the list and to the menu.
- [ ] Tapping the same button twice causes no error message.
- [ ] From another Telegram account, `/start`, `/sources` and `/whoami` return only «این ربات خصوصی است…».
- [ ] Adding the bot to a group produces no replies.
- [ ] Starting a second bot in another window fails with "already running".
- [ ] Nothing under `data/raw`, `data/state` or `data/review` changes during the session.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `GATHERRADAR_TELEGRAM_BOT_TOKEN is not set` | Repeat step 2, then open a new PowerShell window. |
| `Telegram rejected the bot token` | The token was revoked or mistyped. Get it from BotFather and repeat step 2. |
| `This token belongs to @X, not @GatherRadar_Bot` | Use the GatherRadar bot's token. |
| `Telegram is unreachable (network error)` | No internet, a firewall, or Telegram is blocked on this network. Check access to `api.telegram.org` (a system VPN or proxy may be required). The bot retries three times, then exits. |
| `Another GatherRadar Telegram bot is already running` | Another window is running it. Close that window (`Ctrl+C`). |
| `Another process is already polling this bot` | The same token runs on another computer or service. Stop it; only one poller per token is possible. |
| The bot answers «مالک ربات هنوز تنظیم نشده است» | `GATHERRADAR_TELEGRAM_OWNER_ID` is not visible to this window. Repeat step 4 and open a new window. |

## Phase 2 usage

- **Crawl all enabled sources («🔄 کرال همه منابع»).**
  1. The bot shows a summary: enabled sources, 5 items per source, a 14-day horizon, and the outputs.
  2. Tap «✅ شروع کرال» to start. One status message is edited in place: stage, current source, completed/total, and each source's ✅/⚠️/❌.
  3. «⏹ توقف پس از منبع فعلی» stops at the next safe boundary.
- **Crawl selected sources («🎯 انتخاب منابع»).**
  - Pages of enabled sources only, with ☑️/⬜️ checkboxes. The selection is kept across pages.
  - Options: «همه فعال‌ها», «پاک کردن انتخاب», «✅ تأیید انتخاب».
  - Each channel is separate, e.g. Jabama Events website, Jabama Experiences website and Jabama Instagram.
  - The Davvvat website (disabled by robots) is never offered and is refused if forged.
- **After a crawl.** The summary separates:
  - successful, partial and failed sources;
  - event candidates discovered vs. those excluded for a missing title;
  - unique canonical Events, split into upcoming/current, Schedule Review and expired;
  - Excel success or failure.

  It then offers «📥 دریافت Excel», «📋 نمایش رویدادها», «🗓 بررسی زمان‌بندی» and «↩️ منوی اصلی».
- **«📊 دریافت خروجی».** Opens the latest run whose snapshot is in the workbook, without crawling.
- **Excel delivery.**
  - The workbook file is sent only if it exists, is readable, is under 45 MB, and its run index contains that run's sheet.
  - The caption names the run time, the sources and that run's sheet.
  - A failed or missing export is reported; an older file is never sent instead.
  - The workbook is the existing cumulative GatherRadar workbook, so it also contains earlier runs' sheets (append-only history).
- **Event browsing.**
  - Five events per page, grouped by date, showing:
    - title;
    - Jalali date and the time when stored, or the next session;
    - venue, area and city;
    - the first line of the source's own description.
  - «مشاهده جزئیات» opens one event by editing the same message. It also shows the source's schedule wording, address, price and capacity wording, the review note and up to 900 characters of description, plus «🔗 مشاهده منبع».
  - «بستن جزئیات» returns to the page.
  - Schedule Review items are a separate list with their source wording.
  - Missing facts are omitted, never invented. Expired Events are not listed as upcoming.
- **«🕘 آخرین اجراها».** Lists recent runs labelled as:
  - live crawl (کرال زنده);
  - stored replay (بازپخش);
  - incomplete (ناتمام, i.e. interrupted, cancelled or failed before persistence).

  Open a run to get its Excel or event lists.

Callback data holds only short tokens: a 12-character run-ID prefix, a page, an index, or a one-time confirmation nonce. Everything else is looked up on the server:
- confirmations expire after ten minutes and work once;
- replayed or forged callbacks are refused.

## Phase 2 local acceptance (Windows PowerShell, repository folder)

1. Update the branch (your data and `config/sources.yaml` are untouched):

   ```powershell
   git fetch origin feat/telegram-bot-mvp
   git checkout feat/telegram-bot-mvp
   git pull origin feat/telegram-bot-mvp
   ```

2. Install (no new dependency since Phase 1; this refreshes the editable install):

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   ```

3. Start the bot:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

4. Run a single-source test.
   1. In `@GatherRadar_Bot`: `/menu` → «🎯 انتخاب منابع». Tick one small website source, e.g. «Vadoostan Website».
   2. Tap «✅ تأیید انتخاب» → «✅ شروع جمع‌آوری». Watch the single status message update until the summary appears.
5. Tap «📥 دریافت Excel». Open the document, then the sheet named in the caption.
6. Tap «📋 مشاهده رویدادها». Page through, open «مشاهده جزئیات», «🔗 مشاهده منبع» and «بستن جزئیات».
7. Only after steps 4–6 pass: `/menu` → «🔄 کرال همه منابع» → «✅ شروع جمع‌آوری». Chrome opens for Instagram as in a normal refresh.
8. Stop the bot with `Ctrl+C`. If a crawl is running, it finishes the current source first.

## Phase 2 acceptance checklist

- [ ] Confirmation appears before every crawl; menu navigation alone never starts one.
- [ ] Tapping «✅ شروع جمع‌آوری» twice, or tapping an old confirmation, starts nothing more.
- [ ] While a crawl runs, a second crawl request shows «یک اجرا در جریان است…».
- [ ] Progress shows the current source and completed counts (no percentages).
- [ ] The summary distinguishes candidates, canonical, upcoming, review, expired and missing-title.
- [ ] The Excel document belongs to that run (caption sheet name and time), and the file opens.
- [ ] The event list pages, details expand and collapse, and source links open.
- [ ] «🕘 آخرین اجراها» shows this run and earlier CLI runs, and an old run's Excel can be requested.
- [ ] «⏹ توقف پس از منبع فعلی» ends as «لغو شد» after the current source.
- [ ] Another Telegram account still gets only «این ربات خصوصی است…».

## Known limitations

- **Cancellation is coarse.** It takes effect between sources. One Instagram source with media can take several minutes, and CLI runs cannot be cancelled from the bot.
- **The workbook is cumulative.** Telegram receives the whole workbook, and the caption names the sheet for the run.
- **CLI and bot runs block each other.** A crawl started from the command line holds the database lock, so a bot crawl at the same time fails with a clear message (and vice versa).
- **Job status is persisted, but the job itself is not resumed.** After an unexpected exit, an interrupted crawl must be started again.
- **The selection is in memory.** It resets when the bot restarts. Only the owner can use the bot, so selection state is single-user by design.

## Phase 3: progress, estimates and source management

Phase 3 adds a polished journey and owner-managed sources. Crawling, `RefreshService`,
the collectors, Excel export, event browsing, runs, owner decisions and evidence are unchanged.

### Journey

Welcome → menu → action → configure → confirm → run → results → output → menu.
The menu has 🔄 کرال همه منابع, 🎯 انتخاب منابع, 📋 مدیریت منابع, 📊 دریافت خروجی,
🕘 آخرین اجراها, ⚙️ تنظیمات (فقط نمایش) and ❓ راهنما. While a crawl runs, «⏳ وضعیت اجرای جاری»
appears at the top. Every screen after the menu has a back or main-menu button; there are no dead ends.

- **Before a crawl.** The confirmation says how many sources run, the item limit and the 14-day
  window, then asks «آیا می‌خواهید جمع‌آوری شروع شود؟». It shows a time estimate only when history
  supports one.
- **During a crawl.** One status message is edited in place. It shows the stage, completed sources,
  the current source and its type, the elapsed time (overall and for the current source), the
  estimate or «⌛ هنوز داده کافی برای تخمین زمان باقی‌مانده نداریم.», a "what happens next" line
  and how stopping works.
- **After a crawl.** The result keeps these groups separate: sources completed, with warnings and
  failed; unique upcoming Events; schedule review; missing-title candidates; and whether Excel is
  ready. It also shows the actual total duration. Buttons: «📥 دریافت Excel», «📋 مشاهده رویدادها»,
  «🗓 بررسی زمان‌بندی», «🕘 جزئیات اجرا» and «↩️ منوی اصلی».
  An empty result says it is not an error. A failure says what failed and whether anything was saved.

### Elapsed time and the remaining-time estimate

- **Elapsed time.**
  - Measured with `time.monotonic()` in the bot process.
  - A ticker in the event loop refreshes the status every 10 seconds (edits at least 4 seconds
    apart), so a long Instagram source never looks frozen. A small indicator rotates (◐◓◑◒).
  - The ticker never blocks the event loop and stops on success, failure, cancellation or shutdown.
  - After a restart, interrupted jobs get no ticker.
- **Telegram limits.** A `RetryAfter` (flood limit) pauses edits for the requested time. The final
  result waits once and retries. "Message is not modified" is ignored. If the status message was
  deleted, progress continues in a new message.
- **History.** Stored in `data/telegram/timings.json`: per source, up to 20 recent samples of
  seconds, outcome, item limit, media/OCR mode and source type; plus up to 20 samples for the stage
  after collection. No content, URLs or credentials.
- **Baseline.** Only `success` samples with the same item limit and media mode count. Partial,
  failed and unusually slow samples (more than 3× the median of the others) are kept for
  inspection but excluded. Cancelled runs never feed the post-collection baseline.
- **Estimate.**
  - Each pending source needs 3 of its own baseline samples; otherwise the typical range of its
    type (Instagram or website) is used, when that type has history.
  - The post-collection stage also needs 3 samples. If anything is missing, no estimate is shown.
  - The range adds per-source minimum/maximum. For the running source, its elapsed time is
    subtracted. Past its usual maximum, the message says it is taking longer than usual instead of
    guessing.
  - It is shown in whole minutes («حدود ۳ تا ۶ دقیقه»). No percentages and no model.
- **Expect the estimate to appear** after about three successful runs of the same sources.
  Instagram sources take longer because media is captured and read with OCR, and the message says so.

### Source management («📋 مدیریت منابع»)

- **Overview.** Counts of active, disabled, archived, Instagram and website sources. Actions:
  ➕ افزودن منبع, 📚 مشاهده منابع, ⏸ غیرفعال‌سازی منبع, ▶️ فعال‌سازی منبع, 🗂 حذف از فهرست,
  ♻️ بازیابی منابع حذف‌شده. Lists are paginated and show each source's ID, type and status.
- **Adding a source** is a guided, three-step conversation: type → address → preview.
  - Every step has back and cancel.
  - Invalid input shows the reason and keeps you on the same step.
  - Nothing is saved before you confirm.
  - Saving never starts a crawl.
- **Instagram.**
  - Accepts `@example_account`, `example_account` or `https://www.instagram.com/example_account/`.
  - Posts, reels and other non-profile paths are refused.
  - Duplicates are refused: the same ID or account, including archived sources.
  - No password is ever requested. Crawls use the same Chrome profile as before.
  - Access is never claimed: a private or limited account appears as a source failure in the first crawl.
  - You can save it active («✅ افزودن و فعال‌سازی») or paused («💾 افزودن (غیرفعال)»).
- **Website.**
  - **Refused outright:** non-http(s) URLs; credentials; unusual ports; localhost; private,
    link-local, reserved and metadata addresses (also after DNS resolution); and duplicates.
  - **Supported:** only when the host and listing path match a configured website source with a
    specific existing adapter (for example another `jabama.events/all?city=…` listing). It reuses
    that adapter. `robots.txt` is checked through the existing transport, which allows only
    same-origin redirects and re-vets every hop; timeouts and size limits are unchanged.
  - **Policy-blocked:** a site whose policy blocks GatherRadar (for example `davvvat.ir`) is
    saved inactive with the policy reason.
  - **Unsupported:** everything else is stored as «در انتظار پشتیبانی» and is never runnable:
    «این وب‌سایت ثبت شد، اما ساختار آن هنوز توسط GatherRadar پشتیبانی نمی‌شود. برای فعال‌سازی
    Crawl به بررسی یا Adapter اختصاصی نیاز دارد.»
  - Unknown hosts are never contacted. No new adapter is written by this flow.
- **Disable / enable.**
  - Reversible, and the state is re-checked at confirmation.
  - A disabled source leaves all-enabled crawls and the selection list.
  - Enabling a website you added re-checks its `robots.txt`.
  - Sources blocked by robots or terms, and unsupported sites, have no enable button, and a forged
    enable is refused.
- **Archive («🗂 حذف از فهرست»).** A soft delete with confirmation («تأیید حذف» / «انصراف»).
  - It hides the source and excludes it from future crawls.
  - Events, runs, raw JSONL, OCR evidence, Excel files, provenance and review decisions are never
    deleted.
  - «♻️ بازیابی» brings it back paused, or still blocked when a policy applies.
- **During a crawl.** Source changes and new sources are refused with an explanation; the running
  crawl keeps the source snapshot you confirmed.
  - All-enabled and selected crawls run the exact list shown on the confirmation.
  - If the registry changed after you confirmed, nothing starts and you are asked to confirm again.

### Registry design (one effective registry for CLI and bot)

- **Base:** `config/sources.yaml` (tracked). Never rewritten by the bot, so `git pull` keeps
  updating it.
- **Overlay:** `config/sources.local.json` (git-ignored). Holds sources you added and lifecycle
  state for base sources (paused, re-enabled after a pause, archived). Base IDs, URLs, adapters
  and publisher identities are never copied or changed.
- **Precedence.** Base definitions win. If a later `git pull` adds the same ID, Instagram account
  or website URL, the local entry is kept in the file but not loaded, so there is never a duplicate
  crawl.
  - A `robots`/`terms` reason or `unsupported` cannot be cleared by the overlay.
- **Shared loading.** `config.load_sources()`, used by every CLI command and the bot, returns
  base + overlay. `python -m gatherradar sources list` prints the effective registry and how many
  sources an all-enabled crawl would include.
- **Safety.**
  - Every write validates the complete registry first and runs under a file lock.
  - Each write is atomic, and the previous good version is kept as `sources.local.json.bak`.
  - If the overlay becomes unreadable, the backup is used. With no valid backup, loading fails
    closed with a clear error instead of crawling an unknown set of sources.
- **Overlay location.** `GATHERRADAR_SOURCE_OVERLAY` can point to another file, or `none` to
  ignore the overlay. The test suite sets `none`, so it never reads your local sources.
- No new database is introduced.

### Security (Phase 3 additions)

- Owner checks run before every callback, text message and commit, including source changes,
  conversation steps, crawls, run reads and Excel delivery.
- Source changes use one-time confirmation tokens that expire after ten minutes. Add-source
  conversations expire after 15 minutes and live only in memory. A restart or an old preview
  button commits nothing and asks you to start again.
- Names, URLs and descriptions are escaped and bounded in every message.
- The bot never accepts filesystem paths or commands, never asks for or prints tokens or Instagram
  credentials, and never shows internal errors or local paths.

## Phase 3 local acceptance (Windows PowerShell, repository folder)

1. **Update without losing local changes.** `data/` and `config/sources.local.json` are ignored by
   Git and are never touched.

   ```powershell
   git status
   git stash push -m "before-phase3"   # only if git status listed modified files
   git fetch origin feat/telegram-phase3-source-management
   git checkout feat/telegram-phase3-source-management
   git pull origin feat/telegram-phase3-source-management
   git stash pop                        # only if you stashed above
   ```

   If the branch was delivered as a bundle instead, follow the import steps that came with it.
2. **Install and test** (no new dependency):

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   .\.venv\Scripts\python.exe -m unittest discover -s tests
   ```

3. **Start the bot:** `.\.venv\Scripts\python.exe -m gatherradar telegram run`
4. **Welcome and navigation.** Send `/start`. Check the welcome text and open ⚙️ تنظیمات, ❓ راهنما
   and 📋 مدیریت منابع. Return with «↩️ منوی اصلی» from each screen.
5. **Small selected crawl.** «🎯 انتخاب منابع» → tick «Vadoostan Website» → «✅ تأیید انتخاب» →
   «✅ شروع جمع‌آوری».
   - Watch the status: the elapsed time and indicator change about every 10 seconds.
   - Until history exists it says «⌛ هنوز داده کافی برای تخمین زمان باقی‌مانده نداریم.».
   - After the third successful run of the same source, the confirmation and progress show
     «حدود … دقیقه».
6. **Excel and events.** In the result, tap «📥 دریافت Excel» and open the named sheet. Then tap
   «📋 مشاهده رویدادها» and open one event's details and source link.
7. **Add an Instagram source (no crawl).** «📋 مدیریت منابع» → «➕ افزودن منبع» → «📸 اینستاگرام».
   - First send `https://www.instagram.com/p/abc/`: it is refused and you stay on the same step.
   - Then send `@instagram`. Check the preview, then tap «💾 افزودن (غیرفعال)».
   - No crawl starts. In a second PowerShell window, run
     `.\.venv\Scripts\python.exe -m gatherradar sources list`; it lists `instagram_instagram … local`.
8. **Disable, archive and restore it.** Open it from «📚 مشاهده منابع».
   - «▶️ فعال‌سازی» → confirm.
   - «⏸ غیرفعال‌سازی» → confirm.
   - «🗂 حذف از فهرست» → «تأیید حذف».
   - «♻️ بازیابی منابع حذف‌شده» → choose it → «♻️ بازیابی به فهرست» → confirm. It returns paused.
   - Earlier runs and Excel are unchanged.
9. **Unsupported website.** «➕ افزودن منبع» → «🌐 وب‌سایت» → `https://example.org/events`.
   - The preview says it is not supported and offers only «💾 ثبت به‌صورت غیرفعال».
   - After saving, it shows «🟡 در انتظار پشتیبانی» and has no enable button.
10. **All-enabled excludes the rest.** Archive the test Instagram source again, then tap
    «🔄 کرال همه منابع».
    - The confirmation must not list it, Davvvat Website (robots) or `example.org`.
    - Tap «✖️ انصراف»; no crawl is needed.
    - `sources list` prints the same count on its last line.
11. **Stop safely** with `Ctrl+C`. A running crawl finishes its current source first. The status
    loops stop, and the lock is released.

## Phase 3 acceptance checklist

- [ ] Elapsed time moves during a long source; there is no frozen message and no percentages.
- [ ] No estimate is shown without history; an estimate appears after three successful runs.
- [ ] The result shows the actual total duration and the separate counts.
- [ ] An invalid Instagram address keeps the conversation on the same step.
- [ ] A duplicate account names the existing source ID.
- [ ] Adding a source never starts a crawl, and no password is ever requested.
- [ ] An unsupported website is stored inactive and has no enable button.
- [ ] Davvvat Website cannot be enabled from the bot.
- [ ] Archive and restore keep runs, Excel and decisions; a restored source comes back paused.
- [ ] While a crawl runs, source changes are refused with an explanation.
- [ ] `sources list` and the bot agree on the active sources.

## Known limitations (Phase 3)

- **Estimates need local history.** The first runs of a source (or a new item limit) show elapsed
  time only. Estimates are ranges from this computer's past runs, not guarantees.
- **Instagram access is verified only by a crawl.** Adding an account does not open Chrome.
- **Website support is limited to existing adapters.** New sites with another layout stay
  «در انتظار پشتیبانی» until an adapter is added in code and reviewed.
- **Source management is bot-only.** The CLI shows the effective registry
  (`sources list`), but changes are made from the bot or by editing the overlay file carefully
  while the bot is stopped.
- **Conversation state is in memory.** A restart cancels an unfinished add-source flow
  (nothing is saved).

## Windows auto-start readiness (documentation only; nothing is installed)

The bot can later start automatically when the owner logs on. **No scheduled task is created by
this branch.** The bot only works while this PC is on, awake, logged in and online; it does not
run when the PC is off, asleep or offline, and there is no paid hosting.

Requirements for a future Task Scheduler setup:

- **Trigger:** "At log on" of the owner account; "Run only when user is logged on". The
  Instagram Chrome profile needs the interactive desktop session. No administrator rights and
  no "highest privileges".
- **Action:** `<repo>\.venv\Scripts\python.exe -m gatherradar telegram run`, with "Start in"
  set to the repository folder so `config/` and `data/` resolve.
- **Credentials:** `GATHERRADAR_TELEGRAM_BOT_TOKEN` and `GATHERRADAR_TELEGRAM_OWNER_ID` stay
  user environment variables (never in the task definition or a script file).
- **Network:** "Start only if a network connection is available". Startup already retries
  `getMe` 3 times with backoff and long polling retries on its own. The task should also restart
  on failure (for example every 1 minute, at most 3 times).
- **Single instance:** the existing `data/telegram/bot.lock` refuses a second poller on this PC.
  Set the task to "Do not start a new instance". Never run the same token on two computers;
  Telegram reports a conflict and the bot stops.
- **Graceful shutdown:** `Ctrl+C` lets the current source finish. Ending the task from Task
  Scheduler kills the process instead; the next start marks the job as interrupted and nothing
  half-written is reported as finished. Prefer stopping from the console window.
- **Logs:** today logs go to the console. A future wrapper should redirect them to
  `data/logs/telegram.log` with size-based rotation (for example 5 × 1 MB). Logs stay token-free
  thanks to the existing redaction filter.
- **Manual control (later):** run, end, disable and enable with `schtasks /Run`, `/End`,
  `/Change /DISABLE`, `/Change /ENABLE` on the task name, or in the Task Scheduler UI.
