"""Search endpoints: videos, users, the mixed "Top" tab, live streams and
keyword suggestions.

Search is the one surface that needs a booted session (cookies from one
page load) and it is split by exit region (probed 2026-10-05):
  * /api/search/item/full     videos, 20 a page — answers on US exits, is
                              silently empty on EU ones -> the caller's
                              country first, then US
  * /api/search/user/full     accounts, 10 a page — the reverse: EU only
  * /api/search/general/full  the Top tab (videos + a user card), 12 a page
  * /api/search/live/full     live rooms, 20 a page
  * /api/search/general/preview  suggestions, unsigned, no boot

Pages are addressed by offset, and every page after the first must carry
the first page's search id. Both travel in one opaque cursor:
"<offset>.<search id>".

Video filters are the site's own: sort (relevance | likes) and published
(day | week | month | 3months | 6months).

Paging is done SERVER-SIDE inside one request: the first page starts at the
caller's cursor (absent = page 1) and up to `max_pages` pages (default 3,
max 10) are fetched back to back, reusing the first page's search id. The
answer carries, besides the merged results:

  pages  one record per successfully fetched page:
         {page, count, country, next_cursor} — `country` is the exit that
         actually answered that page (the first country in the order is only
         an attempt: an empty answer falls through to the next one), and
         `next_cursor` is null on the last page
  stop   why paging ended: {reason, message, last_page} (last_page is the
         page number paging stopped at, 0 when no page was fetched)
         done           upstream said has_more false (or max_pages was
                        reached with a valid cursor — the message says so)
         cursor_stalled has_more was true but the next cursor was empty or
                        repeated (or had no offset for) the current page's
                        cursor
         bad_cursor     the incoming cursor has no numeric offset (HTTP 400)
         upstream_error every exit/retry failed; pages fetched so far are
                        still returned (HTTP 200)

`next_cursor` / `has_more` keep their old meaning: the cursor to pass to
continue past the collected pages, and whether one exists.
"""
from scraper_errors import BadRequest, UpstreamError

from . import parsers as P
from .fetch import api, country_order, eu_country, status_of

SORTS = {"relevance": 0, "likes": 1}
PUBLISHED = {"day": 1, "week": 7, "month": 30, "3months": 90, "6months": 180}

DEFAULT_MAX_PAGES = 3
MAX_PAGES_LIMIT = 10

DONE = "done"
CURSOR_STALLED = "cursor_stalled"
UPSTREAM_ERROR = "upstream_error"
BAD_CURSOR = "bad_cursor"

_BAD_CURSOR_MESSAGE = ("the cursor has no numeric offset; pass the next_cursor "
                       "value of the previous page unchanged")


class BadCursorExhausted(ValueError):
    """The incoming cursor cannot be parsed -> HTTP 400 with a `bad_cursor`
    stop. `body` is the whole response body (routes.py serves it as-is)."""

    def __init__(self, cursor, body):
        super().__init__(_BAD_CURSOR_MESSAGE)
        self.cursor = cursor
        self.body = body


class _UnreadableCursor(ValueError):
    """Internal: the cursor has no numeric offset before its dot."""


def _split_cursor(cursor):
    """"40.20261005ABC" -> (40, "20261005ABC"); None -> (0, "")."""
    if not cursor:
        return 0, ""
    offset = _cursor_offset(cursor)
    if offset is None:
        raise _UnreadableCursor(f"cannot read an offset from cursor {cursor!r}")
    _, _, search_id = str(cursor).partition(".")
    return offset, search_id


def _cursor_offset(cursor):
    """The numeric page offset a cursor addresses, or None when it has none."""
    head = str(cursor).partition(".")[0]
    return int(head) if head.isdigit() else None


def _has_more(payload):
    """Upstream's has_more flag (0/1 ints, booleans or strings)."""
    value = payload.get("has_more")
    if value is None:
        value = payload.get("hasMore")
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no")
    return bool(value)


def _next_cursor(payload, search_id):
    if not _has_more(payload):
        return None
    offset = payload.get("cursor")
    if offset in (None, ""):
        return None
    # the id later pages must echo: log_pb.impr_id on the video / top / live
    # searches (= extra.logid), `rid` on the user search
    search_id = search_id or _search_id(payload)
    return f"{offset}.{search_id}" if search_id else str(offset)


