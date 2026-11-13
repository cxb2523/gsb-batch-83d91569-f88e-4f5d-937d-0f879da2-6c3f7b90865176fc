<?php

declare(strict_types=1);

namespace App\Cloud;

/**
 * Result of one Cloud API call: the unwrapped `result` plus the envelope's pagination metadata.
 *
 * Returned by {@see CloudApiClient::requestWithMetadata()}. Regular callers that only need the
 * payload keep using {@see CloudApiClient::request()}, which returns `$result` alone.
 */
final readonly class CloudApiResponse
{
    public function __construct(
        public mixed $result,
        public ?string $requestId,
        public int $statusCode,
        public ?PaginationMeta $pagination = null,
    ) {}
}
