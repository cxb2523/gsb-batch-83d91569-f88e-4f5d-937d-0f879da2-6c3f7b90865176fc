// Menu scraping - RU menu scrape plus daily bulletin
// Schedules menu sends, update checks and calendar cron
// Builds summary with weather and calendar events
import { analyzeCalendarEvents, type ClassifiedCalendar } from '@util/calendarAnalytics.ts'
import { type ParsedMenuResult } from '@util/menuParser.ts'
import { updateCalendarCache } from '@plugin/calendarParser.ts'
import { getAllowedTagsList } from '@plugin/groupAnnouncer.ts'
import { generateDailySummary } from '@util/dailySummary.ts'
import { randomDelay } from '@util/functions.ts'
import { fetchWeatherForecast } from '@util/weather.ts'
import { sendMsg } from '@util/msgAbstractions.ts'
import { getOldMenuText, persistMenuCache, scrapURMenu, updateMenuDate } from '@util/menuScraper.ts'
import cache from '@plugin/cache.ts'

export default scrapURMenu

export function scheduleURMenuMsg() {
	// Deno.cron runs in UTC, so we translate UTC-3 (America/Sao_Paulo) to UTC
	// 6 AM UTC-3 = 9 AM UTC
	Deno.cron('Send UR Menu', '0 9 * * *', () => sendURMenu())

	// schedule checking for updates (7 AM - 7 PM UTC-3 = 10 AM - 10 PM UTC)
	Deno.cron('Check for Menu Updates', '*/15 10-22 * * 1-5', checkForUpdates)

	// schedule calendar update every Sunday at 3 AM UTC-3 (6 AM UTC)
	Deno.cron('Update Calendar Cache', '0 6 * * 7', async () => {
		try {
			await updateCalendarCache()
			print('MENUSCRAP', 'Calendar cache updated', 'green')
		} catch (e) {
			print('MENUSCRAP', 'Failed to update calendar cache', e, 'red')
		}
	})

	// run once on startup
	updateCalendarCache().catch(() => null)
}

async function checkForUpdates() {
	await randomDelay()
	const outcome = await scrapURMenu()
	if (outcome.status !== 'success' || !outcome.menu?.hasMenu) {
		if (outcome.status !== 'success' && outcome.status !== 'no-menu') {
			print('MENUSCRAP', `Menu update check failed: ${outcome.reason}`, 'yellow')
		}
		return
	}
	const menu = outcome.menu

	const oldMenuText = await getOldMenuText()
	if (oldMenuText === menu.rawFullText) return
	print('MENUSCRAP', 'Menu updated', 'blue')
	sendURMenu(menu, 1)
	await cache.save()
}

// send the Menu Msg to all groups saved by the "#all" tag + some others
export async function sendURMenu(
	menuData: ParsedMenuResult | null = null,
	updated = 0,
) {
	await randomDelay()
	const { day, month, year } = updateMenuDate()
	const date = new Date()

	// 1. Fetch menu if not provided
	let menu = menuData
	if (!menu) {
		const outcome = await scrapURMenu()
		if (outcome.status !== 'success') {
			print(
				'MENUSCRAP',
				`Menu scrape failed (${outcome.status}): ${outcome.reason}`,
				'yellow',
			)
		}
		menu = outcome.menu
	}

	// 2. Fetch weather forecast in parallel
	const weather = await fetchWeatherForecast()

	// 3. Process calendar events
	let classifiedCalendar: ClassifiedCalendar | null = null
	try {
		const calendarPath = `conf/gen/cache/calendar_${year}.json`
		let rawCalendar = await Deno.readTextFile(calendarPath).catch(() => null)
		if (!rawCalendar) {
			print('MENUSCRAP', 'Calendar cache missing. Fetching now...', 'yellow')
			await updateCalendarCache().catch((e) =>
				print('MENUSCRAP', 'Error initializing calendar cache', e, 'red')
			)
			rawCalendar = await Deno.readTextFile(calendarPath).catch(() => null)
		}

		if (rawCalendar) {
			const events: Record<string, any[]> = JSON.parse(rawCalendar)
			classifiedCalendar = analyzeCalendarEvents(events, date)
		}
	} catch (e: any) {
		print('MENUSCRAP', 'Error reading calendar cache', e.stack || e, 'red')
	}

	const hasMenu = Boolean(menu && menu.hasMenu)
	const hasCalendar = Boolean(classifiedCalendar && classifiedCalendar.hasEvents)

	if (!hasMenu && !hasCalendar) {
		print('MENUSCRAP', 'No menu and no calendar events to send.', 'yellow')
		return
	}

	// 4. Generate AI summary with deterministic fallback
	const dateStr = `${day}/${month}`

	const summary = await generateDailySummary({
		dateStr,
		weather,
		menu,
		calendar: classifiedCalendar,
	})

	// 5. Construct full message
	let msg = ''
	if (updated) {
		msg = `🔄 *ATUALIZAÇÃO DO CARDÁPIO* - *${dateStr}*\n\n`
	}

	msg += summary.trim()

	const groups = Deno.env.get('DEV')
		? [Deno.env.get('GROUPS0')!]
		: getAllowedTagsList().concat('5527997014112-1491836324@g.us')

	for (const g of groups) {
		if (!g) continue
		const msgCtx = await sendMsg.bind(g)(msg)
		await randomDelay()
		await sendMsg.bind(g)({ pin: msgCtx.msg.key, time: 86_400, type: 1 })
		await randomDelay()
	}

	// persist only real menus; a failed scrape must never clobber the last good cache
	await persistMenuCache(menu)
}