def _search_id(payload):
    for value in ((payload.get("log_pb") or {}).get("impr_id"), (payload.get("extra") or {}).get("logid"),
                  payload.get("rid")):
        if isinstance(value, str) and value:
            return value
    return ""


def _search(path, query, offset, search_id, *, countries, offset_key="offset", extra=None):
    """One page -> (payload, the exit country that actually answered)."""
    params = {"keyword": query, offset_key: offset, "from_page": "search"}
    if search_id:
        params["search_id"] = search_id
    params.update(extra or {})
    used = {}
    payload = api(path, params, countries=countries, boot=True, used=used,
                  referer="https://www.tiktok.com/search", label=f"search for {query!r}")
    country = used.get("country")
    return payload, country.upper() if country else None


def _stop(reason, message, pages):
    last = pages[-1]["page"] if pages else 0
    return {"reason": reason, "message": message, "last_page": last}


def _collect(fetch, parse, cursor, max_pages):
    """Fetch up to `max_pages` pages, starting at `cursor`.

    fetch(offset, search_id) -> (payload, country)
    parse(payload) -> (content, count)

    Returns (pages, contents, stop). Raises ValueError for an unreadable
    incoming cursor (a subclass _UnreadableCursor) or an out-of-range
    `max_pages`; the caller turns those into a 400.
    """
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise ValueError(f"max_pages must be an integer between 1 and {MAX_PAGES_LIMIT}.")
    _split_cursor(cursor)                       # validate before any upstream call
    pages, contents, stop = [], [], None
    current = cursor
    for number in range(1, max_pages + 1):
        offset, search_id = _split_cursor(current)
        try:
            payload, country = fetch(offset, search_id)
        except (UpstreamError, BadRequest) as e:
            stop = _stop(UPSTREAM_ERROR, str(e) or type(e).__name__, pages)
            break
        content, count = parse(payload)
        more = _has_more(payload)
        next_cursor = _next_cursor(payload, search_id) if more else None
        stalled = None
        if more:
            if next_cursor is None:
                stalled = "has_more is true but the next cursor is empty"
            elif _cursor_offset(next_cursor) is None:
                stalled = f"has_more is true but the next cursor {next_cursor!r} has no numeric offset"
            elif _cursor_offset(next_cursor) == offset:
                stalled = "has_more is true but the next cursor repeats this page's cursor"
        # a stalled page is the last collected page: it has no usable next cursor
        pages.append({"page": number, "count": count, "country": country,
                      "next_cursor": None if stalled else next_cursor})
        contents.append(content)
        if not more:
            stop = _stop(DONE, "upstream reported has_more false", pages)
            break
        if stalled:
            stop = _stop(CURSOR_STALLED, stalled, pages)
            break
        if number >= max_pages:
            stop = _stop(DONE, f"collected the requested {max_pages} page(s); more results are available",
                         pages)
            break
        current = next_cursor
    return pages, contents, stop


def _bad_cursor(cursor, **empty):
    """The 400 body for an unreadable cursor (no pages were attempted)."""
    stop = _stop(BAD_CURSOR, f"{_BAD_CURSOR_MESSAGE}; got {cursor!r}", [])
    return BadCursorExhausted(cursor, {"error": f"Invalid cursor: {_BAD_CURSOR_MESSAGE}.", **empty,
                                       "pages": [], "stop": stop})


