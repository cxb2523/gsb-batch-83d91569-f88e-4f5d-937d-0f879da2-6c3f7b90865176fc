"""
Synchronous facade over the async Olostep client.

This module provides a synchronous interface to the asynchronous Olostep API client.
It uses the proxy pattern to expose the same dot-notation API as the async client,
but runs all operations in an event loop behind the scenes.

The sync client supports two usage patterns:

1. **Direct Usage (Recommended for one-off calls):**
   No explicit resource management needed since each operation creates
   a new async client internally.

   ```python
   client = Olostep(api_key="your-api-key")
   result = client.scrape.url(
       url_to_scrape="https://example.com",
       formats=["html", "markdown"]
   )
   # No explicit close needed
   ```

2. **Explicit Close (For long-lived services):**
   Call close() for consistency, though currently a no-op.

   ```python
   client = Olostep(api_key="your-api-key")
   try:
       result = client.scrape.url(
           url_to_scrape="https://example.com",
           formats=["html", "markdown"]
       )
   finally:
       client.close()  # For future compatibility
   ```

For most use cases, the direct usage pattern is sufficient since each
operation is self-contained and resources are cleaned up automatically.

PROXY PATTERN EXPLANATION:
=======================

The sync client uses a sophisticated proxy pattern to provide the same API
as the async client:

1. **Olostep** - Main sync client class that creates proxy objects
2. **_SyncProxy** - Proxy class that forwards method calls to async client
3. **_SyncStateProxy** - Smart wrapper for state objects that makes async methods sync
4. **Event Loop Management** - Automatically handles async/sync conversion

Example of how it works:
- User calls: `client.scrape.url("example.com")`
- `client.scrape` returns a `_SyncProxy` instance
- `client.scrape.url` returns another `_SyncProxy` instance with method docstring
- `client.scrape.url(...)` executes the async method and wraps state objects
- State objects get `_SyncStateProxy` which makes their async methods synchronous
- User gets fully synchronous experience without knowing about async internals

STATE OBJECT SYNC WRAPPING:
===========================

State objects (Batch, ScrapeResult, etc.) returned by the sync client are automatically
wrapped in sync proxies that:
- Detect async methods using asyncio.iscoroutine()
- Execute async methods synchronously using the client's event loop management
- Wrap nested state objects recursively
- Cache wrapped objects to avoid duplicate wrapping
- Preserve all synchronous methods and attributes unchanged
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..frontend.answers_menu import AnswersMenu
from ..frontend.batch_menu import BatchMenu

# Import state objects for wrapping
from ..frontend.client_state import (
    Batch,
    BatchItemResult,
    Crawl,
    CrawlPage,
    ScrapeResult,
    Sitemap,
)
from ..frontend.crawl_menu import CrawlMenu
from ..frontend.monitor_menu import MonitorMenu
from ..frontend.retrieve_menu import RetrieveMenu
from ..frontend.scrape_menu import ScrapeMenu
from ..frontend.searches_menu import SearchesMenu
from ..frontend.sitemap_menu import SitemapMenu
from ..retry_strategy import RetryStrategy
from .async_client import AsyncOlostep


class _SyncProxy:
    """
    Proxy class that provides synchronous access to async client methods.

    This class is the core of the proxy pattern implementation. It allows users
    to call async methods using synchronous syntax by automatically handling
    the event loop execution behind the scenes.

    Key Features:
    - Docstring inheritance from async methods
    - Dynamic method resolution
    - Event loop management
    - Transparent async-to-sync conversion

    The proxy works in three phases:
    1. Attribute Access: `client.scrape` → Returns _SyncProxy for scrape endpoint
    2. Method Access: `client.scrape.url` → Returns _SyncProxy with method docstring
    3. Method Call: `client.scrape.url(...)` → Executes async method synchronously
    """

    # Class-level mapping of endpoint names to async classes for docstring inheritance
    # This eliminates code duplication and provides a single source of truth
    # for which async class corresponds to each sync endpoint
    _CLASS_MAP = {
        "scrapes": ScrapeMenu,  # Maps to ScrapeMenu async class
        "batches": BatchMenu,  # Maps to BatchMenu async class
        "crawls": CrawlMenu,  # Maps to CrawlMenu async class
        "maps": SitemapMenu,  # Maps to SitemapMenu async class
        "retrieve": RetrieveMenu,  # Maps to RetrieveMenu async class
        "answers": AnswersMenu,  # Maps to AnswersMenu async class
        "searches": SearchesMenu,  # Maps to SearchesMenu async class
        "monitors": MonitorMenu,  # Maps to MonitorMenu async class
    }

    def __init__(self, outer: "Olostep", endpoint_name: str, method_name: str | None = None) -> None:
        """
        Initialize a sync proxy for a specific endpoint.

        The proxy introspects the corresponding async class to determine which
        methods are available and copies docstrings automatically.

        Args:
            outer: Reference back to the main Olostep instance
                   Used for accessing API credentials and transport settings
            endpoint_name: Name of the endpoint this proxy represents
                          (e.g., "scrapes", "batches", "answers")
            method_name: Name of the method this proxy represents (e.g., "create", "get")
                        If None, this proxy represents the endpoint itself
        """
        self._outer = outer
        self._endpoint_name = endpoint_name
        self._method_name = method_name

        # STEP 1: Copy docstring and class identity from the async method class
        # This ensures sync methods have the same comprehensive documentation
        # and appear to be the actual async class when inspected with type() or __class__
        # For example: type(client.scrape).__name__ returns "ScrapeMenu" instead of "_SyncProxy"
        async_class = self._CLASS_MAP.get(self._endpoint_name)
        if async_class:
            # Copy docstring
            if hasattr(async_class, "__doc__") and async_class.__doc__:
                self.__doc__ = async_class.__doc__
            # Store the async class for identity purposes
            self._async_class = async_class

            # STEP 1.5: Introspect the actual async class for public methods
            # Get all public methods (not starting with _) from the async class
            # This ensures we only expose methods that actually exist on the async class
            self._public_methods = [
                name
                for name in dir(async_class)
                if not name.startswith("_")
                and callable(getattr(async_class, name, None))
            ]

    def __getattr__(self, name: str) -> "_SyncProxy":
        """
        Handle attribute access on the proxy (e.g., client.scrape.url).

        This method is called when user accesses a method on the endpoint proxy.
        It only allows access to methods that were introspected from the async class,
        preventing exposure of internal Python methods or non-existent methods.

        Args:
            name: Name of the method being accessed (e.g., "url", "create", "get")

        Returns:
            New _SyncProxy instance representing the specific method with inherited docstring

        Raises:
            AttributeError: If the method doesn't exist on the async class
        """
        # Only allow access to methods that actually exist on the async class
        if name not in self._public_methods:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        # STEP 2: Create a new proxy for the specific method
        # This maintains the same API structure as the async client
        new_proxy = _SyncProxy(self._outer, self._endpoint_name, method_name=name)

        # STEP 3: Copy method-specific docstring and maintain class identity from async implementation
        # This ensures methods like `client.scrape.url.__doc__` show the correct documentation
        # and `type(client.scrape.url).__name__` returns "ScrapeMenu" instead of "_SyncProxy"
        # All proxies for the same endpoint share the same class identity
        try:
            async_class = self._CLASS_MAP.get(self._endpoint_name)
            if async_class:
                # Store the async class for identity purposes (all proxies share same class)
                new_proxy._async_class = async_class

                # Copy the same public methods list so all proxies have consistent method access
                if hasattr(self, "_public_methods"):
                    new_proxy._public_methods = self._public_methods

                async_method = getattr(async_class, name, None)
                if (
                    async_method
                    and hasattr(async_method, "__doc__")
                    and async_method.__doc__
                ):
                    new_proxy.__doc__ = async_method.__doc__
        except Exception:
            pass  # Silently fail if we can't get the docstring or class

        return new_proxy

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Handle method invocation on the proxy (e.g., client.scrape.url(...)).

        This is where the magic happens! When the user calls a method on the proxy,
        this method intercepts the call and executes the corresponding async method
        synchronously using an event loop.

        The execution flow:
        1. Create a resolver function that gets the async method
        2. Pass it to _outer._call() which handles the async execution
        3. Return the result synchronously to the user

        Args:
            *args: Positional arguments to pass to the async method
            **kwargs: Keyword arguments to pass to the async method

        Returns:
            Result of the async method execution (synchronous)
        """

        # STEP 4: Create a resolver function dynamically based on the endpoint name
        # This function will be called with an async client instance and will
        # return the appropriate async method (e.g., c.scrapes.create, c.batches.get)
        def resolver(c):
            endpoint = getattr(c, self._endpoint_name)
            if self._method_name:
                return getattr(endpoint, self._method_name)
            return endpoint

        # STEP 5: Execute the async method synchronously
        # The _outer._call() method handles all the event loop complexity
        # and returns the result as if it were a normal synchronous call
        result = self._outer._call(lambda c: resolver(c)(*args, **kwargs))

        # STEP 6: Wrap state objects in sync proxies for seamless sync experience
        return self._outer._wrap_state_object(result)

    def __dir__(self) -> list[str]:
        """
        Control what methods are shown by IDE autocomplete and dir().

        Returns the public methods that were introspected from the async class.
        This ensures that only the valid methods for this endpoint are
        suggested by IDEs and shown in help systems. Methods are automatically
        discovered by inspecting the corresponding async class.

        Returns:
            List of available method names for this endpoint
        """
        return self._public_methods

    @property
    def __class__(self):
        """
        Override __class__ to return the async class identity.

        This makes isinstance(client.scrape, ScrapeMenu) return True,
        while maintaining all proxy functionality.

        Returns:
            The async class that this proxy represents
        """
        return self._async_class if hasattr(self, "_async_class") else _SyncProxy

    def __repr__(self) -> str:
        """
        Return a string representation that shows the actual async class name.

        This makes repr(client.scrape) show "ScrapeMenu" instead of "_SyncProxy",
        which is more intuitive for users.

        Returns:
            String representation using the async class name
        """
        if hasattr(self, "_async_class"):
            return f"{self._async_class.__name__}[SyncProxy]()"
        return "_SyncProxy()"


