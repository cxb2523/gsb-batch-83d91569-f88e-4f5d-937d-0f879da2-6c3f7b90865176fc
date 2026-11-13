<?php

declare(strict_types=1);

namespace App\Cloud;

/**
 * Troubleshooting record for one full services collection run.
 *
 * `complete` is true only when paging stopped because the API reported no next page. A partial
 * collection (or one stopped by the page/cursor guards) still returns the services collected so
 * far — the report explains where and why it stopped.
 */
final readonly class ServicesCollectionReport
{
    public const STOP_PAGE_FAILED = 'page_failed';
    public const STOP_REPEATED_CURSOR = 'repeated_cursor';
    public const STOP_REPEATED_PAGE = 'repeated_page';
    public const STOP_NO_PAGE_HINT = 'no_page_hint';
    public const STOP_MAX_PAGES = 'max_pages';

    /**
     * @param list<ServicesPageAttempt> $pages
     */
    public function __construct(
        public string $organizationId,
        public array $pages,
        public int $totalServices,
        public bool $complete,
        public ?string $stoppedReason,
        public \DateTimeImmutable $collectedAt,
    ) {}

    public function pageCount(): int
    {
        return count($this->pages);
    }

    public function hasFailures(): bool
    {
        foreach ($this->pages as $page) {
            if (!$page->success) {
                return true;
            }
        }

        return false;
    }

    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return [
            'organizationId' => $this->organizationId,
            'collectedAt' => $this->collectedAt->format(\DateTimeInterface::ATOM),
            'complete' => $this->complete,
            'stoppedReason' => $this->stoppedReason,
            'totalServices' => $this->totalServices,
            'pages' => array_map(static fn (ServicesPageAttempt $page) => $page->toArray(), $this->pages),
        ];
    }

    /** @param array<string, mixed> $raw */
    public static function fromArray(array $raw): self
    {
        $pages = [];
        foreach ((array) ($raw['pages'] ?? []) as $page) {
            if (!is_array($page)) {
                continue;
            }
            $pages[] = new ServicesPageAttempt(
                pageNumber: (int) ($page['page'] ?? 0),
                cursor: isset($page['cursor']) ? (string) $page['cursor'] : null,
                success: (bool) ($page['success'] ?? false),
                serviceCount: (int) ($page['serviceCount'] ?? 0),
                error: isset($page['error']) ? (string) $page['error'] : null,
                statusCode: isset($page['statusCode']) ? (int) $page['statusCode'] : null,
                requestId: isset($page['requestId']) ? (string) $page['requestId'] : null,
                hasNextPage: (bool) ($page['hasNextPage'] ?? false),
                nextCursor: isset($page['nextCursor']) ? (string) $page['nextCursor'] : null,
                nextPage: isset($page['nextPage']) ? (int) $page['nextPage'] : null,
            );
        }

        try {
            $collectedAt = new \DateTimeImmutable((string) ($raw['collectedAt'] ?? ''));
        } catch (\Exception) {
            $collectedAt = new \DateTimeImmutable();
        }

        return new self(
            organizationId: (string) ($raw['organizationId'] ?? ''),
            pages: $pages,
            totalServices: (int) ($raw['totalServices'] ?? 0),
            complete: (bool) ($raw['complete'] ?? false),
            stoppedReason: isset($raw['stoppedReason']) ? (string) $raw['stoppedReason'] : null,
            collectedAt: $collectedAt,
        );
    }
}
