from __future__ import annotations

import json
import random
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from ehentai_crawler.crawl import (
    CrawlControl,
    StopReason,
    crawl_galleries,
    crawl_gallery,
    crawl_list,
    crawl_single,
    galleries_to_crawl,
    gallery_page_url,
    resolve_gallery_url,
    safe_file_name,
)
from ehentai_crawler.db import Database
from ehentai_crawler.errors import BannedError, SettingsError
from ehentai_crawler.fetch import Fetcher, HostRateLimiter, HttpTransport
from ehentai_crawler.parse import GalleryInfo, ListEntry
from ehentai_crawler.settings import Settings

from .fake_site import GALLERIES, image_bytes


@pytest.fixture
def db(settings):
    with Database(settings.database_path) as database:
        yield database


def listed(db, fetcher, site):
    return crawl_list(fetcher, db, site.base, update_all=False)


# --- list ---------------------------------------------------------------------------


def test_first_list_crawl_reads_every_page(db, fetcher, site):
    result = listed(db, fetcher, site)
    assert (result.pages, result.added, result.updated, result.reached_known) == (2, 5, 0, False)
    assert db.gallery_ids() == set(GALLERIES)
    assert site.paths() == ["/", "/?next=1003"]


def test_second_list_crawl_stops_at_known_galleries(db, fetcher, site):
    listed(db, fetcher, site)
    again = listed(db, fetcher, site)
    # 1005 has the newest stored time, so it is refreshed; 1004 is older, so the walk stops.
    assert (again.pages, again.added, again.updated, again.reached_known) == (1, 0, 1, True)


def test_update_crawl_reads_everything_again(db, fetcher, site):
    listed(db, fetcher, site)
    again = crawl_list(fetcher, db, site.base, update_all=True)
    assert (again.pages, again.added, again.updated) == (2, 0, 5)


def test_list_crawl_waits_out_a_ban_and_retries(db, fetcher, site):
    site.ban["/?next=1003"] = "3 seconds."
    slept = []
    result = crawl_list(fetcher, db, site.base, update_all=False, sleep=slept.append)
    assert result.added == 5
    assert slept == [1, 1, 1]
    assert site.paths() == ["/", "/?next=1003", "/?next=1003"]


def test_list_crawl_retries_a_503(db, fetcher, site):
    site.fail["/"] = 2
    assert listed(db, fetcher, site).added == 5


# --- choosing galleries ---------------------------------------------------------------


def test_removed_galleries_are_not_crawled_again(db):
    """Regression: a missing pair of brackets made the 2019 version re-crawl removed galleries."""
    with db.transaction():
        db.insert_list_entry(ListEntry(1, "aa", "Misc", "t", "2026-01-01 00:00", "u", 1), removed=1)
        db.insert_list_entry(ListEntry(2, "bb", "Misc", "t", "2026-01-01 00:00", "u", 1))
    assert galleries_to_crawl(db, tag_only=True) == [(2, "bb")]
    assert galleries_to_crawl(db, tag_only=False) == [(2, "bb")]


def test_which_galleries_are_due(db):
    info = GalleryInfo({}, 0, 0, 0.0)
    with db.transaction():
        for gid in (1, 2, 3):
            db.insert_list_entry(ListEntry(gid, "ab", "Misc", "t", "2026-01-05 00:00", "u", 1))
        db.save_page_info(1, info, "2026-01-06 00:00")  # crawled after its list time
        db.set_downloaded(1, True)
        db.save_page_info(2, info, "2026-01-06 00:00")  # crawled, images incomplete
        db.save_page_info(3, info, "2026-01-04 00:00")  # list shows a newer time

    assert sorted(galleries_to_crawl(db, tag_only=True)) == [(3, "ab")]
    assert sorted(galleries_to_crawl(db, tag_only=False)) == [(2, "ab"), (3, "ab")]


# --- one gallery -------------------------------------------------------------------------


def test_gallery_download_layout_and_metadata(fetcher, settings, site):
    result = crawl_gallery(
        fetcher,
        1005,
        site.gallery_url(1005),
        image_root=settings.image_folder_path,
        tag_only=False,
        control=CrawlControl(),
    )

    folder = settings.image_folder_path / "1005"
    assert sorted(p.name for p in folder.iterdir()) == ["page001.jpg", "page002.jpg", "page003.jpg"]
    assert (folder / "page002.jpg").read_bytes() == image_bytes(1005, 2)
    assert result.info.tags == {"sample": ["alpha", "beta two"], "other": ["gamma"]}
    assert (result.download.total, result.download.saved, result.download.complete) == (3, 3, True)
    assert site.paths("/g/") == ["/g/1005/0a1b2c3d4e/", "/g/1005/0a1b2c3d4e/?p=1"]


