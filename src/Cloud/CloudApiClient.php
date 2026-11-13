<?php

declare(strict_types=1);

namespace App\Cloud;

use App\Topology\TopologyConfig;
use Psr\Log\LoggerInterface;
use Psr\Log\NullLogger;
use Symfony\Contracts\Cache\CacheInterface;
use Symfony\Contracts\Cache\ItemInterface;
use Symfony\Contracts\HttpClient\HttpClientInterface;
use Symfony\Contracts\HttpClient\Exception\TransportExceptionInterface;

/**
 * ClickHouse Cloud control-plane REST client.
 *
 *   Auth: HTTP Basic (key ID + key secret from CLICKHOUSE_CLOUD_KEY_ID / _SECRET).
 *   Base: https://api.clickhouse.cloud/v1
 *   Response envelope: every endpoint returns { status, requestId, result | error }.
 *
 * Important: calls to `api.clickhouse.cloud` are control-plane — they do NOT wake idle services.
 * Only data-plane HTTPS/native hits the service and wakes it. We strictly avoid the data-plane
 * for state queries.
 */
final class CloudApiClient
{
    private const BASE_URI = 'https://api.clickhouse.cloud/v1/';
    private const CACHE_TTL_SERVICES = 30;       // seconds — service list + states
    private const CACHE_TTL_ORGANIZATIONS = 300; // seconds — orgs almost never change
    private const CACHE_TTL_PRIVATE_DNS = 300;   // seconds — private endpoint config is effectively static
    private const CACHE_TTL_PRIVATE_DNS_MISS = 30; // seconds — re-probe soon after a transient failure

    /**
     * Page size requested from GET .../services. The control plane may cap it server-side;
     * pagination metadata in the response is authoritative, not this number.
     */
    private const SERVICES_PAGE_SIZE = 100;

    /**
     * Hard ceiling on page requests per collection run. Guards against a control plane that keeps
     * advertising "next page" forever (e.g. a buggy or absent cursor). 100 pages × 100 rows is far
     * beyond any real organization; when hit, collection stops and the report records
     * {@see ServicesCollectionReport::STOP_MAX_PAGES}.
     */
    private const MAX_SERVICE_PAGES = 100;

    /**
     * Per-instance memo of collection results keyed by org id, valid for
     * {@see self::CACHE_TTL_SERVICES} seconds. Prevents a second HTTP sweep when the caller asks
     * for both the list and the report in one request (the topology endpoint does), while still
     * honouring the same TTL as the shared cache in long-running workers.
     *
     * @var array<string, array{expiresAt: float, value: array{services: list<CloudService>, report: ServicesCollectionReport}}>
     */
    private array $collectedServices = [];

    public function __construct(
        private readonly HttpClientInterface $httpClient,
        private readonly TopologyConfig $config,
        private readonly ?CacheInterface $cache = null,
        private readonly LoggerInterface $logger = new NullLogger(),
    ) {}

    /**
     * Invalidates cached services list — call after a wake action so the next topology
     * fetch picks up the new state immediately instead of after TTL expiry.
     */
    public function invalidateServicesCache(?string $orgId = null): void
    {
        $orgId = $orgId ?? $this->config->cloudOrgId;
        if ($orgId === '') {
            return;
        }
        // Drop the in-request memo first — it is populated even when no shared cache is wired in.
        unset($this->collectedServices[$orgId]);

        if ($this->cache === null) {
            return;
        }
        $this->cache->delete($this->servicesCacheKey($orgId));
    }

    /**
     * @return list<array{id: string, name: string}>
     */
    public function listOrganizations(): array
    {
        $compute = function (): array {
            $payload = $this->request('GET', 'organizations');
            $out = [];
            foreach ((array) $payload as $org) {
                if (is_array($org) && isset($org['id'], $org['name'])) {
                    $out[] = ['id' => (string) $org['id'], 'name' => (string) $org['name']];
                }
            }
            return $out;
        };

        if ($this->cache === null) {
            return $compute();
        }
        return $this->cache->get('chadmin.cloud.organizations', function (ItemInterface $item) use ($compute) {
            $item->expiresAfter(self::CACHE_TTL_ORGANIZATIONS);
            return $compute();
        });
    }

