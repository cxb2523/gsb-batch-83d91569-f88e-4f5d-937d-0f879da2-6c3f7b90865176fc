<?php

declare(strict_types=1);

namespace App\Cloud;

/**
 * Pagination metadata extracted from a Cloud API response envelope.
 *
 * The envelope itself is `{status, requestId, result | error}`. The services endpoint is the only
 * one chadmin pages through, and the control plane may describe the next page in several shapes.
 * The pagination block is looked up at the envelope root under `pagination`, `paging`, `pageInfo`,
 * `page_info` or `meta`; for gateways that nest everything in the payload it is also looked up
 * under the same keys inside `result` when `result` is an associative array.
 *
 * Accepted field spellings inside that block (first match wins):
 *
 *   next cursor:  nextCursor | next_cursor | nextPageToken | next_page_token |
 *                 nextPageCursor | next_page_cursor | nextToken | next_token |
 *                 pageToken | page_token | cursor
 *   next page:    nextPage | next_page | nextPageNumber | next_page_number
 *   current page: page | pageNumber | page_number | currentPage | current_page
 *   page size:    pageSize | page_size | limit | perPage | per_page
 *   total pages:  totalPages | total_pages | pageCount | page_count | pages
 *   total rows:   total | totalCount | total_count | totalItems | total_items |
 *                 totalRows | total_rows
 *   has next:     hasNext | has_next | hasNextPage | has_next_page | hasMore | has_more
 *
 * `hasNext` is taken from the explicit boolean when present. Otherwise it is derived from a
 * non-empty next cursor, an explicit next page, a current page below the total page count, or
 * `page * pageSize < total`. The bare `cursor` / `pageToken` spellings are treated as *next*
 * cursors only when the response does not explicitly say `hasNext: false`.
 *
 * If the envelope carries no pagination block at all (today's ClickHouse Cloud behaviour — the
 * full service list is returned in one response) {@see self::fromEnvelope()} returns null and
 * callers must treat the response as the only page.
 */
