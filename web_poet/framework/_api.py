from __future__ import annotations

from typing import Annotated, Any, TypeAlias, get_args, get_origin

import andi
from andi.typeutils import strip_annotated
from playwright.async_api import async_playwright

from web_poet import default_registry
from web_poet.annotated import annotation_encode
from web_poet.page_inputs import (
    AnyResponse,
    BrowserHtml,
    BrowserResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBody,
    HttpResponseHeaders,
)
from web_poet.page_inputs.stats import DictStatCollector, StatCollector
from web_poet.page_inputs.url import RequestUrl, ResponseUrl
from web_poet.pages import ItemPage, is_injectable
from web_poet.rules import RulesRegistry
from web_poet.utils import ensure_awaitable

from ._providers import DEFAULT_PLAYWRIGHT_ENGINE, PROVIDERS, ResponseFetcher
from ._report import FetchReport, FetchSource

ANNOTATION_PREFIX = "playwright_engine."

#: Dependencies that are always provided by a direct HTTP request.
_HTTP_DEPENDENCIES = {HttpResponse, HttpResponseBody, HttpResponseHeaders}
#: Dependencies that are always provided by a browser.
_BROWSER_DEPENDENCIES = {BrowserResponse, BrowserHtml}
#: Dependencies provided either directly or by a browser, depending on the
#: other dependencies of the page object.
_ANY_DEPENDENCIES = {AnyResponse, ResponseUrl}


def playwright_engine(name: str) -> str:
    """Helper to create a hashable metadata value for Annotated Playwright
    engine names.

    Example usage:

    .. code-block:: python

        Annotated[BrowserResponse, playwright_engine("firefox")]
    """
    return annotation_encode(f"{ANNOTATION_PREFIX}{name}")


RequestLike: TypeAlias = HttpRequest | RequestUrl | ResponseUrl | str


def _normalize_request(request: RequestLike) -> HttpRequest:
    if not isinstance(request, HttpRequest):
        request = HttpRequest(url=request)
    return request


