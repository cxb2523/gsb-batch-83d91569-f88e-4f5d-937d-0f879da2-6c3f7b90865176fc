import type { PageSession } from '../cdp/page.ts';
import type { CityRef, FlightFetcher, PageFetch } from './types.ts';
import { pageFetchFromBody } from './parse.ts';

const MONTHS_NOM = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

/** "Октябрь 2026" → { year: 2026, month: 10 }; null when the title is not in that shape. */
function monthIndexOf(title: string): { year: number; month: number } | null {
  const m = title.match(/([А-Яа-яЁё]+)\s+(\d{4})/);
  if (!m) return null;
  const month = MONTHS_NOM.findIndex((name) => name.toLowerCase() === m[1].toLowerCase()) + 1;
  return month ? { year: Number(m[2]), month } : null;
}

export interface BrowserFetcherOptions {
  page: PageSession;
  /** Origin of the fixture site, e.g. `http://localhost:1234/`. */
  baseUrl: string;
  from: CityRef;
  to: CityRef;
  /** Called with progress notes; the collector does not need them but a CLI can print them. */
  onAction?: (note: string) => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Collects pages by driving the fixture site itself: on flights.html it picks both cities from the autocomplete,
 * picks the departure day in the low-fare calendar and submits; on results.html it presses "Показать ещё" for
 * every following page. The JSON the page requests is captured from the page's own network traffic, so the
 * records are literally produced by the same `/api/flights` calls the API path makes.
 *
 * Every DOM step is bounded by the page deadline and every failure is reported as a PageFetch, never thrown.
 */
export class BrowserFlightFetcher implements FlightFetcher {
  readonly path = 'browser' as const;
  private readonly page: PageSession;
  private readonly baseUrl: string;
  private readonly from: CityRef;
  private readonly to: CityRef;
  private readonly onAction: (note: string) => void;
  private consentHandled = false;
  private networkReady = false;
  private currentDate: string | null = null;
  private currentPage = 0;

  constructor(opts: BrowserFetcherOptions) {
    this.page = opts.page;
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.from = opts.from;
    this.to = opts.to;
    this.onAction = opts.onAction ?? (() => {});
    if (!opts.from.name || !opts.to.name) throw new Error('the browser path needs city names (from.name, to.name) for the autocomplete');
  }

  private get sessionId(): string | undefined { return this.page.sessionId; }

  private send<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return this.page.send<T>(method, params);
  }

  private async backendNode(selector: string): Promise<number> {
    const { root } = await this.send<{ root: { nodeId: number } }>('DOM.getDocument', { depth: 0 });
    const { nodeId } = await this.send<{ nodeId: number }>('DOM.querySelector', { nodeId: root.nodeId, selector });
    if (!nodeId) throw new Error(`element not found: ${selector}`);
    const { node } = await this.send<{ node: { backendNodeId: number } }>('DOM.describeNode', { nodeId });
    return node.backendNodeId;
  }

  private async clickSelector(selector: string): Promise<void> {
    await this.page.click(await this.backendNode(selector));
  }

  private async exists(selector: string): Promise<boolean> {
    return this.page.evaluate<boolean>(`!!document.querySelector(${JSON.stringify(selector)})`).catch(() => false);
  }