final readonly class PaginationMeta
{
    private const CONTAINER_KEYS = ['pagination', 'paging', 'pageInfo', 'page_info', 'meta'];

    private const CURSOR_KEYS = [
        'nextCursor', 'next_cursor', 'nextPageToken', 'next_page_token',
        'nextPageCursor', 'next_page_cursor', 'nextToken', 'next_token',
        'pageToken', 'page_token', 'cursor',
    ];

    private const NEXT_PAGE_KEYS = ['nextPage', 'next_page', 'nextPageNumber', 'next_page_number'];

    private const PAGE_KEYS = ['page', 'pageNumber', 'page_number', 'currentPage', 'current_page'];

    private const PAGE_SIZE_KEYS = ['pageSize', 'page_size', 'limit', 'perPage', 'per_page'];

    private const TOTAL_PAGES_KEYS = ['totalPages', 'total_pages', 'pageCount', 'page_count', 'pages'];

    private const TOTAL_KEYS = [
        'total', 'totalCount', 'total_count', 'totalItems', 'total_items',
        'totalRows', 'total_rows',
    ];

    private const HAS_NEXT_KEYS = ['hasNext', 'has_next', 'hasNextPage', 'has_next_page', 'hasMore', 'has_more'];

    public function __construct(
        public bool $hasNext = false,
        public ?string $nextCursor = null,
        public ?int $nextPage = null,
        public ?int $page = null,
        public ?int $pageSize = null,
        public ?int $totalPages = null,
        public ?int $total = null,
    ) {}

    /**
     * @param array<string, mixed> $envelope Decoded `{status, requestId, result|error}` body.
     * @param int|null             $pageSize Page size sent with the request, used as a fallback
     *                                        when deriving `hasNext` from a total row count.
     */
    public static function fromEnvelope(array $envelope, ?int $pageSize = null): ?self
    {
        $raw = self::locatePaginationBlock($envelope);
        if ($raw === null) {
            return null;
        }

        $cursor = self::firstString($raw, self::CURSOR_KEYS);
        $nextPage = self::firstInt($raw, self::NEXT_PAGE_KEYS);
        $page = self::firstInt($raw, self::PAGE_KEYS);
        $pageSize = self::firstInt($raw, self::PAGE_SIZE_KEYS) ?? $pageSize;
        $totalPages = self::firstInt($raw, self::TOTAL_PAGES_KEYS);
        $total = self::firstInt($raw, self::TOTAL_KEYS);
        $explicitHasNext = self::firstBool($raw, self::HAS_NEXT_KEYS);

        if ($nextPage === null && $page !== null && $totalPages !== null && $page < $totalPages) {
            $nextPage = $page + 1;
        }
        if ($nextPage === null && $explicitHasNext === true && $page !== null) {
            // `hasNext: true` with only a current page number — infer the sequential next page.
            // Repeated / non-advancing numbers are caught by the caller's loop guard.
            $nextPage = $page + 1;
        }
        if (
            $nextPage === null
            && $page !== null
            && $total !== null
            && $pageSize !== null
            && $pageSize > 0
            && $page * $pageSize < $total
        ) {
            $nextPage = $page + 1;
        }

        if ($explicitHasNext === false) {
            // Explicitly the last page — ignore any leftover cursor/page hints.
            $cursor = null;
            $nextPage = null;
            $hasNext = false;
        } else {
            $hasNext = $explicitHasNext
                ?? (
                    $cursor !== null
                    || $nextPage !== null
                    || ($page !== null && $totalPages !== null && $page < $totalPages)
                );
        }

        return new self(
            hasNext: $hasNext,
            nextCursor: $cursor,
            nextPage: $nextPage,
            page: $page,
            pageSize: $pageSize,
            totalPages: $totalPages,
            total: $total,
        );
    }

    /**
     * @param array<string, mixed> $envelope
     * @return array<string, mixed>|null
     */
    private static function locatePaginationBlock(array $envelope): ?array
    {
        foreach (self::CONTAINER_KEYS as $key) {
            if (isset($envelope[$key]) && is_array($envelope[$key]) && self::looksLikePagination($envelope[$key])) {
                return $envelope[$key];
            }
        }

        $result = $envelope['result'] ?? null;
        if (is_array($result) && !array_is_list($result)) {
            foreach (self::CONTAINER_KEYS as $key) {
                if (isset($result[$key]) && is_array($result[$key]) && self::looksLikePagination($result[$key])) {
                    return $result[$key];
                }
            }
        }

        return null;
    }

    /** @param array<string, mixed> $candidate */
    private static function looksLikePagination(array $candidate): bool
    {
        $keys = [
            ...self::CURSOR_KEYS,
            ...self::NEXT_PAGE_KEYS,
            ...self::PAGE_KEYS,
            ...self::PAGE_SIZE_KEYS,
            ...self::TOTAL_PAGES_KEYS,
            ...self::HAS_NEXT_KEYS,
        ];
        foreach ($keys as $key) {
            if (array_key_exists($key, $candidate)) {
                return true;
            }
        }

        return false;
    }

    /**
     * @param array<string, mixed> $raw
     * @param list<string>         $keys
     */
    private static function firstString(array $raw, array $keys): ?string
    {
        foreach ($keys as $key) {
            if (!array_key_exists($key, $raw)) {
                continue;
            }
            $value = $raw[$key];
            if (is_string($value) || is_int($value)) {
                $value = trim((string) $value);
                if ($value !== '') {
                    return $value;
                }
            }
        }

        return null;
    }

    /**
     * @param array<string, mixed> $raw
     * @param list<string>         $keys
     */
    private static function firstInt(array $raw, array $keys): ?int
    {
        foreach ($keys as $key) {
            if (!array_key_exists($key, $raw)) {
                continue;
            }
            $value = $raw[$key];
            if (is_int($value)) {
                return $value;
            }
            if (is_numeric($value)) {
                return (int) $value;
            }
        }

        return null;
    }

    /**
     * @param array<string, mixed> $raw
     * @param list<string>         $keys
     */
    private static function firstBool(array $raw, array $keys): ?bool
    {
        foreach ($keys as $key) {
            if (!array_key_exists($key, $raw)) {
                continue;
            }
            $value = $raw[$key];
            if (is_bool($value)) {
                return $value;
            }
            if (is_int($value) || is_float($value)) {
                return $value !== 0 && $value !== 0.0;
            }
            if (is_string($value)) {
                $normalized = strtolower(trim($value));
                if (in_array($normalized, ['1', 'true', 'yes'], true)) {
                    return true;
                }
                if (in_array($normalized, ['0', 'false', 'no'], true)) {
                    return false;
                }
            }
        }

        return null;
    }
}
