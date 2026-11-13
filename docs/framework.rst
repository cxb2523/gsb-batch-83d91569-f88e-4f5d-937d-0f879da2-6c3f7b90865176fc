.. _framework:

==================
Built-in framework
==================

:mod:`web_poet.framework` is a built-in :ref:`web-poet framework <frameworks>`
for simple use cases.

It is designed to be easy to use for quick proof-of-concepts, simple scripts,
and for generating test fixtures. It can also serve as a reference
implementation for framework authors.

Limitations
===========

The main limitation of the built-in framework is that it is not a complete
scraping framework like :doc:`Scrapy <scrapy:index>`, which can support
web-poet thanks to :doc:`scrapy-poet <scrapy-poet:index>`.

As a web-poet framework, the built-in framework also lacks support for
:ref:`custom input classes <custom-inputs>`, :exc:`~web_poet.exceptions.Retry`
and :exc:`~web_poet.exceptions.UseFallback`.

Also, :ref:`browser inputs <framework-browser>` only support plain GET
requests. Requests with a non-GET method, headers or a body raise
:exc:`~web_poet.exceptions.http.HttpRequestError`.

Installation
============

To use :mod:`web_poet.framework`, install the ``framework`` extra:

.. code-block:: bash

    pip install web-poet[framework]

For :ref:`browser support <framework-browser>`, you also need to `install at
least 1 browser with Playwright
<https://playwright.dev/python/docs/browsers#install-browsers>`__. For example,
to install the main browsers:

.. code-block:: bash

    playwright install

Basic use
=========

.. code-block:: python

    from dataclasses import dataclass
    from web_poet import WebPage
    from web_poet.framework import Framework
    from web_poet.utils import ensure_awaitable


    @dataclass
    class Book:
        title: str


    class BookPage(WebPage[Book]):
        @field
        def title(self) -> str:
            return self.response.css("h1::text").get()


    framework = Framework()
    item = await framework.get_item("https://books.example.com/book/1", BookPage)

    # Or, if you prefer, get a page object instance first.
    page = await framework.get_page("https://books.example.com/book/1", BookPage)
    item = await ensure_awaitable(page.to_item())

Choosing a page object class automatically
==========================================

If you decorate your page object classes with :func:`~web_poet.handle_urls` and
make sure they are imported, e.g. with :func:`~web_poet.consume_modules`, you
can pass :meth:`~web_poet.framework.Framework.get_item` an item class, and let
it determine which page object class to use:

.. code-block:: python

    from dataclasses import dataclass
    from web_poet import WebPage, handle_urls
    from web_poet.framework import Framework


    @dataclass
    class Book:
        title: str


    @handle_urls("books.example.com")
    class BookPage(WebPage[Book]):
        @field
        def title(self) -> str:
            return self.response.css("h1::text").get()


    framework = Framework()
    item = await framework.get_item("https://books.example.com/book/1", Book)

.. _framework-browser:

Browser
=======

The built-in framework can use `Playwright
<https://playwright.dev/python/docs/library>`_ to resolve browser dependencies
like :class:`~web_poet.page_inputs.browser.BrowserHtml` or
:class:`~web_poet.page_inputs.browser.BrowserResponse`.

Chromium is used by default. You can override that by passing
``default_playwright_engine`` to :class:`~web_poet.framework.Framework`. Page
objects can also annotate their Playwright engine dependencies with
:func:`~web_poet.framework.playwright_engine` to specify which engine they
require. For example:

.. code-block:: python

    from typing import Annotated

    from web_poet import WebPage, Item
    from web_poet.page_inputs.browser import BrowserResponse
    from web_poet.framework import playwright_engine


    class MyPageObject(WebPage[Item]):
        response = Annotated[BrowserResponse, playwright_engine("firefox")]

.. _framework-fetch-report:

Fetch report
============

After each :meth:`~web_poet.framework.Framework.get_page` or
:meth:`~web_poet.framework.Framework.get_item` call, the
:attr:`~web_poet.framework.Framework.fetch_report` attribute holds a
:class:`~web_poet.framework.FetchReport` object that describes where the data
of that page object came from:

.. code-block:: python

    framework = Framework()
    page = await framework.get_page("https://books.example.com/book/1", BookPage)

    report = framework.fetch_report
    assert report.http_requests == 1
    assert report.browser_launches == {}
    print(report.sources)
    # {<class 'web_poet.page_inputs.http.HttpResponse'>: <FetchSource.HTTP: 'http'>}

The report includes:

-   :attr:`~web_poet.framework.FetchReport.http_requests`, the number of
    direct HTTP requests attempted, and
    :attr:`~web_poet.framework.FetchReport.uses_http`.
-   :attr:`~web_poet.framework.FetchReport.browser_launches`, the number of
    browser launches attempted, per Playwright engine, and
    :attr:`~web_poet.framework.FetchReport.uses_browser`.
-   :attr:`~web_poet.framework.FetchReport.dependencies`, how each dependency,
    including dependencies nested inside injectable page objects, was
    obtained: :attr:`~web_poet.framework.FetchSource.HTTP`,
    :attr:`~web_poet.framework.FetchSource.BROWSER` or
    :attr:`~web_poet.framework.FetchSource.LOCAL`. For browser dependencies,
    :attr:`~web_poet.framework.DependencyFetch.playwright_engine` is the
    engine used. :attr:`~web_poet.framework.FetchReport.sources` is the same
    information, without the Playwright engine details.

Counts reflect the fetch operations that actually happen. For example, a
page object that requests both :class:`~web_poet.page_inputs.HttpResponse` and
:class:`~web_poet.page_inputs.ResponseUrl` reports a single direct HTTP
request, because both dependencies share the same cached response. Likewise,
dependencies that use the same Playwright engine report a single launch.

The report is kept when the call raises an exception, so you can inspect the
records of the fetches that were attempted, e.g. before an
:exc:`~web_poet.exceptions.HttpRequestError` was raised. Dependencies whose
fetch failed have :attr:`~web_poet.framework.DependencyFetch.failed` set to
``True``.

Stats
=====

The built-in framework supports :class:`~web_poet.page_inputs.stats.Stats`.

By default, :class:`~web_poet.framework.Framework` creates a
:class:`~web_poet.page_inputs.stats.DictStatCollector` object, exposes it to
any page object that requests :class:`~web_poet.page_inputs.stats.Stats`, and
exposes that object as the :data:`stats <web_poet.framework.Framework.stats>`
attribute of the framework:

.. code-block:: python

    from web_poet.framework import Framework

    framework = Framework()
    item1 = await framework.get_item("http://example.com/book/1", BookPage)
    item2 = await framework.get_item("http://example.com/book/2", BookPage)
    all_stats = framework.stats

:class:`~web_poet.framework.Framework` also supports passing a custom stats
collector:

.. code-block:: python

    from web_poet.page_inputs.stats import StatCollector


    class MyStatCollector(StatCollector): ...


    framework = Framework(stats=MyStatCollector())
