<script setup>
/** Vendor */
import { DateTime } from "luxon"

/** UI */
import Button from "@/components/ui/Button.vue"
import Tooltip from "@/components/ui/Tooltip.vue"
import AmountInCurrency from "@/components/AmountInCurrency.vue"

/** Services */
import { comma, space, formatBytes } from "@/services/utils"

/** API */
import { fetchBlocks, fetchBlocksCount } from "@/services/api/block"

useExplorerSeo({
	title: () => "Blocks - Nubit Explorer",
	description: () => "Blocks in the Nubit Blockchain. Hash, proposer, transactions count, events, blobs size and fee are shown.",
	image: "/img/seo/blocks.png",
})

const route = useRoute()
const router = useRouter()

const PAGE_SIZE = 20

const isRefetching = ref(false)
const blocks = ref([])
const count = ref(0)

/** 本地兜底状态：仅在索引 API 不可用时出现 */
const isCached = ref(false)
const cacheUpdatedAt = ref(null)
const cacheUnavailable = ref(false)
const cachedBlocks = ref([])

const hintedBlock = ref(route.query.block)

const page = ref(route.query.page ? parseInt(route.query.page) : 1)
const pages = computed(() => Math.max(1, Math.ceil(count.value / PAGE_SIZE)))

// 只有在 API 失败时才会请求，API 正常时不会读取本地文件。
// useRequestFetch 让 SSR 阶段也能安全访问同源内部接口。
const requestFetch = useRequestFetch()

const loadCachedPage = async () => {
	if (!cachedBlocks.value.length) {
		let document
		try {
			document = await requestFetch("/api/recent/blocks")
		} catch (error) {
			console.error(error)
			return false
		}
		if (!document || !Array.isArray(document.blocks)) return false
		cachedBlocks.value = document.blocks
		cacheUpdatedAt.value = document.updatedAt || null
	}

	if (!cachedBlocks.value.length) return false

	isCached.value = true
	cacheUnavailable.value = false
	count.value = cachedBlocks.value.length
	blocks.value = cachedBlocks.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE)
	return true
}

const loadPage = async () => {
	const [countResult, blocksResult] = await Promise.all([
		fetchBlocksCount(),
		fetchBlocks({ limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE }),
	])

	const rawCount = countResult?.data?.value
	const apiCount = rawCount === null || rawCount === undefined || rawCount === "" ? NaN : Number(rawCount)
	const rows = blocksResult?.data?.value
	const apiFailed = Boolean(countResult?.error?.value || blocksResult?.error?.value)

	if (!apiFailed && Number.isSafeInteger(apiCount) && apiCount >= 0 && Array.isArray(rows)) {
		count.value = apiCount
		blocks.value = rows
		isCached.value = false
		cacheUpdatedAt.value = null
		cacheUnavailable.value = false
		// 丢掉内存里的兜底快照，避免下次故障时使用过期数据。
		cachedBlocks.value = []
		return
	}

	// 索引 API 超时或异常：回退到本地留存，页面继续渲染同样的表格。
	if (await loadCachedPage()) return

	count.value = 0
	blocks.value = []
	cacheUnavailable.value = true
}

await loadPage()

if (page.value > pages.value) throw createError({ statusCode: 404, statusMessage: "Page not found", fatal: true })

/** Refetch blocks */
watch(
	() => page.value,
	async () => {
		isRefetching.value = true

		await loadPage()

		isRefetching.value = false

		router.replace({ query: { page: page.value } })
	},
)

const handlePrev = () => {
	if (page.value === 1) return

	page.value -= 1
}

const handleNext = () => {
	if (page.value === pages.value) return

	page.value += 1
}

const handleLast = async () => {
	if (isCached.value) {
		page.value = pages.value
		return
	}

	const { data: blocksCount } = await fetchBlocksCount()
	count.value = blocksCount.value

	page.value = pages.value
}

const cachedAtLabel = computed(() => {
	if (!cacheUpdatedAt.value) return "unknown time"
	const time = DateTime.fromISO(cacheUpdatedAt.value)
	return time.isValid ? time.setLocale("en").toFormat("LLL d, t") : "unknown time"
})
</script>