    /**
     * Resolves the org id to use: CLICKHOUSE_CLOUD_ORG_ID if set, otherwise auto-derived
     * when the key has access to exactly one org. Throws if ambiguous.
     */
    public function resolveOrganizationId(): string
    {
        if ($this->config->cloudOrgId !== '') {
            return $this->config->cloudOrgId;
        }

        $orgs = $this->listOrganizations();
        if (count($orgs) === 1) {
            return $orgs[0]['id'];
        }
        if ($orgs === []) {
            throw new CloudApiException('Cloud API key has access to no organizations.');
        }
        throw new CloudApiException(sprintf(
            'Cloud API key has access to %d organizations; set CLICKHOUSE_CLOUD_ORG_ID to select one.',
            count($orgs),
        ));
    }

    /**
     * Lists all services in the resolved organization, walking every page.
     *
     * Pages are requested sequentially until the response reports no next page. A failed page
     * stops paging but keeps the services already collected — the method never discards a partial
     * result. Repeated cursors/pages and {@see self::MAX_SERVICE_PAGES} also stop the walk.
     * The list (and the per-page {@see ServicesCollectionReport}) is cached as a single entry per
     * organization for {@see self::CACHE_TTL_SERVICES}s; call {@see invalidateServicesCache()}
     * after a wake action to pick up the new state immediately.
     *
     * @return list<CloudService>
     */
    public function listServices(?string $orgId = null): array
    {
        $orgId = $orgId ?? $this->resolveOrganizationId();

        return $this->collectServices($orgId)['services'];
    }

    /**
     * Per-page outcome of the most recent services collection for the organization. Reads the
     * same cache entry as {@see listServices()}, so calling both in one request only performs a
     * single HTTP sweep.
     */
    public function servicesCollectionReport(?string $orgId = null): ServicesCollectionReport
    {
        $orgId = $orgId ?? $this->resolveOrganizationId();

        return $this->collectServices($orgId)['report'];
    }

    /**
     * @return array{services: list<CloudService>, report: ServicesCollectionReport}
     */
    private function collectServices(string $orgId): array
    {
        $now = microtime(true);
        if (isset($this->collectedServices[$orgId]) && $this->collectedServices[$orgId]['expiresAt'] > $now) {
            return $this->collectedServices[$orgId]['value'];
        }
        unset($this->collectedServices[$orgId]);

        $compute = fn (): array => $this->fetchAllServicePages($orgId);

        if ($this->cache === null) {
            return $this->remember($orgId, $compute());
        }

        $cached = $this->cache->get($this->servicesCacheKey($orgId), function (ItemInterface $item) use ($compute) {
            $item->expiresAfter(self::CACHE_TTL_SERVICES);
            return $compute();
        });

        // Cache entries written before pagination support are a bare list<CloudService>.
        // Normalize them so a deploy doesn't break the first request after the upgrade.
        if (!isset($cached['services']) || !isset($cached['report'])) {
            $legacyServices = is_array($cached) ? array_values(array_filter($cached, static fn (mixed $s) => $s instanceof CloudService)) : [];
            $cached = [
                'services' => $legacyServices,
                'report' => new ServicesCollectionReport(
                    organizationId: $orgId,
                    pages: [],
                    totalServices: count($legacyServices),
                    complete: true,
                    stoppedReason: null,
                    collectedAt: new \DateTimeImmutable(),
                ),
            ];
        }

        return $this->remember($orgId, $cached);
    }

    /**
     * @param array{services: list<CloudService>, report: ServicesCollectionReport} $value
     * @return array{services: list<CloudService>, report: ServicesCollectionReport}
     */
    private function remember(string $orgId, array $value): array
    {
        $this->collectedServices[$orgId] = [
            'expiresAt' => microtime(true) + self::CACHE_TTL_SERVICES,
            'value' => $value,
        ];

        return $value;
    }