  private async waitFor(selector: string, timeoutMs: number): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (await this.exists(selector)) return;
      await sleep(50);
    }
    throw new Error(`timed out waiting for ${selector}`);
  }

  /**
   * Registers a listener for the first `/api/flights` request matching `pred` and resolves with its parsed body.
   * The returned `cancel` unregisters it (used when the page flow fails before the request is ever made).
   */
  private capture(pred: (u: URL) => boolean, timeoutMs: number): { promise: Promise<PageFetch>; cancel: () => void } {
    let off: () => void = () => {};
    let settled = false;
    let requestId = '';
    let httpStatus: number | undefined;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const promise = new Promise<PageFetch>((resolve) => {
      const finish = (v: PageFetch) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        off();
        resolve(v);
      };
      timer = setTimeout(() => finish({ outcome: 'timeout', error: `no /api/flights response within ${timeoutMs}ms` }), timeoutMs);
      off = this.page.conn.on((method: string, params: any, sessionId?: string) => {
        if (sessionId !== this.sessionId) return;
        if (method === 'Network.requestWillBeSent') {
          try { if (pred(new URL(params.request.url))) requestId = params.requestId; } catch { /* not a URL */ }
        } else if (method === 'Network.responseReceived' && params.requestId === requestId) {
          httpStatus = params.response.status;
        } else if (method === 'Network.loadingFinished' && params.requestId === requestId) {
          this.send<{ body: string; base64Encoded: boolean }>('Network.getResponseBody', { requestId })
            .then((r) => {
              const body = r.base64Encoded ? Buffer.from(r.body, 'base64').toString('utf8') : r.body;
              if (httpStatus !== undefined && (httpStatus < 200 || httpStatus >= 300)) {
                finish({ outcome: 'failed', httpStatus, error: `HTTP ${httpStatus}` });
              } else {
                finish(pageFetchFromBody(body, httpStatus ?? 200));
              }
            })
            .catch((e) => finish({ outcome: 'failed', httpStatus, error: e instanceof Error ? e.message : String(e) }));
        } else if (method === 'Network.loadingFailed' && params.requestId === requestId) {
          finish({ outcome: 'failed', httpStatus, error: params.errorText ?? 'request failed' });
        }
      });
    });
    return { promise, cancel: () => { settled = true; if (timer) clearTimeout(timer); off(); } };
  }

  private flightsRequest(date: string, page: number): (u: URL) => boolean {
    return (u) => u.pathname === '/api/flights'
      && u.searchParams.get('from') === this.from.code
      && u.searchParams.get('to') === this.to.code
      && u.searchParams.get('date') === date
      && Number(u.searchParams.get('page') ?? '0') === page;
  }

  async fetchPage(date: string, page: number, timeoutMs: number): Promise<PageFetch> {
    try {
      if (!this.networkReady) {
        // Response bodies are only readable while the inspector keeps them buffered (PageSession enables
        // Network without buffers, so re-enable it with room for the JSON payloads this collector reads).
        await this.send('Network.enable', { maxTotalBufferSize: 20_000_000, maxResourceBufferSize: 5_000_000 });
        this.networkReady = true;
      }
      if (date !== this.currentDate) {
        this.currentDate = date;
        this.currentPage = 0;
        return await this.search(date, timeoutMs);
      }
      if (page !== this.currentPage + 1) {
        return { outcome: 'failed', error: `cannot page to ${page}: the page flow is at ${this.currentPage} for ${date}` };
      }
      return await this.loadMore(date, page, timeoutMs);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const timeout = /timed out|timeout/i.test(msg);
      return { outcome: timeout ? 'timeout' : 'failed', error: msg };
    }
  }

  /** Runs the search form on flights.html for one day and captures the first results page. */
  private async search(date: string, timeoutMs: number): Promise<PageFetch> {
    this.onAction(`open flights.html for ${date}`);
    await this.page.navigate(`${this.baseUrl}/flights.html`);
    await this.page.waitForSettle({ maxMs: Math.min(timeoutMs, 5_000) });
    await this.dismissConsent(timeoutMs);
    await this.pickCity('#f-origin', '#origin', this.from, timeoutMs);
    await this.pickCity('#f-dest', '#f-dest input', this.to, timeoutMs);
    await this.pickDate(date, timeoutMs);

    const cap = this.capture(this.flightsRequest(date, 1), timeoutMs);
    try {
      this.onAction(`submit ${this.from.code}→${this.to.code} ${date}`);
      await this.clickSelector('#search button[type="submit"]');
      await this.waitFor('#more, #list .ticket, #err:not(:empty)', Math.min(timeoutMs, 10_000));
      const err = await this.page.evaluate<string>('document.getElementById("err")?.textContent ?? ""').catch(() => '');
      if (err) {
        cap.cancel();
        return { outcome: 'failed', error: `search form rejected the input: ${err}` };
      }
    } catch (e) {
      cap.cancel();
      throw e;
    }
    const res = await cap.promise;
    if (res.outcome === 'success') this.currentPage = 1;
    return res;
  }

  private async dismissConsent(timeoutMs: number): Promise<void> {
    if (this.consentHandled) return;
    const deadline = Date.now() + Math.min(timeoutMs, 2_000);
    while (Date.now() < deadline) {
      if (await this.exists('#c-ok')) {
        await this.clickSelector('#c-ok');
        this.consentHandled = true;
        return;
      }
      await sleep(100);
    }
    this.consentHandled = true; // no wall on this run; do not wait for it again
  }

  /** Types a city name, waits for the autocomplete and clicks the suggestion with the wanted IATA code. */
  private async pickCity(fieldContainer: string, inputSelector: string, city: CityRef, timeoutMs: number): Promise<void> {
    this.onAction(`pick ${city.code} in ${fieldContainer}`);
    await this.page.type(await this.backendNode(inputSelector), city.name ?? city.code, { mode: 'insert' });
    await this.waitFor(`${fieldContainer} .suggest li`, Math.min(timeoutMs, 4_000));
    const idx = await this.page.evaluate<number>(`(() => {
      const items = [...document.querySelectorAll(${JSON.stringify(`${fieldContainer} .suggest li`)})];
      const want = ${JSON.stringify(city.code)};
      return items.findIndex((li) => (li.textContent || '').includes(want));
    })()`);
    if (idx < 0) throw new Error(`no autocomplete suggestion for ${city.code} in ${fieldContainer}`);
    await this.clickSelector(`${fieldContainer} .suggest li:nth-child(${idx + 1})`);
    const code = await this.page.evaluate<string>(`document.querySelector(${JSON.stringify(inputSelector)})?.dataset.code ?? ''`);
    if (code !== city.code) throw new Error(`autocomplete picked "${code}" instead of ${city.code}`);
  }

  /** Opens the low-fare calendar, pages it to the target month and clicks the day. */
  private async pickDate(date: string, timeoutMs: number): Promise<void> {
    this.onAction(`pick ${date} in the calendar`);
    const [y, m] = date.split('-').map(Number);
    await this.clickSelector('#f-date');
    await this.waitFor('#f-date .cal .title', Math.min(timeoutMs, 4_000));
    for (let i = 0; i < 36; i++) {
      // Month titles are names, not sortable text: compare them by (year, month number), never alphabetically.
      const title = (await this.page.evaluate<string>('document.querySelector("#f-date .cal .title")?.textContent ?? ""')).trim();
      const cur = monthIndexOf(title);
      if (!cur) throw new Error(`unreadable calendar title "${title}"`);
      if (cur.year === y && cur.month === m) break;
      const nextMonth = cur.year < y || (cur.year === y && cur.month < m);
      await this.clickSelector(`#f-date .cal ${nextMonth ? '.next' : '.prev'}`);
      await sleep(250);
      if (i === 35) throw new Error(`calendar never reached ${MONTHS_NOM[m - 1]} ${y}`);
    }
    const selector = `#f-date .cal button[data-date="${date}"]`;
    await this.waitFor(selector, Math.min(timeoutMs, 4_000));
    await this.clickSelector(selector);
    const picked = await this.page.evaluate<string>('document.getElementById("date-val")?.textContent ?? ""');
    if (!picked || picked === 'Дата') throw new Error(`calendar did not accept ${date}`);
  }

  /** Presses "Показать ещё" on the results page and captures the next page's request. */
  private async loadMore(date: string, page: number, timeoutMs: number): Promise<PageFetch> {
    this.onAction(`load page ${page} for ${date}`);
    if (!(await this.exists('#more'))) return { outcome: 'failed', error: `no "show more" button for page ${page}` };
    const cap = this.capture(this.flightsRequest(date, page), timeoutMs);
    try {
      await this.clickSelector('#more');
    } catch (e) {
      cap.cancel();
      throw e;
    }
    const res = await cap.promise;
    if (res.outcome === 'success' || res.outcome === 'empty') this.currentPage = page;
    return res;
  }

  async dispose(): Promise<void> {
    // The caller owns the page/tab; nothing to release here.
  }
}