def search_videos(query, country=None, sort="relevance", published=None, cursor=None,
                  max_pages=DEFAULT_MAX_PAGES):
    """Videos matching the query, up to `max_pages` pages in one call."""
    extra = {"count": 20}
    if sort != "relevance" or published:
        extra.update({"is_filter_search": 1, "sort_type": SORTS[sort], "publish_time": PUBLISHED.get(published, 0)})
    countries = country_order(country, "us")

    def fetch(offset, search_id):
        return _search("/api/search/item/full/", query, offset, search_id, countries=countries, extra=extra)

    def parse(payload):
        videos = P.videos(payload.get("item_list"))
        return videos, len(videos)

    try:
        pages, contents, stop = _collect(fetch, parse, cursor, max_pages)
    except _UnreadableCursor:
        raise _bad_cursor(cursor, query=query, sort=sort, published=published,
                          video_count=0, videos=[], next_cursor=None, has_more=False)
    videos = [video for page in contents for video in page]
    next_cursor = pages[-1]["next_cursor"] if pages else None
    return {"query": query, "sort": sort, "published": published, "video_count": len(videos), "videos": videos,
            "next_cursor": next_cursor, "has_more": next_cursor is not None,
            "pages": pages, "stop": stop}


def search_users(query, cursor=None, max_pages=DEFAULT_MAX_PAGES):
    """Accounts matching the query, up to `max_pages` pages in one call."""
    def fetch(offset, search_id):
        return _search("/api/search/user/full/", query, offset, search_id,
                       countries=(eu_country(),), offset_key="cursor")

    def parse(payload):
        users = P.users(payload.get("user_list"), P.search_user)
        return users, len(users)

    try:
        pages, contents, stop = _collect(fetch, parse, cursor, max_pages)
    except _UnreadableCursor:
        raise _bad_cursor(cursor, query=query, user_count=0, users=[],
                          next_cursor=None, has_more=False)
    users = [user for page in contents for user in page]
    next_cursor = pages[-1]["next_cursor"] if pages else None
    return {"query": query, "user_count": len(users), "users": users,
            "next_cursor": next_cursor, "has_more": next_cursor is not None,
            "pages": pages, "stop": stop}


def search_top(query, country=None, cursor=None, max_pages=DEFAULT_MAX_PAGES):
    """The site's default "Top" results (videos plus the matching accounts
    card on the first page), up to `max_pages` pages in one call."""
    countries = country_order(country, eu_country())

    def fetch(offset, search_id):
        return _search("/api/search/general/full/", query, offset, search_id, countries=countries)

    def parse(payload):
        videos, users = P.top_results(payload.get("data"))
        return (videos, users), len(videos) + len(users)

    try:
        pages, contents, stop = _collect(fetch, parse, cursor, max_pages)
    except _UnreadableCursor:
        raise _bad_cursor(cursor, query=query, user_count=0, users=[], video_count=0,
                          videos=[], next_cursor=None, has_more=False)
    videos = [video for page_videos, _ in contents for video in page_videos]
    users = [user for _, page_users in contents for user in page_users]
    next_cursor = pages[-1]["next_cursor"] if pages else None
    return {"query": query, "user_count": len(users), "users": users, "video_count": len(videos), "videos": videos,
            "next_cursor": next_cursor, "has_more": next_cursor is not None,
            "pages": pages, "stop": stop}


def search_live(query, country=None, cursor=None, max_pages=DEFAULT_MAX_PAGES):
    """Live streams matching the query, up to `max_pages` pages in one call."""
    countries = country_order(country, eu_country())

    def fetch(offset, search_id):
        return _search("/api/search/live/full/", query, offset, search_id, countries=countries, extra={"count": 20})

    def parse(payload):
        rooms = [room for room in (P.search_live_room(row) for row in payload.get("data") or []) if room]
        return rooms, len(rooms)

    try:
        pages, contents, stop = _collect(fetch, parse, cursor, max_pages)
    except _UnreadableCursor:
        raise _bad_cursor(cursor, query=query, room_count=0, rooms=[],
                          next_cursor=None, has_more=False)
    rooms = [room for page in contents for room in page]
    next_cursor = pages[-1]["next_cursor"] if pages else None
    return {"query": query, "room_count": len(rooms), "rooms": rooms,
            "next_cursor": next_cursor, "has_more": next_cursor is not None,
            "pages": pages, "stop": stop}


def get_suggestions(query, country=None):
    """What the search box suggests while typing."""
    payload = api("/api/search/general/preview/", {"keyword": query}, country=country, signed=False)
    suggestions = P.suggestions(payload.get("sug_list")) if status_of(payload) == 0 else []
    return {"query": query, "suggestion_count": len(suggestions), "suggestions": suggestions}