    /**
     * Requests pages of GET /v1/organizations/{orgId}/services until the API reports no next page.
     *
     * Pagination protocol used for the request side (the response side is parsed by
     * {@see PaginationMeta}): the first call sends `pageSize`; if the response metadata yields a
     * cursor the next call sends `pageSize` + `pageToken=<cursor>`; if it only yields a page
     * number the next call sends `pageSize` + `page=<n>`. Endpoints that ignore these parameters
     * simply return the whole list and no pagination metadata, which is treated as one final page.
     *
     * @return array{services: list<CloudService>, report: ServicesCollectionReport}
     */
    private function fetchAllServicePages(string $orgId): array
    {
        $services = [];
        $seenServiceIds = [];
        $pages = [];
        $seenCursors = [];
        $seenPages = [];
        $cursor = null;
        $pageNumber = null;
        $stoppedReason = null;
        $complete = false;

        for ($attempt = 1; $attempt <= self::MAX_SERVICE_PAGES; $attempt++) {
            $query = ['pageSize' => self::SERVICES_PAGE_SIZE];
            if ($cursor !== null) {
                $query['pageToken'] = $cursor;
            } elseif ($pageNumber !== null) {
                $query['page'] = $pageNumber;
            }

            $path = sprintf('organizations/%s/services', urlencode($orgId))
                . '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986);

            $unpagedFallback = false;
            try {
                $response = $this->requestWithMetadata('GET', $path, null, self::SERVICES_PAGE_SIZE);
            } catch (CloudApiException $e) {
                // Compatibility fallback: a gateway that rejects the pagination query parameters
                // outright (400/422 on the *first* request) gets one plain, parameter-free call so
                // deployments whose control plane does not know `pageSize` keep working. Auth and
                // throttling failures (401/403/429) are not parameter problems — don't retry them.
                if ($attempt === 1 && in_array($e->statusCode, [400, 422], true)) {
                    $plainPath = sprintf('organizations/%s/services', urlencode($orgId));
                    try {
                        $response = $this->requestWithMetadata('GET', $plainPath);
                        $unpagedFallback = true;
                        $this->logger->notice('Cloud services endpoint rejected pagination parameters; falling back to a single unpaged request.', [
                            'org' => $orgId,
                            'status' => $e->statusCode,
                        ]);
                    } catch (CloudApiException $fallbackError) {
                        $e = $fallbackError;
                        $response = null;
                    }
                } else {
                    $response = null;
                }

                if ($response === null) {
                    // A failed page must not poison the pages that already succeeded: stop here and
                    // return the partial list, but leave a full record of the failure.
                    $pages[] = new ServicesPageAttempt(
                        pageNumber: $attempt,
                        cursor: $cursor,
                        success: false,
                        serviceCount: 0,
                        error: $e->getMessage(),
                        statusCode: $e->statusCode,
                        requestId: $e->requestId,
                    );
                    $this->logger->warning('Cloud services page failed; returning services collected so far.', [
                        'org' => $orgId,
                        'page' => $attempt,
                        'cursor' => $cursor,
                        'status' => $e->statusCode,
                        'error' => $e->getMessage(),
                    ]);
                    $stoppedReason = ServicesCollectionReport::STOP_PAGE_FAILED;
                    break;
                }
            }

            $rows = self::extractServiceRows($response->result);
            $pageServices = 0;
            foreach ($rows as $row) {
                $service = CloudService::fromArray($row);
                $pageServices++;
                if ($service->id !== '' && isset($seenServiceIds[$service->id])) {
                    continue;
                }
                if ($service->id !== '') {
                    $seenServiceIds[$service->id] = true;
                }
                $services[] = $service;
            }

            $meta = $response->pagination;
            $hasNext = $meta?->hasNext ?? false;
            $nextCursor = $meta?->nextCursor;
            $nextPage = $meta?->nextPage;

            // The unpaged fallback exists because this control plane rejected pagination
            // parameters — requesting another page would be rejected the same way. Treat the
            // fallback response as the only (and therefore final) page.
            if ($unpagedFallback) {
                $hasNext = false;
                $nextCursor = null;
                $nextPage = null;
            }

            $pages[] = new ServicesPageAttempt(
                pageNumber: $attempt,
                cursor: $cursor,
                success: true,
                serviceCount: $pageServices,
                requestId: $response->requestId,
                statusCode: $response->statusCode,
                hasNextPage: $hasNext,
                nextCursor: $nextCursor,
                nextPage: $nextPage,
            );

            if (!$hasNext) {
                $complete = true;
                break;
            }

            if ($nextCursor !== null) {
                if (isset($seenCursors[$nextCursor])) {
                    $this->logger->warning('Cloud services pagination repeated a cursor; stopping to avoid a loop.', [
                        'org' => $orgId,
                        'cursor' => $nextCursor,
                        'page' => $attempt,
                    ]);
                    $stoppedReason = ServicesCollectionReport::STOP_REPEATED_CURSOR;
                    break;
                }
                $seenCursors[$nextCursor] = true;
                $cursor = $nextCursor;
                $pageNumber = null;
                continue;
            }

            if ($nextPage !== null) {
                if (isset($seenPages[$nextPage])) {
                    $this->logger->warning('Cloud services pagination repeated a page number; stopping to avoid a loop.', [
                        'org' => $orgId,
                        'next_page' => $nextPage,
                        'page' => $attempt,
                    ]);
                    $stoppedReason = ServicesCollectionReport::STOP_REPEATED_PAGE;
                    break;
                }
                $seenPages[$nextPage] = true;
                $pageNumber = $nextPage;
                $cursor = null;
                continue;
            }

            // hasNext was advertised without a usable cursor or page number — cannot continue.
            $this->logger->warning('Cloud services pagination advertised another page without a cursor or page number.', [
                'org' => $orgId,
                'page' => $attempt,
            ]);
            $stoppedReason = ServicesCollectionReport::STOP_NO_PAGE_HINT;
            break;
        }

        if (!$complete && $stoppedReason === null) {
            $stoppedReason = ServicesCollectionReport::STOP_MAX_PAGES;
        }

        return [
            'services' => $services,
            'report' => new ServicesCollectionReport(
                organizationId: $orgId,
                pages: $pages,
                totalServices: count($services),
                complete: $complete,
                stoppedReason: $stoppedReason,
                collectedAt: new \DateTimeImmutable(),
            ),
        ];
    }