class Framework:
    """Manager of the :ref:`built-in framework <framework>`.

    *registry* is the :class:`~web_poet.rules.RulesRegistry` from where page
    objects resolve their dependencies. If ``None``,
    :data:`~web_poet.default_registry` is used.

    *default_playwright_engine* is the Playwright browser engine to use when
    browser inputs do not specify one. Examples: ``"chromium"``, ``"firefox"``,
    ``"webkit"``.

    *stats* is a :class:`~web_poet.page_inputs.stats.StatCollector` instance to
    collect stats written by the page object through the
    :class:`~web_poet.page_inputs.stats.Stats` dependency. If not specified, a
    :class:`~web_poet.page_inputs.stats.DictStatCollector` is used. You can
    access the collector through the :attr:`stats` attribute, e.g. to read its
    data.

    After each :meth:`get_page` or :meth:`get_item` call, the
    :attr:`fetch_report` attribute holds a :class:`FetchReport` that describes
    the data sources used for that call.
    """

    def __init__(
        self,
        *,
        registry: RulesRegistry | None = None,
        default_playwright_engine: str | None = None,
        stats: StatCollector | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._default_playwright_engine = default_playwright_engine
        self.stats: StatCollector = stats or DictStatCollector()
        self.fetch_report: FetchReport = FetchReport()

    def _playwright_engine_for_dependency(self, fn_or_cls: Any, default: str) -> str:
        base = strip_annotated(fn_or_cls)
        if base not in _BROWSER_DEPENDENCIES:
            return default
        if get_origin(fn_or_cls) is Annotated:
            meta = get_args(fn_or_cls)[1:]
            if meta and isinstance(meta[0], str):
                m = meta[0]
                if m.startswith(ANNOTATION_PREFIX):
                    return m.split(".", 1)[1]
        return default

    def _fetch_source(
        self,
        fn_or_cls: Any,
        response_fetcher: ResponseFetcher,
        engine_for_unannotated: str,
    ) -> tuple[FetchSource, str | None]:
        base = strip_annotated(fn_or_cls)
        if base in _HTTP_DEPENDENCIES:
            return FetchSource.HTTP, None
        if base in _BROWSER_DEPENDENCIES:
            engine = self._playwright_engine_for_dependency(
                fn_or_cls, engine_for_unannotated
            )
            return FetchSource.BROWSER, engine
        if base in _ANY_DEPENDENCIES:
            if response_fetcher.needs_browser_response:
                return FetchSource.BROWSER, response_fetcher.default_engine_name
            return FetchSource.HTTP, None
        return FetchSource.LOCAL, None

    async def get_page(
        self,
        request: RequestLike,
        page_cls: type[ItemPage],
        *,
        page_params: dict[Any, Any] | None = None,
    ) -> ItemPage:
        """Return a page object built from *request* and *page_cls*.

        *page_params* is a dict that the page object may access through the
        :class:`~web_poet.page_inputs.PageParams` dependency.

        The :attr:`fetch_report` attribute is updated with the data sources
        used to build the page object, also when an exception is raised.
        """
        request = _normalize_request(request)
        report = FetchReport()
        self.fetch_report = report
        plan = andi.plan(
            page_cls,
            is_injectable=is_injectable,
            externally_provided=set(PROVIDERS),
        )
        instances: dict[Any, Any] = {}
        required_deps: set[type] = set()
        for fn_or_cls, _ in plan:
            base = strip_annotated(fn_or_cls)
            assert isinstance(base, type)
            required_deps.add(base)
        response_fetcher = ResponseFetcher(
            required_deps=required_deps,
            default_playwright_engine=self._default_playwright_engine,
            report=report,
        )

        # first pass: collect explicit Playwright engine names from Annotated
        # browser deps
        explicit_engines: set[str] = set()
        for fn_or_cls, _ in plan:
            base = strip_annotated(fn_or_cls)
            if (
                base in {BrowserResponse, BrowserHtml}
                and get_origin(fn_or_cls) is Annotated
            ):
                meta = get_args(fn_or_cls)[1:]
                if meta and isinstance(meta[0], str):
                    m = meta[0]
                    if m.startswith(ANNOTATION_PREFIX):
                        explicit_engines.add(m.split(".", 1)[1])

        if not explicit_engines:
            chosen_engine_for_unannotated = (
                self._default_playwright_engine or DEFAULT_PLAYWRIGHT_ENGINE
            )
        elif (
            self._default_playwright_engine
            and self._default_playwright_engine in explicit_engines
        ):
            chosen_engine_for_unannotated = self._default_playwright_engine
        else:
            chosen_engine_for_unannotated = min(explicit_engines)

        # validate requested browsers are available in playwright before doing work
        needed_browsers = set(explicit_engines)
        # include chosen browser for unannotated deps if there are any browser deps
        if required_deps & {BrowserResponse, BrowserHtml}:
            needed_browsers.add(chosen_engine_for_unannotated)
        if needed_browsers:
            async with async_playwright() as playwright:
                for b in needed_browsers:
                    if getattr(playwright, b, None) is None:
                        raise ValueError(f"Playwright does not provide engine '{b}'")

        # second pass: instantiate dependencies, forwarding browser kwarg when needed
        for fn_or_cls, kwargs_spec in plan:
            kwargs = kwargs_spec.kwargs(instances)
            base = strip_annotated(fn_or_cls)
            assert isinstance(base, type)
            playwright_engine_kw: str | None = None
            if base in _BROWSER_DEPENDENCIES:
                playwright_engine_kw = self._playwright_engine_for_dependency(
                    fn_or_cls, chosen_engine_for_unannotated
                )

            provider = PROVIDERS.get(base)
            if provider is not None:
                source, engine = self._fetch_source(
                    fn_or_cls, response_fetcher, chosen_engine_for_unannotated
                )
                if base is not page_cls:
                    report._record_dependency(fn_or_cls, source, engine)
                call_kwargs = {
                    "request": request,
                    "page_params": page_params,
                    "page_cls": page_cls,
                    "registry": self._registry,
                    "response_fetcher": response_fetcher,
                    "stats": self.stats,
                    **kwargs,
                }
                if playwright_engine_kw is not None:
                    call_kwargs["playwright_engine"] = playwright_engine_kw
                try:
                    value = await ensure_awaitable(provider(**call_kwargs))
                except Exception:
                    if base is not page_cls:
                        report._mark_dependency_failed(fn_or_cls)
                    raise
            else:
                if base is not page_cls:
                    report._record_dependency(fn_or_cls, FetchSource.LOCAL)
                try:
                    value = await ensure_awaitable(base(**kwargs))
                except Exception:
                    if base is not page_cls:
                        report._mark_dependency_failed(fn_or_cls)
                    raise

            instances[fn_or_cls] = value
        return instances[page_cls]

    async def get_item(
        self,
        request: RequestLike,
        item_or_page_cls: type,
        *,
        page_params: dict[Any, Any] | None = None,
    ) -> Any:
        """Return an item built from *request*.

        *item_or_page_cls* is either an item class or a page object class. If
        it is an item class, the page class to use is determined by the
        :class:`~web_poet.rules.RulesRegistry` passed to
        :class:`~web_poet.framework.Framework`.

        *page_params* is a dict that the page object may access through the
        :class:`~web_poet.page_inputs.PageParams` dependency.

        The :attr:`fetch_report` attribute is updated with the data sources
        used to build the page object, also when an exception is raised.
        """
        self.fetch_report = FetchReport()
        request = _normalize_request(request)
        if issubclass(item_or_page_cls, ItemPage):
            page_cls: type | None = item_or_page_cls
        else:
            page_cls = self._registry.page_cls_for_item(request.url, item_or_page_cls)
            if page_cls is None:
                raise ValueError(f"No page object class found for URL: {request.url}")
        assert page_cls is not None
        page = await self.get_page(request, page_cls, page_params=page_params)
        return await ensure_awaitable(page.to_item())