class _SyncStateProxy:
    """
    Smart wrapper that makes async state objects synchronous.

    This wrapper intercepts method calls on state objects and automatically:
    - Detects async methods using asyncio.iscoroutine()
    - Executes async methods synchronously using the sync client's event loop
    - Wraps nested state objects recursively
    - Converts async iterators to sync iterators for seamless for-loop usage
    - Caches wrapped objects to avoid duplicate wrapping
    - Preserves synchronous methods and attributes unchanged

    Examples:
        batch = client.batch(["url1", "url2"])  # Returns SyncBatch
        info = batch.info()  # Sync call, returns BatchInfo directly
        for item in batch.items():  # Sync iteration over async iterator
            result = item.retrieve()  # Sync call, returns ScrapeResult directly
    """

    def __init__(self, async_state_obj: Any, sync_client: "Olostep") -> None:
        """Initialize sync wrapper for async state object.

        Args:
            async_state_obj: The async state object to wrap
            sync_client: Reference to sync client for event loop management
        """
        self._async_state = async_state_obj
        self._sync_client = sync_client
        self._wrapped_cache: dict[
            int, "_SyncStateProxy"
        ] = {}  # Cache for wrapped nested objects

        # Copy all non-private, non-callable attributes from async object
        # This prevents issues with method wrapping and infinite recursion
        for attr_name in dir(async_state_obj):
            if not attr_name.startswith("_"):
                attr_value = getattr(async_state_obj, attr_name)
                # Only copy non-callable attributes directly
                if not callable(attr_value):
                    setattr(self, attr_name, attr_value)

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access to wrap methods and nested objects."""
        if name.startswith("_"):
            # Don't wrap private attributes
            return getattr(self._async_state, name)

        attr = getattr(self._async_state, name)

        # First check if it's a state object (before checking if callable)
        # This prevents treating state objects as methods
        if self._is_state_object(attr):
            return self._wrap_nested_state(attr)

        # If it's a method, wrap it to handle async execution
        if callable(attr):
            return self._wrap_method(name, attr)

        return attr

    def _is_state_object(self, obj: Any) -> bool:
        """Check if an object is a state object that needs wrapping."""
        if obj is None:
            return False

        # Check if it's one of our known state classes
        if isinstance(obj, tuple(_STATE_WRAPPERS.keys())):
            return True

        # Check module for additional safety (but don't rely on it for MagicMock)
        if hasattr(obj, "__class__") and hasattr(obj.__class__, "__module__"):
            module = obj.__class__.__module__
            # Avoid wrapping unittest.mock objects
            if module == "unittest.mock":
                return False
            return module.startswith("olostep.frontend.client_state")

        return False

    def _wrap_method(self, method_name: str, method: Any) -> Any:
        """Wrap a method to detect and handle async execution."""

        def sync_wrapper(*args, **kwargs):
            # Execute the method
            result = method(*args, **kwargs)

            # Check if result is a coroutine (async method)
            if asyncio.iscoroutine(result):
                # This is an async method - execute it with fresh transport
                # Create a fresh async client to avoid using closed transport
                async def _fresh_call():
                    async with AsyncOlostep(
                        api_key=self._sync_client._api_key,
                        _base_url=self._sync_client._base_url,
                        _transport=self._sync_client._transport,
                    ) as fresh_client:
                        # Get the fresh caller from the new client
                        fresh_caller = fresh_client._caller
                        # Replace the caller in the state object temporarily
                        original_caller = self._async_state._caller
                        self._async_state._caller = fresh_caller
                        try:
                            # Execute the coroutine with the fresh caller
                            return await result
                        finally:
                            # Restore the original caller
                            self._async_state._caller = original_caller

                # Execute with fresh transport
                result = self._sync_client._run(_fresh_call())

            # Handle async iterators (like items(), pages(), urls())
            # Check this before state objects since async iterators might also be state objects
            # But avoid wrapping MagicMock objects which have fake __aiter__ methods
            if (
                hasattr(result, "__aiter__")
                and hasattr(result, "__anext__")
                and not getattr(result.__class__, "__module__", "").startswith(
                    "unittest.mock"
                )
            ):
                return self._wrap_async_iterator(result, method_name, args, kwargs)

            # Check if result is a nested state object that needs wrapping
            if self._is_state_object(result):
                return self._wrap_nested_state(result)

            # Regular result
            return result

        # Preserve method metadata
        sync_wrapper.__name__ = method_name
        sync_wrapper.__doc__ = getattr(method, "__doc__", None)

        return sync_wrapper

    def _wrap_nested_state(self, async_obj: Any) -> "_SyncStateProxy":
        """Wrap nested state objects in sync proxies."""
        # Check cache first to avoid infinite recursion
        obj_id = id(async_obj)
        if obj_id in self._wrapped_cache:
            return self._wrapped_cache[obj_id]

        # Create new wrapper
        wrapper = _SyncStateProxy(async_obj, self._sync_client)
        self._wrapped_cache[obj_id] = wrapper
        return wrapper

    def _wrap_async_iterator(
        self, async_iter: Any, method_name: str, args: tuple, kwargs: dict
    ) -> Any:
        """Wrap async iterators to make them synchronous.

        Converts async iterators (like batch.items(), crawl.pages(), sitemap.urls())
        into synchronous iterators that can be used in regular for loops.
        """

        class SyncIterator:
            def __init__(
                self, async_iter, sync_client, state_obj, method_name, args, kwargs
            ):
                self._async_iter = async_iter
                self._sync_client = sync_client
                self._state_obj = state_obj
                self._method_name = method_name
                self._args = args
                self._kwargs = kwargs
                self._items = None  # Cache for collected items
                self._index = 0

            def __iter__(self):
                # Collect all items synchronously on first iteration
                if self._items is None:
                    # Run the async collection with fresh transport
                    async def _collect_all():
                        async with AsyncOlostep(
                            api_key=self._sync_client._api_key,
                            _base_url=self._sync_client._base_url,
                            _transport=self._sync_client._transport,
                        ) as fresh_client:
                            # Get the fresh caller from the new client
                            fresh_caller = fresh_client._caller

                            # Temporarily replace the caller in the original state object
                            original_caller = self._state_obj._caller
                            self._state_obj._caller = fresh_caller
                            try:
                                # Create a fresh async iterator by calling the method again
                                # This ensures the iterator uses the fresh caller
                                fresh_method = getattr(
                                    self._state_obj, self._method_name
                                )
                                fresh_async_iter = fresh_method(
                                    *self._args, **self._kwargs
                                )

                                items = []
                                async for item in fresh_async_iter:
                                    # Wrap state objects in sync proxies
                                    items.append(
                                        self._sync_client._wrap_state_object(item)
                                    )
                                return items
                            finally:
                                # Restore the original caller
                                self._state_obj._caller = original_caller

                    # Execute the coroutine synchronously
                    self._items = self._sync_client._run(_collect_all())
                self._index = 0
                return self

            def __next__(self):
                if self._items is None:
                    # Trigger collection
                    self.__iter__()

                if self._items is None or self._index >= len(self._items):
                    raise StopIteration

                item = self._items[self._index]
                self._index += 1
                return item

        return SyncIterator(
            async_iter, self._sync_client, self._async_state, method_name, args, kwargs
        )

    def __dir__(self) -> list[str]:
        """Return directory including methods from async state object."""
        # Get all public attributes and methods from async state object
        async_names = [
            name for name in dir(self._async_state) if not name.startswith("_")
        ]

        # Get attributes already copied to self (excluding our internal ones)
        own_attrs = [
            name
            for name in self.__dict__
            if not name.startswith("_")
            and name not in ["_async_state", "_sync_client", "_wrapped_cache"]
        ]

        # Get wrapper-specific methods
        wrapper_methods = [
            name
            for name in dir(_SyncStateProxy)
            if not name.startswith("_") and name not in ["__class__", "__dir__"]
        ]

        # Combine all names, prioritizing async state methods/attributes
        all_names = set(async_names + own_attrs + wrapper_methods)
        return sorted(all_names)

    def __repr__(self) -> str:
        """Delegate repr to async object."""
        return repr(self._async_state)

    def __str__(self) -> str:
        """Delegate str to async object."""
        return str(self._async_state)


# Specific sync wrapper classes for type hints and clarity
class SyncBatch(_SyncStateProxy):
    """Synchronous version of Batch state object."""

    pass


class SyncScrapeResult(_SyncStateProxy):
    """Synchronous version of ScrapeResult state object."""

    pass


class SyncBatchItemResult(_SyncStateProxy):
    """Synchronous version of BatchItemResult state object."""

    pass


class SyncCrawl(_SyncStateProxy):
    """Synchronous version of Crawl state object."""

    pass


class SyncSitemap(_SyncStateProxy):
    """Synchronous version of Sitemap state object."""

    pass


class SyncCrawlPage(_SyncStateProxy):
    """Synchronous version of CrawlPage state object."""

    pass


# Mapping of async state classes to their sync wrappers
_STATE_WRAPPERS = {
    Batch: SyncBatch,
    ScrapeResult: SyncScrapeResult,
    BatchItemResult: SyncBatchItemResult,
    Crawl: SyncCrawl,
    Sitemap: SyncSitemap,
    CrawlPage: SyncCrawlPage,
    # Add more as needed
}


class Olostep:
    """
    Main synchronous client class that provides the same API as the async client.

    This class creates proxy objects for each endpoint (scrape, batch, crawl, etc.)
    that forward method calls to their async counterparts. The proxies handle
    all the complexity of running async code in event loops transparently.

    Architecture:
    - Each endpoint (scrape, batch, etc.) gets a _SyncProxy instance
    - Proxies inherit docstrings from async classes automatically
    - Method calls are forwarded to async client and executed synchronously
    - Event loop management is handled automatically

    Example:
        client = Olostep(api_key="...")
        # client.scrape returns _SyncProxy with ScrapeMenu docstring
        # client.scrape.url returns _SyncProxy with ScrapeMenu.url docstring
        # client.scrape.url(...) executes async method and returns result
    """

    def __init__(
        self,
        api_key: str | None = None,
        retry_strategy: RetryStrategy | None = None,
        *,
        _base_url: str | None = None,
        _transport: Any = None,
    ) -> None:
        """Initialize the synchronous client.

        Args:
            api_key: Your Olostep API key. If not provided, reads from OLOSTEP_API_KEY env var.
            retry_strategy: Retry configuration for API calls. If not provided, uses sensible defaults.
            _base_url: Override the base API URL (for internal testing only).
            _transport: Custom transport layer (internal use only, not documented).
        """
        self._api_key = api_key
        self._base_url = _base_url
        self._transport = _transport
        self._retry_strategy = retry_strategy

        # No need for async client - we get docstrings from class definitions directly

        # STEP 6: Create proxies for each endpoint namespace
        # These proxies provide the same dot-notation API as the async client
        # but execute methods synchronously using event loops. Methods are introspected
        # from the actual async classes automatically.
        self.scrapes = _SyncProxy(self, "scrapes")
        self.batches = _SyncProxy(self, "batches")
        self.crawls = _SyncProxy(self, "crawls")
        self.maps = _SyncProxy(self, "maps")
        self.answers = _SyncProxy(self, "answers")
        self.searches = _SyncProxy(self, "searches")
        self.retrieve = _SyncProxy(self, "retrieve")
        self.monitors = _SyncProxy(self, "monitors")

    def __dir__(self) -> list[str]:
        """
        Control what attributes are shown by IDE autocomplete and dir().

        This ensures users see the same endpoint names as the async client.

        Returns:
            List of available endpoint namespaces
        """
        return ["scrapes", "batches", "crawls", "maps", "retrieve", "answers", "searches"]

    def close(self) -> None:
        """
        Close any shared resources used by the sync client.

        Currently a no-op since each operation creates a new async client,
        but provided for future compatibility if connection pooling or caching
        is implemented.

        For one-off usage, no explicit close is needed:

            client = Olostep(api_key="...")
            result = client.scrape.url("https://example.com")

        For long-lived services where you want to ensure cleanup:

            client = Olostep(api_key="...")
            try:
                result = client.scrape.url("https://example.com")
            finally:
                client.close()
        """
        pass

    def _run(self, coro: Any) -> Any:
        """
        Execute a coroutine synchronously, handling different event loop contexts.

        This method intelligently handles async execution in various scenarios:
        - If no event loop is running: Creates new loop with asyncio.run()
        - If already in an event loop: Runs in background thread to avoid blocking

        Args:
            coro: The coroutine to execute synchronously

        Returns:
            Result of the coroutine execution
        """
        try:
            # Check if we're already in an event loop
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running - safe to use asyncio.run()
            return asyncio.run(coro)
        else:
            # Already in an event loop - must use threading to avoid blocking
            import threading

            result: dict[str, Any] = {}

            def _runner() -> None:
                """Run the coroutine in a separate event loop thread."""
                result["value"] = asyncio.run(coro)

            # Create and start daemon thread for async execution
            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join()  # Wait for completion
            return result["value"]

    def _call(self, func: Callable[[AsyncOlostep], Any]) -> Any:
        """
        Execute an async client function synchronously.

        This is the main entry point for all sync client operations. It:
        1. Creates a temporary async client with the provided credentials
        2. Executes the function within an async context manager
        3. Returns the result synchronously

        Args:
            func: Function that takes an async client and returns a coroutine

        Returns:
            Result of the async function execution (synchronous)
        """

        # STEP 7: Create the async function that will be executed
        async def _inner():
            # Use async context manager to ensure proper resource cleanup
            async with AsyncOlostep(
                api_key=self._api_key,
                retry_strategy=self._retry_strategy,
                _base_url=self._base_url,
                _transport=self._transport,
            ) as c:
                return await func(c)

        # STEP 8: Execute the async function synchronously
        return self._run(_inner())

    def _wrap_state_object(self, obj: Any) -> Any:
        """Recursively wrap state objects in sync proxies.

        This method detects state objects returned by async operations and wraps
        them in sync proxies so their methods become synchronous too.

        Args:
            obj: Object to potentially wrap (could be state object, list, dict, etc.)

        Returns:
            Wrapped object with sync behavior, or original object if not a state object
        """
        # Check if it's a direct state object
        if isinstance(obj, tuple(_STATE_WRAPPERS.keys())):
            wrapper_class = _STATE_WRAPPERS[type(obj)]
            return wrapper_class(obj, self)

        # Handle collections that might contain state objects
        if isinstance(obj, (list, tuple)):
            return type(obj)(self._wrap_state_object(item) for item in obj)
        elif isinstance(obj, dict):
            return {k: self._wrap_state_object(v) for k, v in obj.items()}

        # Not a state object - return as-is
        return obj


# =============================================================================
# PROXY PATTERN SUMMARY
# =============================================================================
#
# COMPLETE EXECUTION FLOW:
# ======================
#
# 1. User creates sync client: `client = Olostep(api_key="...")`
# 2. User accesses endpoint: `client.scrape` → Returns _SyncProxy with ScrapeMenu docstring
# 3. User accesses method: `client.scrape.url` → Returns _SyncProxy with url() docstring
# 4. User calls method: `client.scrape.url("example.com")` → Executes async method
# 5. _SyncProxy.__call__() creates resolver function: `lambda c: c.scrape`
# 6. _call() creates async context: `async with AsyncOlostep(...) as c:`
# 7. _run() executes coroutine: Creates/manages event loop as needed
# 8. _wrap_state_object() detects and wraps state objects in sync proxies
# 9. Result returned synchronously: State objects have sync methods too!
#
# KEY BENEFITS:
# ============
# - **Transparent:** Users write sync code, async happens automatically
# - **Consistent:** Same API as async client with identical documentation
# - **Thread-safe:** Handles nested event loops correctly
# - **Resource-managed:** Proper cleanup via async context managers
# - **IDE-friendly:** Full autocomplete and type hints
#
# The proxy pattern successfully bridges the gap between sync and async APIs
# while maintaining the full feature set and developer experience of both!