    /**
     * @return list<array<string, mixed>>
     */
    private static function extractServiceRows(mixed $result): array
    {
        if (!is_array($result)) {
            return [];
        }

        // Some gateways wrap the list: {"services": [...]}. Prefer that when present.
        if (!array_is_list($result) && isset($result['services']) && is_array($result['services'])) {
            $result = $result['services'];
        }

        $rows = [];
        foreach ($result as $row) {
            if (is_array($row)) {
                $rows[] = $row;
            }
        }

        return $rows;
    }

    private function servicesCacheKey(string $orgId): string
    {
        return 'chadmin.cloud.services.' . $orgId;
    }

    /**
     * Resolves a service's private endpoint DNS hostname from
     * GET /v1/organizations/{orgId}/services/{serviceId}/privateEndpointConfig.
     *
     * Control-plane only — does NOT wake the service. Used when CLICKHOUSE_CLOUD_USE_PRIVATE_DNS
     * is on so the data-plane SQL connection (and the idle-wake /ping) goes through the private
     * endpoint instead of the public one. Returns null when no private endpoint is configured or
     * the lookup fails, so the caller can fall back to the public endpoint.
     */
    public function privateDnsHostname(string $serviceId, ?string $orgId = null): ?string
    {
        $orgId = $orgId ?? $this->resolveOrganizationId();

        $compute = function () use ($orgId, $serviceId): ?string {
            try {
                $payload = $this->request('GET', sprintf(
                    'organizations/%s/services/%s/privateEndpointConfig',
                    urlencode($orgId),
                    urlencode($serviceId),
                ));
            } catch (CloudApiException $e) {
                $this->logger->warning('Failed to resolve private endpoint config; falling back to public endpoint.', [
                    'service' => $serviceId,
                    'error' => $e->getMessage(),
                ]);
                return null;
            }

            $host = is_array($payload) ? trim((string) ($payload['privateDnsHostname'] ?? '')) : '';
            if ($host === '') {
                $this->logger->warning('No private DNS hostname configured for service; falling back to public endpoint.', [
                    'service' => $serviceId,
                ]);
                return null;
            }
            return $host;
        };

        if ($this->cache === null) {
            return $compute();
        }
        return $this->cache->get($this->privateDnsCacheKey($orgId, $serviceId), function (ItemInterface $item) use ($compute) {
            $host = $compute();
            // Positive config is static → long TTL; a miss is likely transient → re-probe soon.
            $item->expiresAfter($host !== null ? self::CACHE_TTL_PRIVATE_DNS : self::CACHE_TTL_PRIVATE_DNS_MISS);
            return $host;
        });
    }

