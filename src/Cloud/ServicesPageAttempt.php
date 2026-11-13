<?php

declare(strict_types=1);

namespace App\Cloud;

/**
 * Outcome of one services page request. Exposed (via {@see ServicesCollectionReport}) in the
 * topology payload and the troubleshooting endpoint so an operator can see exactly which page
 * failed, why, and whether the response claimed another page.
 */
final readonly class ServicesPageAttempt
{
    public function __construct(
        public int $pageNumber,      // 1-based sequence number of this request within the collection run
        public ?string $cursor,      // cursor sent with the request (null in page-number mode)
        public bool $success,
        public int $serviceCount,    // service rows parsed from this page (before cross-page de-duplication)
        public ?string $error = null,
        public ?int $statusCode = null,
        public ?string $requestId = null,
        public bool $hasNextPage = false,
        public ?string $nextCursor = null,
        public ?int $nextPage = null,
    ) {}

    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return [
            'page' => $this->pageNumber,
            'cursor' => $this->cursor,
            'success' => $this->success,
            'serviceCount' => $this->serviceCount,
            'error' => $this->error,
            'statusCode' => $this->statusCode,
            'requestId' => $this->requestId,
            'hasNextPage' => $this->hasNextPage,
            'nextCursor' => $this->nextCursor,
            'nextPage' => $this->nextPage,
        ];
    }
}
