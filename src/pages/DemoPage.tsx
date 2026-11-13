import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Map } from '@/components/ui/map';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import {
  AlertTriangle,
  Database,
  Filter,
  Globe,
  Loader2,
  MapPin,
  RefreshCw,
  TrendingUp,
  Users
} from 'lucide-react';
import { useCustomerDistribution } from '@/services/customerDistribution/useCustomerDistribution';
import {
  buildAuditView,
  buildDistributionView,
  type DistributionView
} from '@/services/customerDistribution/viewModel';

/** 统计卡图标与配色，仅负责外观；数字一律来自采集结果。 */
const statCardStyles = {
  totalCustomers: { icon: Users, className: 'from-blue-50 to-indigo-50', iconClass: 'text-blue-600', valueClass: 'text-blue-600' },
  activeCustomers: { icon: Users, className: 'from-green-50 to-emerald-50', iconClass: 'text-green-600', valueClass: 'text-green-600' },
  growthRate: { icon: TrendingUp, className: 'from-purple-50 to-pink-50', iconClass: 'text-purple-600', valueClass: 'text-purple-600' },
  coverage: { icon: Globe, className: 'from-orange-50 to-red-50', iconClass: 'text-orange-600', valueClass: 'text-orange-600' }
} as const;

const DatasetFootnote = ({ sourceLabel }: { sourceLabel: string }) => (
  <p className="text-sm text-gray-500">{sourceLabel}</p>
);

/** 采集加载态：不展示任何地图中心或数字，避免旧区域数据被误读成本次结果。 */
const CollectionLoading = ({
  regionName,
  hint
}: {
  regionName: string;
  hint: string;
}) => (
  <div className="space-y-6" aria-busy="true" aria-live="polite">
    <div className="flex items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-blue-800">
      <Loader2 className="h-5 w-5 animate-spin" />
      <div>
        <div className="font-medium">正在采集“{regionName}”的客户分布…</div>
        <div className="text-sm text-blue-700">{hint}</div>
      </div>
    </div>

    <div className="rounded-xl overflow-hidden border-2 border-gray-200">
      <Skeleton className="h-[500px] w-full rounded-none" />
    </div>

    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {['总客户数', '活跃客户', '增长率', '覆盖国家'].map((label) => (
        <div key={label} className="p-4 rounded-xl border border-gray-200">
          <div className="mb-2 text-sm text-gray-600">{label}</div>
          <Skeleton className="h-8 w-24" />
        </div>
      ))}
    </div>

    <div>
      <h3 className="font-bold text-gray-900 mb-3">主要国家分布</h3>
      <div className="flex flex-wrap gap-2">
        {[1, 2, 3, 4, 5].map((item) => (
          <Skeleton key={item} className="h-7 w-20" />
        ))}
      </div>
    </div>
  </div>
);