    private function privateDnsCacheKey(string $orgId, string $serviceId): string
    {
        return 'chadmin.cloud.private_dns.' . $orgId . '.' . $serviceId;
    }

    /**
     * Explicit wake — used only on user-initiated action (click "Wake" button).
     *
     *  - `stopped` → PATCH /state with {"command": "start"}.
     *  - `idle` → per Cloud docs, `start` does NOT resume an idle service; only a data-plane
     *    request (e.g. HTTPS /ping) resumes. We call /ping on the HTTPS endpoint.
     */
    public function wakeService(string $serviceId, string $currentState, ?string $httpsHost = null, int $httpsPort = 8443, ?string $orgId = null): void
    {
        $orgId = $orgId ?? $this->resolveOrganizationId();

        $normalized = strtolower($currentState);
        if ($normalized === 'stopped') {
            $this->request(
                'PATCH',
                sprintf('organizations/%s/services/%s/state', urlencode($orgId), urlencode($serviceId)),
                ['command' => 'start'],
            );
            return;
        }

        if ($normalized === 'idle' && $httpsHost !== null && $httpsHost !== '') {
            try {
                $this->httpClient->request('GET', sprintf('https://%s:%d/ping', $httpsHost, $httpsPort), [
                    'timeout' => 3,
                    'max_redirects' => 0,
                ])->getStatusCode();
            } catch (TransportExceptionInterface $e) {
                // Read timeout is EXPECTED for an idle service — the TCP/TLS handshake already
                // delivered the wake signal, but the service can take minutes to answer HTTP.
                // Only genuine connect-level failures (DNS, connection refused, TLS) bubble up.
                if (stripos($e->getMessage(), 'timeout') === false) {
                    throw new CloudApiException('Failed to ping Cloud service to wake it: ' . $e->getMessage(), previous: $e);
                }
                $this->logger->info('Idle wake /ping timed out (expected) — wake signal delivered', [
                    'service' => $serviceId,
                ]);
            }
            return;
        }

        throw new CloudApiException(sprintf(
            'Cannot wake service "%s" from state "%s" — only idle/stopped are resumable.',
            $serviceId,
            $currentState,
        ));
    }

    /**
     * Best-effort extraction of requestId/error from a non-2xx body. Returns
     * ['requestId' => ?string, 'error' => ?string], with nulls when the body isn't JSON.
     *
     * @return array{requestId: ?string, error: ?string}
     */
    private function describeErrorBody(string $content, int $status): array
    {
        $decoded = json_decode($content, true);
        if (!is_array($decoded)) {
            return ['requestId' => null, 'error' => sprintf('HTTP %d', $status)];
        }
        $error = $decoded['error'] ?? null;
        if (is_array($error)) {
            $error = $error['message'] ?? json_encode($error);
        }

        return [
            'requestId' => isset($decoded['requestId']) ? (string) $decoded['requestId'] : null,
            'error' => $error !== null ? (string) $error : sprintf('HTTP %d', $status),
        ];
    }

