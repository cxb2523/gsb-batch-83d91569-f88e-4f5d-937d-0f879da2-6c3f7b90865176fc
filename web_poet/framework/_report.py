from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class FetchSource(StrEnum):
    """Source from which a page object dependency was obtained."""

    #: The dependency was obtained through a direct HTTP request.
    HTTP = "http"
    #: The dependency was obtained by rendering the page in a browser.
    BROWSER = "browser"
    #: The dependency was provided locally, without network access.
    LOCAL = "local"


@dataclass(frozen=True)
class DependencyFetch:
    """How a single dependency of a page object was obtained.

    Instances are exposed as the values of
    :attr:`FetchReport.dependencies <web_poet.framework.FetchReport.dependencies>`.
    """

    #: The dependency, as declared by the page object. It is a type, or a
    #: :class:`typing.Annotated` type for browser dependencies that specify a
    #: Playwright engine.
    dependency: object
    #: The source that provided the dependency.
    source: FetchSource
    #: The Playwright engine used, for browser dependencies only. ``None``
    #: otherwise.
    playwright_engine: str | None = None
    #: Whether obtaining the dependency raised an exception.
    failed: bool = False

    @property
    def fetched(self) -> bool:
        """Whether obtaining the dependency involved network access."""
        return self.source is not FetchSource.LOCAL


class FetchReport:
    """Report of the data sources used to build a page object.

    :attr:`Framework.fetch_report <web_poet.framework.Framework.fetch_report>`
    holds the report of the most recent
    :meth:`~web_poet.framework.Framework.get_page` or
    :meth:`~web_poet.framework.Framework.get_item` call, and keeps it also
    when that call raises an exception.

    Counts reflect the fetch operations that actually happened: dependencies
    that share a cached direct or browser response do not increment the count
    more than once, and sources that were not used are reported as unused.
    Network operations are counted as they are attempted, so the report keeps
    the records of fetches that fail.
    """

    def __init__(self) -> None:
        self._http_requests = 0
        self._browser_launches: dict[str, int] = {}
        self._dependencies: dict[object, DependencyFetch] = {}

    @property
    def http_requests(self) -> int:
        """Number of direct HTTP requests attempted, including failed ones."""
        return self._http_requests

    @property
    def uses_http(self) -> bool:
        """Whether any direct HTTP request was attempted."""
        return bool(self._http_requests)

    @property
    def browser_launches(self) -> dict[str, int]:
        """Number of browser launches attempted, per Playwright engine.

        Launches that fail, e.g. because the browser fails to start, are
        included.
        """
        return dict(self._browser_launches)

    @property
    def uses_browser(self) -> bool:
        """Whether any browser was used, or attempted to be used."""
        return bool(self._browser_launches) or any(
            info.source is FetchSource.BROWSER for info in self._dependencies.values()
        )

    @property
    def dependencies(self) -> dict[object, DependencyFetch]:
        """How each dependency was obtained.

        It includes dependencies nested inside injectable page objects, not
        only the dependencies declared directly by the page object. A nested
        injectable page object is reported as
        :attr:`FetchSource.LOCAL <web_poet.framework.FetchSource.LOCAL>`, since
        it is assembled locally out of its own dependencies, which are
        reported separately with their actual sources.
        """
        return dict(self._dependencies)

    @property
    def sources(self) -> dict[object, FetchSource]:
        """Mapping of each dependency to its source only.

        A shorter view of
        :attr:`dependencies <web_poet.framework.FetchReport.dependencies>`.
        """
        return {
            dependency: info.source for dependency, info in self._dependencies.items()
        }

    def dependency_for(self, dependency: object) -> DependencyFetch | None:
        """Return how *dependency* was obtained, or ``None`` if it was not used."""
        return self._dependencies.get(dependency)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(http_requests={self._http_requests!r}, "
            f"browser_launches={self._browser_launches!r}, "
            f"dependencies={list(self._dependencies)!r})"
        )

    def _record_http_request(self) -> None:
        self._http_requests += 1

    def _record_browser_launch(self, engine: str) -> None:
        self._browser_launches[engine] = self._browser_launches.get(engine, 0) + 1

    def _record_dependency(
        self,
        dependency: object,
        source: FetchSource,
        playwright_engine: str | None = None,
        *,
        failed: bool = False,
    ) -> None:
        self._dependencies[dependency] = DependencyFetch(
            dependency, source, playwright_engine, failed
        )

    def _mark_dependency_failed(self, dependency: object) -> None:
        info = self._dependencies.get(dependency)
        if info is not None:
            self._dependencies[dependency] = replace(info, failed=True)