def test_resume_skips_saved_images_without_opening_their_pages(fetcher, settings, site):
    run = dict(image_root=settings.image_folder_path, tag_only=False, control=CrawlControl())
    crawl_gallery(fetcher, 1005, site.gallery_url(1005), **run)
    (settings.image_folder_path / "1005" / "page002.jpg").unlink()
    (settings.image_folder_path / "1005" / "page002.jpg.part").write_bytes(b"half")
    site.requests.clear()

    result = crawl_gallery(fetcher, 1005, site.gallery_url(1005), **run)

    assert (result.download.saved, result.download.skipped, result.download.complete) == (1, 2, True)
    assert site.paths("/s/") == ["/s/dd33ee44ff/1005-2"]
    assert (settings.image_folder_path / "1005" / "page002.jpg").read_bytes() == image_bytes(1005, 2)


def test_tag_only_downloads_nothing(fetcher, settings, site):
    result = crawl_gallery(
        fetcher,
        1005,
        site.gallery_url(1005),
        image_root=settings.image_folder_path,
        tag_only=True,
        control=CrawlControl(),
    )
    assert result.download is None
    assert not settings.image_folder_path.exists()
    assert site.paths() == ["/g/1005/0a1b2c3d4e/"]


def test_content_warning_is_skipped(fetcher, settings, site):
    site.content_warning.add(1004)
    result = crawl_gallery(
        fetcher,
        1004,
        site.gallery_url(1004),
        image_root=settings.image_folder_path,
        tag_only=True,
        control=CrawlControl(),
    )
    assert result.info.favorited_time == 0
    assert site.paths() == ["/g/1004/5f6a7b8c9d/", "/g/1004/5f6a7b8c9d/?nw=session"]


def test_quota_placeholder_stops_downloads(fetcher, settings, site):
    site.quota_after = 1
    control = CrawlControl()
    result = crawl_gallery(
        fetcher, 1005, site.gallery_url(1005), image_root=settings.image_folder_path, tag_only=False, control=control
    )
    assert control.quota_exceeded.is_set()
    assert (result.download.saved, result.download.complete) == (1, False)
    assert result.download.stop_reason is StopReason.QUOTA
    assert result.download.quota_exhausted and result.download.interrupted
    assert not (settings.image_folder_path / "1005" / "509.gif").exists()
    # The one image saved before the placeholder is still on disk.
    assert (settings.image_folder_path / "1005" / "page001.jpg").read_bytes() == image_bytes(1005, 1)


def test_stop_flag_ends_a_gallery_without_counting_images_as_failed(fetcher, settings, site):
    control = CrawlControl()
    control.stop.set()  # e.g. a ban in another thread, before the first image is opened
    result = crawl_gallery(
        fetcher, 1005, site.gallery_url(1005), image_root=settings.image_folder_path, tag_only=False, control=control
    )
    download = result.download
    assert download.stop_reason is StopReason.STOPPED
    assert (download.saved, download.skipped, download.failed) == (0, 0, 0)
    assert not download.complete and download.interrupted
    assert not any(path.is_file() for path in settings.image_folder_path.rglob("*"))  # no image, no placeholder


def test_quota_flag_set_mid_gallery_marks_the_next_image_quota_stopped(fetcher, settings, site):
    """Another thread sets the shared quota flag while this gallery is between
    images: its loop ends on the flag (without opening another page) and records QUOTA."""
    site.quota_after = 1
    control = CrawlControl()
    # Flip the shared quota flag as soon as the first image page is fetched, so the
    # loop's next iteration sees a flag another thread would have set in a real run.
    original_page = fetcher.page

    def page_then_flag(url: str) -> str:
        html = original_page(url)
        if url.startswith(site.base + "s/"):
            control.quota_exceeded.set()
        return html

    fetcher.page = page_then_flag  # type: ignore[method-assign]
    result = crawl_gallery(
        fetcher, 1005, site.gallery_url(1005), image_root=settings.image_folder_path, tag_only=False, control=control
    )
    assert result.download.stop_reason is StopReason.QUOTA
    assert result.download.saved == 1 and result.download.failed == 0  # image 1 landed, the rest did not fail
    assert not (settings.image_folder_path / "1005" / "509.gif").exists()


# --- many galleries ----------------------------------------------------------------------


