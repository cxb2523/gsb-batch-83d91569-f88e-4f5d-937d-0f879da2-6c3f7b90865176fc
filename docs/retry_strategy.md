# Retry Strategy Configuration

## Overview

The `RetryStrategy` class controls how the Olostep SDK handles transient API errors through automatic retries with exponential backoff and jitter. This helps ensure reliable operation in production environments where temporary network issues, rate limits, and server overload can cause intermittent failures.

## Default Behavior

By default, the SDK uses the following retry configuration:

- **Max retries**: 5 attempts
- **Initial delay**: 2 seconds
- **Backoff**: Exponential (2^attempt)
- **Jitter**: 10-90% of delay (randomized)

This means:

- Attempt 1: Immediate
- Attempt 2: ~2-3.6s delay
- Attempt 3: ~4-7.2s delay
- Attempt 4: ~8-14.4s delay
- Attempt 5: ~16-28.8s delay

Maximum duration: ~57 seconds for all retries (worst case)

## Custom Configuration

```python
from olostep import AsyncOlostep, RetryStrategy

# Create custom retry strategy
retry_strategy = RetryStrategy(
    max_retries=3,
    initial_delay=1.0,
    jitter_min=0.2,  # 20% minimum jitter
    jitter_max=0.8,  # 80% maximum jitter
)

# Use with client
async with AsyncOlostep(
    api_key="your-api-key",
    retry_strategy=retry_strategy
) as client:
    result = await client.scrapes.create("https://example.com")
```

## When Retries Happen

The SDK automatically retries on:

- **Temporary server issues** (`OlostepServerError_TemporaryIssue`)
- **Timeout responses** (`OlostepServerError_NoResultInResponse`)

Other errors (authentication, validation, resource not found, etc.) fail immediately without retry.

## Transport vs Caller Retries

The SDK has two retry layers:

1. **Transport layer**: Handles network-level connection failures (DNS, timeouts, etc.)
2. **Caller layer**: Handles API-level transient errors (controlled by `RetryStrategy`)

Both layers are independent and have separate configuration. The total maximum duration is the sum of both layers.

## Calculating Max Duration

```python
retry_strategy = RetryStrategy(max_retries=5, initial_delay=2.0)
max_duration = retry_strategy.max_duration()
print(f"Max call duration: {max_duration:.2f}s")
```

## Configuration Examples

### Conservative Strategy

```python
# Fewer retries, shorter delays
retry_strategy = RetryStrategy(
    max_retries=3,
    initial_delay=1.0,
    jitter_min=0.2,
    jitter_max=0.8
)
# Max duration: ~12.6s
```

### Aggressive Strategy

```python
# More retries for critical operations
retry_strategy = RetryStrategy(
    max_retries=10,
    initial_delay=0.5
)
# Max duration: ~969.75s
```

### No Retries (Fail Fast)

```python
# Disable retries for immediate failure feedback
retry_strategy = RetryStrategy(max_retries=0)

client = AsyncOlostep(api_key="your-api-key", retry_strategy=retry_strategy)
```

### High-Throughput Strategy

```python
# Optimized for high-volume operations
retry_strategy = RetryStrategy(
    max_retries=2,
    initial_delay=0.5,
    jitter_min=0.1,
    jitter_max=0.3  # Lower jitter for more predictable timing
)
# Max duration: ~1.95s
```

## Understanding Jitter

Jitter adds randomization to prevent "thundering herd" problems when many clients retry simultaneously. The jitter is calculated as:

```python
base_delay = initial_delay * (2 ** attempt)
jitter_range = base_delay * (jitter_max - jitter_min)
jitter = random.uniform(base_delay * jitter_min, base_delay * jitter_min + jitter_range)
final_delay = base_delay + jitter
```

For example, with `initial_delay=2.0`, `jitter_min=0.1`, `jitter_max=0.9`:

- Attempt 0: base=2.0s, jitter=0.2-1.8s, final=2.2-3.8s
- Attempt 1: base=4.0s, jitter=0.4-3.6s, final=4.4-7.6s
- Attempt 2: base=8.0s, jitter=0.8-7.2s, final=8.8-15.2s

## Best Practices

### For Production Applications

```python
# Balanced approach for production
retry_strategy = RetryStrategy(
    max_retries=5,
    initial_delay=2.0,
    jitter_min=0.1,
    jitter_max=0.9
)
```

### For Development/Testing

```python
# Fast feedback for development
retry_strategy = RetryStrategy(
    max_retries=2,
    initial_delay=0.5,
    jitter_min=0.1,
    jitter_max=0.3
)
```

### For Batch Operations

```python
# Conservative for large batch jobs
retry_strategy = RetryStrategy(
    max_retries=3,
    initial_delay=1.0,
    jitter_min=0.2,
    jitter_max=0.8
)
```

## Monitoring and Debugging

The SDK logs retry information at the DEBUG level:

```
DEBUG: Temporary issue, retrying in 2.34s
DEBUG: No result in response, retrying in 4.67s
```

Enable debug logging to monitor retry behavior:

```python
import logging
logging.getLogger("olostep").setLevel(logging.DEBUG)
```

## Error Handling

When all retries are exhausted, the original error is raised:

```python
try:
    result = await client.scrapes.create("https://example.com")
except OlostepServerError_TemporaryIssue as e:
    print(f"Failed after all retries: {e}")
    # Handle the permanent failure
```

## Performance Considerations

- **Memory**: Each retry attempt uses additional memory for request/response objects
- **Time**: Total operation time can be significantly longer with retries enabled
- **API Limits**: Retries count against your API usage limits
- **Network**: More network traffic due to retry attempts

Choose your retry strategy based on your application's requirements for reliability vs. performance.