    /**
     * Runs one HTTP request against api.clickhouse.cloud. Retries once on 429/5xx with backoff.
     * Unwraps the common {status, requestId, result|error} envelope and returns `result`.
     *
     * @return mixed  The `result` field from the envelope (usually array).
     */
    private function request(string $method, string $path, ?array $body = null): mixed
    {
        return $this->requestWithMetadata($method, $path, $body)->result;
    }

    /**
     * Same as {@see request()}, but returns the whole envelope instead of only `result`, so the
     * caller can also read pagination metadata and the request id. Use this for any endpoint that
     * may be paged.
     *
     * Pagination field names parsed out of the envelope (see {@see PaginationMeta} for the full
     * list of accepted spellings): a `pagination` / `paging` / `pageInfo` / `page_info` / `meta`
     * block at the envelope root (or inside an assoc `result`) carrying a next cursor
     * (`nextCursor`, `next_page_token`, …), a next page number (`nextPage`, `next_page`, …),
     * `hasNext` / `has_more`, and optionally `page`, `pageSize`, `totalPages`, `total`.
     * A response with no such block yields `pagination: null`, meaning "single / final page".
     */
    public function requestWithMetadata(string $method, string $path, ?array $body = null, ?int $pageSize = null): CloudApiResponse
    {
        $url = self::BASE_URI . ltrim($path, '/');
        $options = [
            'auth_basic' => [$this->config->cloudKeyId, $this->config->cloudKeySecret],
            'timeout' => 10,
            'max_redirects' => 0,
        ];
        if ($body !== null) {
            $options['json'] = $body;
        }

        $attempts = 0;
        while (true) {
            $attempts++;
            try {
                $response = $this->httpClient->request($method, $url, $options);
                $status = $response->getStatusCode();
                $content = $response->getContent(false);
            } catch (TransportExceptionInterface $e) {
                if ($attempts >= 3) {
                    throw new CloudApiException('Cloud API transport error: ' . $e->getMessage(), previous: $e);
                }
                usleep(200_000 * $attempts);
                continue;
            }

            if ($status === 429 || $status >= 500) {
                if ($attempts >= 3) {
                    // Keep whatever the error body told us (requestId / API error) so the
                    // per-page collection report can point at the exact failing request.
                    $failure = $this->describeErrorBody($content, $status);
                    throw new CloudApiException(
                        sprintf('Cloud API %s %s → %d after %d attempts: %s', $method, $path, $status, $attempts, $failure['error'] ?? $content),
                        statusCode: $status,
                        requestId: $failure['requestId'],
                    );
                }
                $resetHeader = $response->getHeaders(false)['x-ratelimit-reset'][0] ?? null;
                $delaySec = is_numeric($resetHeader) ? max(1, (int) $resetHeader) : $attempts;
                $this->logger->notice('Cloud API backoff', ['status' => $status, 'delay_sec' => $delaySec, 'path' => $path]);
                sleep(min(5, $delaySec));
                continue;
            }

            $decoded = json_decode($content, true);
            if (!is_array($decoded)) {
                throw new CloudApiException(sprintf('Cloud API returned non-JSON body for %s %s: %s', $method, $path, substr($content, 0, 200)), statusCode: $status);
            }

            $requestId = isset($decoded['requestId']) ? (string) $decoded['requestId'] : null;
            if ($status >= 400 || isset($decoded['error'])) {
                throw new CloudApiException(
                    sprintf('Cloud API error %s %s: %s', $method, $path, $decoded['error'] ?? "HTTP $status"),
                    statusCode: $status,
                    requestId: $requestId,
                );
            }

            return new CloudApiResponse(
                result: $decoded['result'] ?? null,
                requestId: $requestId,
                statusCode: $status,
                pagination: PaginationMeta::fromEnvelope($decoded, $pageSize),
            );
        }
    }
}