def test_crawl_galleries_end_to_end(db, fetcher, settings, site):
    listed(db, fetcher, site)
    result = crawl_galleries(fetcher, db, replace(settings, number_of_thread=3), tag_only=False, rng=random.Random(1))

    assert (result.crawled, result.complete, result.removed, result.failed) == (4, 4, 1, 0)
    rows, pages = db.list_rows(), db.page_rows()
    assert rows[1003].removed == 1
    assert set(pages) == {1005, 1004, 1002, 1001}
    assert all(page.all_downloaded_check == 1 for page in pages.values())
    assert json.loads(pages[1005].tags) == {"sample": ["alpha", "beta two"], "other": ["gamma"]}
    assert (settings.image_folder_path / "1001" / "single.png").read_bytes() == image_bytes(1001, 1)

    site.requests.clear()
    again = crawl_galleries(fetcher, db, settings, tag_only=False)
    assert again.crawled == 0 and site.requests == []  # nothing is due any more


def test_quota_switches_the_rest_to_tags_only(db, fetcher, settings, site):
    listed(db, fetcher, site)
    site.quota_after = 0
    result = crawl_galleries(fetcher, db, replace(settings, number_of_thread=1), tag_only=False)
    assert result.quota_exceeded
    assert result.crawled == 4 and result.complete == 0
    assert all(page.all_downloaded_check == 0 for page in db.page_rows().values())
    assert len(site.paths("/s/")) == 1  # only the image page that showed the placeholder


def test_quota_on_the_first_image_page_stops_every_gallery_but_records_it(db, fetcher, settings, site):
    """quota_after=0: the very first image page is the 509 placeholder, so no
    gallery gets any image; one is the quota-interrupted gallery, all others tags only."""
    listed(db, fetcher, site)
    site.quota_after = 0
    result = crawl_galleries(fetcher, db, replace(settings, number_of_thread=1), tag_only=False)

    assert result.quota_exceeded
    assert result.control_stopped == []
    # Exactly one gallery opened an image page; it is the single quota-interrupted one.
    quota_gids = {int(path.rsplit("/", 1)[-1].split("-")[0]) for path in site.paths("/s/")}
    assert result.quota_stopped == sorted(quota_gids) and len(result.quota_stopped) == 1
    quota_gid = result.quota_stopped[0]

    page_rows = db.page_rows()
    assert set(page_rows) == {1005, 1004, 1002, 1001}  # every live gallery still got its tags
    assert all(page.all_downloaded_check == 0 for page in page_rows.values())
    assert result.failed == 0  # an interrupted download is not a failure
    # Nothing was saved anywhere, and the 509 placeholder never hit the disk.
    assert not (settings.image_folder_path / str(quota_gid) / "509.gif").exists()
    if settings.image_folder_path.exists():
        assert not any(path.is_file() for path in settings.image_folder_path.rglob("*"))
    # The other three galleries were tag-only and therefore have no DownloadResult of their own.
    assert len(site.paths("/s/")) == 1


def test_quota_halfway_through_a_gallery_marks_only_that_gallery(db, fetcher, settings, site):
    """quota_after=3 with seed 0: three real images are served across the earlier
    galleries, then the 509 placeholder appears at gallery 1005's third image;
    1005 is the sole quota-interrupted gallery and everything before it completed."""
    listed(db, fetcher, site)
    site.quota_after = 3
    result = crawl_galleries(fetcher, db, replace(settings, number_of_thread=1), tag_only=False, rng=random.Random(0))

    assert result.quota_exceeded
    assert result.control_stopped == [] and result.failed == 0
    assert result.quota_stopped == [1005]
    # Galleries visited before 1005 (1004) and the tag-only ones after it kept their rows.
    assert db.page_rows()[1004].all_downloaded_check == 1
    assert db.page_rows()[1001].all_downloaded_check == 0  # visited after the quota: tags only
    assert db.page_rows()[1002].all_downloaded_check == 0
    assert db.page_rows()[1005].all_downloaded_check == 0
    # 1005 kept the two images saved before the placeholder; the placeholder itself was not saved.
    folder = settings.image_folder_path / "1005"
    assert sorted(p.name for p in folder.iterdir()) == ["page001.jpg", "page002.jpg"]
    assert not (folder / "509.gif").exists()
    assert not (settings.image_folder_path / "1001").exists()  # later galleries never opened image pages