<template>
	<Flex direction="column" wide :class="$style.wrapper">
		<Breadcrumbs
			:items="[
				{ link: '/', name: 'Home' },
				{ link: '/blocks', name: `Blocks` },
			]"
			:class="$style.breadcrumbs"
		/>

		<Flex wide direction="column" gap="0">
			<Flex justify="between" :class="$style.header">
				<Flex align="center" gap="8">
					<Text as="h1" size="20" weight="600" color="primary">Blocks</Text>
				</Flex>

				<Flex align="center" gap="6">
					<Button @click="page = 1" type="secondary" size="mini" :disabled="page === 1">
						<Icon name="arrow-left-stop" size="12" color="primary" />
					</Button>
					<Button type="secondary" @click.prevent="handlePrev" size="mini" :disabled="page === 1" :link="!(page === 1) ? router.resolve({ query: { ...route.query, page: page - 1 } }).href : undefined" aria-label="Previous page">
						<Icon name="arrow-left" size="12" color="primary" />
					</Button>

					<Button type="secondary" size="mini" disabled>
						<Text class="openSans_font" size="12" weight="600" color="primary"> {{ comma(page) }} of {{ comma(pages) }} </Text>
					</Button>

					<Button @click.prevent="handleNext" type="secondary" size="mini" :disabled="page === pages" :link="!(page === pages) ? router.resolve({ query: { ...route.query, page: page + 1 } }).href : undefined" aria-label="Next page">
						<Icon name="arrow-right" size="12" color="primary" />
					</Button>
					<Button @click="handleLast" type="secondary" size="mini" :disabled="page === pages">
						<Icon name="arrow-right-stop" size="12" color="primary" />
					</Button>
				</Flex>
			</Flex>

			<Flex direction="column" wide :class="[$style.table, isRefetching && $style.disabled]">
				<Flex v-if="isCached || cacheUnavailable" align="center" gap="8" :class="$style.fallback_notice" data-testid="blocks-cache-notice">
					<Icon name="info" size="14" color="yellowNew" />
					<Text v-if="isCached" size="12" weight="600" color="yellowNew">
						Index API unavailable — showing cached data from {{ cachedAtLabel }}
					</Text>
					<Text v-else size="12" weight="600" color="yellowNew">
						Index API unavailable and no cached data is available yet
					</Text>
				</Flex>

				<div :class="$style.table_scroller">
					<table>
						<thead>
							<tr>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Height</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Time</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Proposer</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Hash</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Txs</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Events</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Blobs</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Blobs Size</Text></th>
								<th><Text size="12" weight="600" color="tertiary" noWrap>Total Fees</Text></th>
							</tr>
						</thead>

						<tbody>
							<tr v-for="block in blocks" :key="block">
								<td style="width: 1px">
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Outline>
												<Flex align="center" gap="6">
													<Icon
														name="block"
														size="14"
														:color="hintedBlock == block.height ? 'blue' : 'yellowNew'"
													/>

													<Text class="rubik_font" size="13" weight="600" color="yellowNew" tabular>{{
														comma(block.height)
													}}</Text>
												</Flex>
											</Outline>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex justify="center" direction="column" gap="6">
											<Text size="12" weight="600" color="primary">
												{{
													DateTime.fromISO(block.time).toRelative({
														locale: "en",
														style: "short",
													})
												}}
											</Text>
											<Text size="12" weight="500" color="tertiary">
												{{ DateTime.fromISO(block.time).setLocale("en").toFormat("LLL d, t") }}
											</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Tooltip v-if="block.hash" delay="500">
												<template #default>
													<Flex direction="column" gap="4">
														<Text
															size="12"
															height="120"
															weight="600"
															color="primary"
															:class="$style.proposer_moniker"
														>
															{{ block.proposer.moniker }}
														</Text>

														<Flex align="center" gap="6">
															<Text size="12" weight="600" color="tertiary" mono>
																{{ block.proposer.cons_address.slice(0, 4) }}
															</Text>
															<Flex align="center" gap="3">
																<div v-for="dot in 3" :key="dot" class="dot" />
															</Flex>
															<Text size="12" weight="600" color="tertiary" mono>
																{{
																	block.proposer.cons_address.slice(
																		block.proposer.cons_address.length - 4,
																		block.proposer.cons_address.length,
																	)
																}}
															</Text>
															<CopyButton :text="block.proposer.cons_address" size="14" />
														</Flex>
													</Flex>
												</template>

												<template #content> {{ space(block.proposer.cons_address) }} </template>
											</Tooltip>
											<Text v-else size="13" weight="600" color="secondary">Genesis</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Tooltip v-if="block.hash" delay="500">
												<template #default>
													<Flex align="center" gap="8">
														<Text class="rubik_font" size="13" weight="600" color="primary" mono>{{
															block.hash.slice(0, 4)
														}}</Text>

														<Flex align="center" gap="3">
															<div class="rubik_font dot" v-for="dot in 3" :key="dot" />
														</Flex>

														<Text class="rubik_font" size="13" weight="600" color="primary" mono>
															{{ block.hash.slice(block.hash.length - 4, block.hash.length) }}
														</Text>

														<CopyButton :text="block.hash" />
													</Flex>
												</template>

												<template #content> {{ space(block.hash) }} </template>
											</Tooltip>
											<Text v-else size="13" weight="600" color="secondary">Genesis</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Text size="13" weight="600" color="primary">
												{{ block.stats.tx_count }}
											</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Text size="13" weight="600" color="primary">
												{{ block.stats.events_count }}
											</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Text size="13" weight="600" color="primary">
												{{ block.stats.blobs_count }}
											</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center">
											<Text size="13" weight="600" color="primary">
												{{ formatBytes(block.stats.blobs_size) }}
											</Text>
										</Flex>
									</NuxtLink>
								</td>
								<td>
									<NuxtLink :to="`/block/${block.height}`">
										<Flex align="center" gap="4">
											<AmountInCurrency
												:amount="{ value: block.stats.fee, decimal: 6 }"
												:styles="{ amount: { size: '13' } }"
											/>
										</Flex>
									</NuxtLink>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</Flex>
		</Flex>
	</Flex>
