// menuScraper - fetch the RU menu page and return a typed outcome
// - retries only network errors and 5xx; 4xx fails immediately
// - owns menu cache persistence so failures never clobber the last good menu
import { type ParsedMenuResult, parseMenuHtml } from '@util/menuParser.ts'
import { delay, randomDelay } from '@util/functions.ts'

export type ScrapStatus = 'success' | 'network-error' | 'http-error' | 'no-menu'

// ScrapMenuOutcome: what a scrape attempt produced, readable by callers
export interface ScrapMenuOutcome {
	// success | network-error | http-error | no-menu
	status: ScrapStatus
	// HTTP status code, null when no response was received
	httpStatus: number | null
	// how many retries were performed before this outcome
	retries: number
	// short human-readable reason
	reason: string
	// parsed menu on success/no-menu, null on fetch errors
	menu: ParsedMenuResult | null
}

export const MENU_CACHE_PATH = 'conf/gen/cache/menu.txt'
export const MENU_FETCH_TIMEOUT_MS = 10_000
export const MENU_MAX_RETRIES = 3

let day = '',
	month = '',
	year = ''
const numPadding = (n: number) => (n < 10 ? '0' + n : n.toString()) // 4 => 04

export function updateMenuDate() {
	const date = new Date()
	day = global.menuDay || numPadding(date.getDate())
	month = numPadding(date.getMonth() + 1)
	year = date.getFullYear().toString()
	return { day, month, year }
}
updateMenuDate()

const log = (...args: any[]) => {
	if (typeof print === 'function') print(...args)
}

// wait between retries: fixed delay plus jitter (injectable so tests stay fast)
const defaultRetryWait = async () => {
	await delay(60_000)
	await randomDelay()
}

// scrap university's restaurant menu
export async function scrapURMenu(
	fetchImpl: typeof fetch = fetch,
	wait: () => Promise<unknown> = defaultRetryWait,
): Promise<ScrapMenuOutcome> {
	updateMenuDate()
	const url = `https://restaurante.saomateus.ufes.br/cardapio/${year}-${month}-${day}`
	let retries = 0

	while (true) {
		let res: Response
		let txt = ''
		try {
			// Timeout so a hung RU site never wedges the bulletin; retries handle transient drops.
			res = await fetchImpl(url, { signal: AbortSignal.timeout(MENU_FETCH_TIMEOUT_MS) })
			if (res.ok) txt = await res.text()
		} catch (e: any) {
			log('MENUSCRAP', 'Error scraping menu', e?.stack || e, 'red')
			if (retries >= MENU_MAX_RETRIES) {
				log('MENUSCRAP', 'Max retries reached, giving up', 'red')
				return {
					status: 'network-error',
					httpStatus: null,
					retries,
					reason: `Network error after ${retries} retries: ${e?.message || e}`,
					menu: null,
				}
			}
			retries++
			await wait()
			continue
		}

		if (!res.ok) {
			// only 5xx is worth retrying; 4xx means the page/date is really not there
			if (res.status >= 500 && retries < MENU_MAX_RETRIES) {
				log('MENUSCRAP', `Menu fetch failed with HTTP ${res.status}, retrying`, 'yellow')
				retries++
				await wait()
				continue
			}
			return {
				status: 'http-error',
				httpStatus: res.status,
				retries,
				reason: retries > 0
					? `HTTP ${res.status} after ${retries} retries`
					: `HTTP ${res.status}`,
				menu: null,
			}
		}

		const menu = parseMenuHtml(txt)
		if (!menu.hasMenu) {
			// page loaded but no meal sections: report it, never fall back to the old cache
			return {
				status: 'no-menu',
				httpStatus: res.status,
				retries,
				reason: 'Page loaded but no meal sections could be parsed',
				menu,
			}
		}

		return { status: 'success', httpStatus: res.status, retries, reason: 'OK', menu }
	}
}

let oldMenuText = ''

// last menu text seen; lazily loaded from the cache file
export async function getOldMenuText(cachePath = MENU_CACHE_PATH): Promise<string> {
	if (!oldMenuText) oldMenuText = await Deno.readTextFile(cachePath).catch(() => '')
	return oldMenuText
}

// persist a freshly scraped menu; failures (null/empty menu) never touch the cache
export async function persistMenuCache(
	menu: ParsedMenuResult | null,
	cachePath = MENU_CACHE_PATH,
): Promise<boolean> {
	if (!menu?.rawFullText) return false
	await Deno.writeTextFile(cachePath, menu.rawFullText)
	oldMenuText = menu.rawFullText
	return true
}