def test_ban_interrupts_inflight_galleries_and_lists_them_as_stopped(db, settings, site):
    """A ban on one gallery stops the run; the other in-flight gallery ends on
    CrawlControl.stop and must appear in control_stopped, never in failed."""
    # Build the list through a separate fetcher since the gated one blocks on purpose.
    http0 = HttpTransport(settings, HostRateLimiter(0))
    setup_fetcher = Fetcher(http0, http0, max_retries=settings.max_retries, sleep=lambda _: None)
    crawl_list(setup_fetcher, db, site.base, update_all=False)
    setup_fetcher.close()

    site.ban["/g/1004/5f6a7b8c9d/"] = "2 hours."

    class GatedFetcher:
        """Holds gallery 1005's first request until the ban in 1004 has been raised."""

        def __init__(self) -> None:
            self._inner_http = HttpTransport(settings, HostRateLimiter(0))
            self.inner = Fetcher(
                self._inner_http, self._inner_http, max_retries=settings.max_retries, sleep=lambda _: None
            )
            self.entered = threading.Event()
            self.release = threading.Event()

        def page(self, url: str) -> str:
            if url.startswith(site.base + "g/1005/"):
                self.entered.set()
                self.release.wait(timeout=10)
            return self.inner.page(url)

        def download(self, url: str, dest: Path) -> int:
            return self.inner.download(url, dest)

        def close(self) -> None:
            self.inner.close()

    gated = GatedFetcher()
    try:
        with pytest.raises(BannedError, match="about 120 min") as exc_info:
            crawl_galleries(gated, db, replace(settings, number_of_thread=2), tag_only=False, rng=random.Random(5))
        assert gated.entered.wait(timeout=5)
    finally:
        gated.release.set()
        gated.close()

    partial = exc_info.value.partial_result
    assert partial is not None
    # Every gallery that was on the wire when the ban fired ends on CrawlControl.stop.
    assert partial.control_stopped == sorted(partial.control_stopped)  # the list is id-sorted
    assert 1005 in partial.control_stopped
    assert partial.quota_stopped == []
    assert partial.failed == 0  # neither the banned gallery nor a stopped one counts as failed
    # The banned gallery has no page row, so the next run retries it; stopped galleries kept their tags.
    assert 1004 not in db.page_rows()
    for gid in partial.control_stopped:
        assert gid in db.page_rows() and db.page_rows()[gid].all_downloaded_check == 0
    # A stop is not a quota event.
    assert not partial.quota_exceeded


def test_ban_stops_the_gallery_crawl(db, fetcher, settings, site):
    listed(db, fetcher, site)
    for gid, gallery in GALLERIES.items():
        site.ban[f"/g/{gid}/{gallery.url_hash}/"] = "1 hours."
    with pytest.raises(BannedError, match="about 60 min"):
        crawl_galleries(fetcher, db, replace(settings, number_of_thread=2), tag_only=True)


def test_one_broken_gallery_does_not_stop_the_others(db, fetcher, settings, site):
    listed(db, fetcher, site)
    site.fail["/g/1004/5f6a7b8c9d/"] = 10  # more 503s than retries
    result = crawl_galleries(fetcher, db, settings, tag_only=True)
    assert (result.crawled, result.failed, result.removed) == (3, 1, 1)
    assert 1004 not in db.page_rows()  # so the next run tries it again


# --- by URL -------------------------------------------------------------------------------


def test_crawl_single_downloads_without_a_database(fetcher, settings, site):
    result = crawl_single(fetcher, settings, site.gallery_url(1002) + "?p=0")
    assert result.download.complete
    assert (settings.image_folder_path / "1002" / "single.png").exists()
    assert not settings.database_path.exists()


def test_resolve_gallery_url_uses_the_configured_prefix(settings, site):
    assert resolve_gallery_url(settings, site.base + "g/1002/6d7e8f9a0b") == (1002, site.gallery_url(1002))


@pytest.mark.parametrize("url", ["https://elsewhere.test/g/1/ab/", "https://e-hentai.org/g/1/ab/"])
def test_resolve_gallery_url_rejects_other_sites(settings, url):
    with pytest.raises(SettingsError, match="not a gallery URL"):
        resolve_gallery_url(settings, url)


def test_exhentai_url_without_cookies_is_refused_before_any_request(fetcher, site):
    with pytest.raises(SettingsError, match="login cookies"):
        crawl_single(fetcher, Settings(), "https://exhentai.org/g/1/0123456789/")
    assert site.requests == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [("page 001.jpg", "page001.jpg"), ('a:b*c?"d".png', "a_b_c__d_.png"), ("..", None), ("", None), (None, None)],
)
def test_safe_file_name(name, expected):
    assert safe_file_name(name) == expected


def test_gallery_page_url():
    assert gallery_page_url("https://site.test/g/1/ab/", 2) == "https://site.test/g/1/ab/?p=2"