</template>

<style module>
.wrapper {
	max-width: calc(var(--base-width) + 48px);

	padding: 40px 24px 60px 24px;
}

.breadcrumbs {
	margin-bottom: 16px;
}

.header {
	border-radius: 8px 8px 0 0;
	background: rgba(255, 255, 255, 0.1);
	padding: 20px;
}

.table_scroller {
	overflow-x: auto;
}

tbody tr td {
	border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.table {
	border-radius: 0 0 8px 8px;
	background: rgba(255, 255, 255, 0.1);
	padding-bottom: 12px;
	padding: 0 20px 20px 20px;
	transition: all 0.2s ease;

	& table {
		width: 100%;
		height: fit-content;

		border-spacing: 0px;

		& tbody {
			& tr {
				cursor: pointer;

				transition: all 0.05s ease;

				&:hover {
					background: var(--op-5);
				}

				&:active {
					background: var(--op-8);
				}
			}
		}

		& tr th {
			text-align: left;
			padding: 0;
			padding-right: 16px;
			padding-top: 16px;
			padding-bottom: 8px;

			& span {
				display: flex;
			}

			&:first-child {
				padding-left: 16px;
			}
		}

		& tr td {
			padding: 0;

			white-space: nowrap;

			&:first-child {
				padding-left: 16px;
			}

			& > a {
				display: flex;

				min-height: 44px;

				padding-right: 24px;
			}
		}
	}
}

.proposer_moniker {
	max-width: 160px;

	text-overflow: ellipsis;
	overflow: hidden;
}

.table.disabled {
	opacity: 0.5;
	pointer-events: none;
}

.fallback_notice {
	padding: 12px 16px 0;
}

@media (max-width: 500px) {
	.wrapper {
		padding: 32px 12px;
	}

	.header {
		gap: 16px;

		height: initial;

		padding: 16px;
	}
}
</style>
