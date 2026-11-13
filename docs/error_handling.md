# Error Handling

## Exception Hierarchy

The Olostep SDK provides a comprehensive exception hierarchy for different failure scenarios. All exceptions inherit from `Olostep_BaseError`.

There are three main error types that directly inherit from `Olostep_BaseError`:

1. **`Olostep_APIConnectionError`** - Network-level connection failures
2. **`OlostepServerError_BaseError`** - Errors raised (sort of) by the API server
3. **`OlostepClientError_BaseError`** - Errors raised by the client SDK

### Why Connection Errors Are Separate

`Olostep_APIConnectionError` is separate from server errors because it represents network-level failures that occur before the API can process the request. These are transport layer issues (DNS or HTTP failures, timeouts, connection refused, etc.) rather than API-level errors. HTTP status codes (4xx, 5xx) are considered API responses and are categorized as server errors, even though they indicate problems.

```
Olostep_BaseError
├── Olostep_APIConnectionError
├── OlostepServerError_BaseError
│   ├── OlostepServerError_TemporaryIssue
│   │   ├── OlostepServerError_NetworkBusy
│   │   └── OlostepServerError_InternalNetworkIssue
│   ├── OlostepServerError_RequestUnprocessable
│   │   ├── OlostepServerError_ParserNotFound
│   │   └── OlostepServerError_OutOfResources
│   ├── OlostepServerError_BlacklistedDomain
│   ├── OlostepServerError_FeatureApprovalRequired
│   ├── OlostepServerError_AuthFailed
│   ├── OlostepServerError_CreditsExhausted
│   ├── OlostepServerError_InvalidEndpointCalled
│   ├── OlostepServerError_ResourceNotFound
│   ├── OlostepServerError_NoResultInResponse
│   └── OlostepServerError_UnknownIssue
└── OlostepClientError_BaseError
    ├── OlostepClientError_RequestValidationFailed
    ├── OlostepClientError_ResponseValidationFailed
    ├── OlostepClientError_NoAPIKey
    ├── OlostepClientError_AsyncContext
    ├── OlostepClientError_BetaFeatureAccessRequired
    └── OlostepClientError_Timeout
```

## Recommended Error Handling

For most use cases, catch the base error and print the error name:

```python
from olostep import AsyncOlostep, Olostep_BaseError

try:
    result = await client.scrapes.create(url_to_scrape="https://example.com")
except Olostep_BaseError as e:
    print(f"Error has occurred: {type(e).__name__}")
    print(f"Error message: {e}")
```

This approach catches all SDK errors and provides clear information about what went wrong. The error name (e.g., `OlostepServerError_AuthFailed`) is descriptive enough to understand the issue.

## Granular Error Handling

If you need more specific error handling, catch the specific error types directly. **Avoid using `OlostepServerError_BaseError` or `OlostepClientError_BaseError`** - these base classes only indicate who raised the error (server vs client), not who's responsible for fixing it. This is an implementation detail that doesn't help with error handling logic.

Instead, catch specific error types that indicate the actual problem:

```python
from olostep import (
    AsyncOlostep,
    Olostep_BaseError,
    Olostep_APIConnectionError,
    OlostepServerError_AuthFailed,
    OlostepServerError_CreditsExhausted,
    OlostepClientError_NoAPIKey,
)

try:
    result = await client.scrapes.create(url_to_scrape="https://example.com")
except Olostep_APIConnectionError as e:
    print(f"Network error: {type(e).__name__}")
except OlostepServerError_AuthFailed:
    print("Invalid API key")
except OlostepServerError_CreditsExhausted:
    print("Credits exhausted")
except OlostepClientError_NoAPIKey:
    print("API key not provided")
except Olostep_BaseError as e:
    print(f"Error has occurred: {type(e).__name__}")
```

## Automatic Retries

The SDK automatically retries on transient errors:

- `OlostepServerError_TemporaryIssue` (and its subclasses)
- `OlostepServerError_NoResultInResponse`

Retry behavior is controlled by the `RetryStrategy` configuration. See [Retry Strategy](retry_strategy.md) for details.