/** 区域数据不可用：不显示 0 / NaN，也不沿用上一个区域的数字。 */
const UnavailablePanel = ({ view }: { view: Extract<DistributionView, { kind: 'unavailable' }> }) => (
  <div
    className="rounded-xl border-2 border-red-200 bg-red-50 p-6"
    role="alert"
    data-testid="region-unavailable"
  >
    <div className="flex items-start gap-3">
      <AlertTriangle className="mt-1 h-6 w-6 shrink-0 text-red-600" />
      <div className="space-y-3">
        <div>
          <h3 className="text-lg font-bold text-red-800">
            区域“{view.regionName}”数据不可用
          </h3>
          <p className="mt-1 text-sm text-red-700">
            采集到的记录缺少必需字段或数值非法，已拒绝展示；不会用占位数字或其它区域的数据代替。
          </p>
        </div>
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-800">
          {view.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <div className="grid gap-1 text-sm text-red-700">
          <span>数据来源：{view.sourceLabel}</span>
          <span>数据源更新于：{view.datasetUpdatedAtLabel}</span>
          <span>本次采集于：{view.fetchedAtLabel}（{view.modeLabel}）</span>
        </div>
      </div>
    </div>
  </div>
);

export default function DemoPage() {
  const { state, selectRegion, retryCatalog, datasetUrl } = useCustomerDistribution();
  const view = buildDistributionView(state);
  const audit = buildAuditView(state);
  const [showChainDetails, setShowChainDetails] = useState(false);

  const selectedRegionId = state.selectedRegionId;
  const unavailableRegionId =
    state.current?.status === 'unavailable' ? state.current.regionId : null;
  const isLoading = view.kind === 'loading';

  // 只有采集成功的结果（含失败时保留的上一次成功结果）能提供地图与统计。
  const availableView =
    view.kind === 'available' ? view : view.kind === 'failure' ? view.retained : null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-blue-50">
      {/* Header */}
      <section className="bg-gradient-to-r from-blue-600 to-indigo-700 text-white py-20">
        <div className="container mx-auto px-4">
          <div className="max-w-4xl mx-auto text-center">
            <h1 className="text-5xl font-bold mb-6">在线演示</h1>
            <p className="text-xl text-blue-100">
              体验探客AI获客平台的强大功能
            </p>
          </div>
        </div>
      </section>

      {/* Demo Content */}
      <section className="py-20">
        <div className="container mx-auto px-4">
          <div className="max-w-7xl mx-auto">
            <Tabs defaultValue="map" className="space-y-8">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="map">地图分析</TabsTrigger>
                <TabsTrigger value="heatmap">热力图</TabsTrigger>
                <TabsTrigger value="analytics">数据分析</TabsTrigger>
              </TabsList>

              <TabsContent value="map" className="space-y-6">
                <Card className="border-2" data-testid="region-collection-card">
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between">
                      <span className="flex items-center">
                        <MapPin className="h-6 w-6 mr-3 text-blue-600" />
                        全球客户地图分布
                      </span>
                      <div className="flex items-center space-x-2">
                        <Filter className="h-4 w-4 text-gray-500" />
                        <span className="text-sm text-gray-500">区域筛选</span>
                      </div>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    {state.catalogStatus === 'error' ? (
                      <Alert variant="destructive">
                        <AlertTriangle className="h-4 w-4" />
                        <AlertTitle>演示数据源加载失败</AlertTitle>
                        <AlertDescription>
                          <p>{state.catalogError}</p>
                          <p className="text-xs">数据源位置：{datasetUrl}</p>
                          <Button
                            variant="outline"
                            size="sm"
                            className="mt-2"
                            onClick={retryCatalog}
                          >
                            <RefreshCw className="mr-2 h-4 w-4" />
                            重试
                          </Button>
                        </AlertDescription>
                      </Alert>
                    ) : state.catalogStatus !== 'ready' ? (
                      <div className="flex items-center gap-2 text-sm text-gray-500">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        正在加载区域目录…
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2" data-testid="region-buttons">
                        {state.catalog.map((region) => (
                          <Button
                            key={region.id}
                            variant={selectedRegionId === region.id ? 'default' : 'outline'}
                            onClick={() => selectRegion(region.id)}
                            disabled={state.catalogStatus !== 'ready'}
                            data-testid={`region-button-${region.id}`}
                            data-active={selectedRegionId === region.id ? 'true' : 'false'}
                            className={
                              selectedRegionId === region.id
                                ? 'bg-gradient-to-r from-blue-600 to-indigo-600'
                                : ''
                            }
                          >
                            {region.name}
                            {unavailableRegionId === region.id && (
                              <AlertTriangle className="ml-2 h-4 w-4 text-amber-500" />
                            )}
                            {isLoading && state.pendingRegionId === region.id && (
                              <Loader2 className="ml-2 h-4 w-4 animate-spin" />
                            )}
                          </Button>
                        ))}
                      </div>
                    )}

                    {/* 采集失败：保留上一次成功结果，并把失败原因可见地展示出来。 */}
                    {view.kind === 'failure' && (
                      <Alert variant="destructive" role="alert" data-testid="collection-failure">
                        <AlertTriangle className="h-4 w-4" />
                        <AlertTitle>
                          采集“{view.regionName}”失败，已保留上一次成功结果
                        </AlertTitle>
                        <AlertDescription>
                          <p>{view.reason}</p>
                          <p className="text-xs">
                            {view.retained
                              ? `当前继续展示上一次成功结果：${view.retained.regionName}`
                              : '当前没有可展示的上一次成功结果'}
                          </p>
                        </AlertDescription>
                      </Alert>
                    )}

                    {view.kind === 'loading' ? (
                      <CollectionLoading regionName={view.regionName} hint={view.hint} />
                    ) : view.kind === 'unavailable' ? (
                      <UnavailablePanel view={view} />
                    ) : availableView ? (
                      <>
                        <div
                          className="rounded-xl overflow-hidden border-2 border-gray-200"
                          data-testid="region-map"
                          data-region-id={availableView.regionId}
                          data-lat={availableView.map.lat}
                          data-lng={availableView.map.lng}
                          data-zoom={availableView.map.zoom}
                        >
                          <Map
                            ak="OeTpXHgdUrRT2pPyAPRL7pog6GlMlQzl"
                            option={{
                              lat: availableView.map.lat,
                              lng: availableView.map.lng,
                              zoom: availableView.map.zoom,
                              address: availableView.map.address
                            }}
                            className="w-full h-[500px]"
                          />
                        </div>

                        <div
                          className="grid grid-cols-2 md:grid-cols-4 gap-4"
                          data-testid="region-stats"
                          data-region-id={availableView.regionId}
                        >
                          {availableView.stats.map((stat) => {
                            const style = statCardStyles[stat.key];
                            const Icon = style.icon;
                            return (
                              <div
                                key={stat.key}
                                className={`bg-gradient-to-br ${style.className} p-4 rounded-xl`}
                                data-testid={`stat-card-${stat.key}`}
                              >
                                <div className="flex items-center space-x-2 mb-2">
                                  <Icon className={`h-5 w-5 ${style.iconClass}`} />
                                  <span className="text-sm text-gray-600">{stat.label}</span>
                                </div>
                                <div
                                  className={`text-2xl font-bold ${style.valueClass}`}
                                  data-testid={`stat-value-${stat.key}`}
                                >
                                  {stat.value}
                                </div>
                                {stat.hint && (
                                  <div className="text-xs text-gray-500">{stat.hint}</div>
                                )}
                              </div>
                            );
                          })}
                        </div>

                        <div data-testid="region-countries" data-region-id={availableView.regionId}>
                          <h3 className="font-bold text-gray-900 mb-3">主要国家分布</h3>
                          <div className="flex flex-wrap gap-2">
                            {availableView.countries.map((country) => (
                              <Badge key={country} variant="secondary" className="text-sm py-1 px-3">
                                {country}
                              </Badge>
                            ))}
                          </div>
                        </div>

                        <div
                          className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-600"
                          data-testid="region-provenance"
                        >
                          <div className="font-medium text-gray-800">本次采集</div>
                          <div className="mt-1 grid gap-1">
                            <span>区域：{availableView.regionName}（{availableView.regionId}）</span>
                            <span>数据来源：{availableView.sourceLabel}</span>
                            <span>数据源采集时间：{availableView.collectedAtLabel}</span>
                            <span>页面获取时间：{availableView.fetchedAtLabel}</span>
                            <span>结果类型：{availableView.modeLabel}</span>
                          </div>
                        </div>
                      </>
                    ) : view.kind === 'failure' ? (
                      <div className="rounded-xl border border-dashed border-red-300 bg-red-50 p-8 text-center text-red-700">
                        本次采集失败，且没有可展示的上一次成功结果。请重新选择区域或刷新页面重试。
                      </div>
                    ) : (
                      <div className="py-16 text-center text-gray-500">
                        {state.catalogStatus === 'ready'
                          ? '请选择一个区域以采集客户分布数据。'
                          : '等待演示数据源就绪…'}
                      </div>
                    )}

                    <div className="border-t pt-4">
                      <div
                        className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-900"
                        data-testid="collection-audit-strip"
                        data-request-count={audit.requestCount}
                        data-cache-hits={audit.cacheHits}
                        data-coalesced={audit.coalescedSelections}
                        data-stale-ignored={audit.staleResultsIgnored}
                      >
                        <span className="font-medium text-blue-800">采集核对：</span>
                        <span>请求 {audit.requestCount} 次</span>
                        <span>缓存命中 {audit.cacheHits} 次</span>
                        <span>请求合并 {audit.coalescedSelections} 次</span>
                        <span>过期结果丢弃 {audit.staleResultsIgnored} 次</span>
                        <span>最近一次选择：{audit.lastSelectionLabel}</span>
                      </div>

                      <button
                        type="button"
                        className="flex items-center gap-2 text-sm font-medium text-blue-700"
                        onClick={() => setShowChainDetails((value) => !value)}
                      >
                        <Database className="h-4 w-4" />
                        {showChainDetails ? '收起采集链路核对信息' : '展开采集链路核对信息'}
                      </button>

                      {showChainDetails && (
                        <div className="mt-3 space-y-3 rounded-lg bg-gray-50 p-4 text-sm text-gray-700">
                          <div className="grid gap-1">
                            <span>数据源目录：{datasetUrl}/index.json</span>
                            <span>区域记录：{datasetUrl}/regions/&lt;regionId&gt;.json</span>
                            <span>
                              目录字段：sourceId、sourceName、updatedAt、regions（id、name）
                            </span>
                            <span>
                              区域字段：regionId、regionName、map{'（lat、lng、zoom、address）'}、
                              totalCustomers、activeCustomers、growthRate、topCountries、collectedAt
                            </span>
                            <span>
                              可选字段：simulateCollectionFailure（演示上游采集失败）
                            </span>
                          </div>
                          <div className="grid gap-1 border-t border-gray-200 pt-2">
                            <span>已发起的采集请求数：{audit.requestCount}</span>
                            <span>缓存命中次数：{audit.cacheHits}</span>
                            <span>合并到进行中请求的次数：{audit.coalescedSelections}</span>
                            <span>快速切换丢弃的过期结果：{audit.staleResultsIgnored}</span>
                            <span>最近一次选择：{audit.lastSelectionLabel}</span>
                          </div>
                          <p className="text-xs text-gray-500">
                            地图中心、统计卡与国家标签均取自同一次采集结果；数字缺失或非法时整块区域标记为不可用。
                          </p>
                        </div>
                      )}

                      <div className="mt-2">
                        <DatasetFootnote
                          sourceLabel={
                            view.kind === 'available' || view.kind === 'unavailable'
                              ? view.sourceLabel
                              : view.kind === 'failure'
                                ? view.sourceLabel ?? datasetUrl
                                : datasetUrl
                          }
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="heatmap" className="space-y-6">
                <Card className="border-2">
                  <CardHeader>
                    <CardTitle className="flex items-center">
                      <TrendingUp className="h-6 w-6 mr-3 text-indigo-600" />
                      客户密度热力图
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div className="rounded-xl overflow-hidden border-2 border-gray-200">
                      <Map
                        ak="OeTpXHgdUrRT2pPyAPRL7pog6GlMlQzl"
                        option={{
                          lat: 39.915,
                          lng: 116.404,
                          zoom: 5,
                          address: '中国市场客户密度分布'
                        }}
                        className="w-full h-[500px]"
                      />
                    </div>

                    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 p-6 rounded-xl">
                      <h3 className="font-bold text-gray-900 mb-4">热力图说明</h3>
                      <div className="space-y-2 text-gray-700">
                        <p>🔴 红色区域：客户密度极高，重点市场区域</p>
                        <p>🟠 橙色区域：客户密度较高，潜力市场区域</p>
                        <p>🟡 黄色区域：客户密度中等，待开发市场</p>
                        <p>🟢 绿色区域：客户密度较低，新兴市场机会</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="analytics" className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <Card className="border-2">
                    <CardHeader>
                      <CardTitle>客户行业分布</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {[
                          { industry: '机械制造', percentage: 28, color: 'bg-blue-600' },
                          { industry: '电子科技', percentage: 22, color: 'bg-indigo-600' },
                          { industry: '纺织服装', percentage: 18, color: 'bg-purple-600' },
                          { industry: '化工产品', percentage: 15, color: 'bg-green-600' },
                          { industry: '其他行业', percentage: 17, color: 'bg-gray-600' }
                        ].map((item) => (
                          <div key={item.industry}>
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-sm font-medium text-gray-700">
                                {item.industry}
                              </span>
                              <span className="text-sm font-bold text-gray-900">
                                {item.percentage}%
                              </span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-2">
                              <div
                                className={`${item.color} h-2 rounded-full transition-all duration-500`}
                                style={{ width: `${item.percentage}%` }}
                              ></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-2">
                    <CardHeader>
                      <CardTitle>客户规模分布</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {[
                          { size: '大型企业', percentage: 35, color: 'bg-blue-600' },
                          { size: '中型企业', percentage: 42, color: 'bg-indigo-600' },
                          { size: '小型企业', percentage: 23, color: 'bg-purple-600' }
                        ].map((item) => (
                          <div key={item.size}>
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-sm font-medium text-gray-700">
                                {item.size}
                              </span>
                              <span className="text-sm font-bold text-gray-900">
                                {item.percentage}%
                              </span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-2">
                              <div
                                className={`${item.color} h-2 rounded-full transition-all duration-500`}
                                style={{ width: `${item.percentage}%` }}
                              ></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-2">
                    <CardHeader>
                      <CardTitle>月度获客趋势</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-3">
                        {[
                          { month: '1月', count: 1200 },
                          { month: '2月', count: 1450 },
                          { month: '3月', count: 1680 },
                          { month: '4月', count: 1920 },
                          { month: '5月', count: 2150 },
                          { month: '6月', count: 2400 }
                        ].map((item) => (
                          <div key={item.month} className="flex items-center space-x-3">
                            <span className="text-sm font-medium text-gray-700 w-12">
                              {item.month}
                            </span>
                            <div className="flex-1 bg-gray-200 rounded-full h-8 relative">
                              <div
                                className="bg-gradient-to-r from-blue-600 to-indigo-600 h-8 rounded-full flex items-center justify-end pr-3 transition-all duration-500"
                                style={{ width: `${(item.count / 2400) * 100}%` }}
                              >
                                <span className="text-xs font-bold text-white">
                                  {item.count}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-2">
                    <CardHeader>
                      <CardTitle>转化率分析</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-4 rounded-xl">
                          <div className="text-sm text-gray-600 mb-1">线索转化率</div>
                          <div className="text-3xl font-bold text-blue-600">45%</div>
                        </div>
                        <div className="bg-gradient-to-br from-green-50 to-emerald-50 p-4 rounded-xl">
                          <div className="text-sm text-gray-600 mb-1">客户成交率</div>
                          <div className="text-3xl font-bold text-green-600">32%</div>
                        </div>
                        <div className="bg-gradient-to-br from-purple-50 to-pink-50 p-4 rounded-xl">
                          <div className="text-sm text-gray-600 mb-1">客户复购率</div>
                          <div className="text-3xl font-bold text-purple-600">68%</div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </section>
    </div>
  );
}
