import os
from bs4 import BeautifulSoup
import requests
import requests_cache
from urllib.parse import urlparse, urljoin
import time
import shutil
import logging
import sys
from playwright.sync_api import sync_playwright

# destlocationdir = "/data/"
language = "es"
fulldir = "/data/" # + language

logger = logging.getLogger('mylogger')
logger.setLevel(logging.INFO)  # set logger level
logFormatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
consoleHandler = logging.StreamHandler(sys.stdout)  # set streamhandler to stdout
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


def get_sitemap():
    requests_cache.install_cache(fulldir + '/sitemap')
    session = requests_cache.CachedSession('sitemap', expire_after=86400)  # 24h
    web = "https://www.place.holder/"
    links = []
    r = requests.get(web + language + "/sitemap.xml")
    soup = BeautifulSoup(r.text, "lxml")
    url_locs = soup.find_all("loc")
    for url in url_locs:
        links.append(url.text)
    return ["https://www.place.holder/VIDEO"]
    # return links


class VideoDownloadError(RuntimeError):
    """Raised when a video cannot be downloaded completely."""


def download_video(url, filename):
    """Download ``url`` to ``filename`` only for a complete 2xx response.

    The body is streamed into a ``.part`` file next to the destination and only
    moved into place once the download finished, so a non-2xx status, a network
    error, or an interrupted body never leaves a truncated video file behind.
    """
    temp_filename = filename + ".part"
    try:
        with requests.get(url, stream=True) as r:
            if not (200 <= r.status_code < 300):
                raise VideoDownloadError("HTTP %s for %s" % (r.status_code, url))
            with open(temp_filename, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        os.replace(temp_filename, filename)
    except BaseException:
        # Drop the half-written body so a failed download leaves no artifact.
        if os.path.isfile(temp_filename):
            os.remove(temp_filename)
        raise


def _page_path(url, mirror_root):
    """Filesystem path and served URL path of a page, trailing slashes removed."""
    url_path = urlparse(url).path.rstrip("/")
    if not url_path:
        # The site root *is* the mirror root: its page is served as index.html
        # and must not produce a "<root>.html" file outside the mirror.
        return mirror_root, ""
    return mirror_root + url_path, url_path


def _local_absolute_path(url_path):
    """The absolute URL nginx serves ``url_path`` from below the mirror root."""
    return "/" + url_path.lstrip("/")


def _remove_page_artifacts(local_page_path, mirror_root):
    """Remove the HTML and video files a previous crawl wrote for this page.

    Only this page's own artifacts are removed: its ``.html`` file, its
    ``index.html``, and the video files stored in its directory, together with
    any leftover partial download. ``.html`` files other than ``index.html``
    in that directory may belong to nested pages (``.../sub.html``), so they
    are left alone. The mirror root also holds the sitemap cache, which is
    skipped as well.
    """
    if os.path.isfile(local_page_path + ".html"):
        os.remove(local_page_path + ".html")

    if not os.path.isdir(local_page_path):
        return

    if os.path.isfile(local_page_path + "/index.html"):
        os.remove(local_page_path + "/index.html")

    at_mirror_root = os.path.abspath(local_page_path) == os.path.abspath(mirror_root)
    for name in os.listdir(local_page_path):
        if name != ".html" and name.endswith(".html"):
            continue  # a nested page's own HTML file (e.g. ".../sub.html")
        if at_mirror_root and name.startswith("sitemap"):
            continue  # requests_cache database
        candidate = local_page_path + "/" + name
        if os.path.isfile(candidate):
            os.remove(candidate)


def _video_source_tag(video):
    """The tag carrying the video's URL: the element itself or its first source."""
    if video.get("src"):
        return video
    return video.find("source", src=True)


def download_webpage(url, context):
    """Mirror one page into ``fulldir``.

    Regular pages are written to ``<path>/index.html``; pages containing a
    ``<video>`` are written to ``<path>.html`` with the video stored inside the
    sibling ``<path>/`` directory. The video ``src`` is rewritten to the local
    absolute URL of the file actually downloaded. Re-crawling the same page
    first removes the artifacts written for it last time.
    """
    page = context.new_page()
    try:
        page.goto(url)
        time.sleep(3)
        page_content = page.content()
    finally:
        page.close()

    bs_page = BeautifulSoup(page_content, "html.parser")
    mirror_root = fulldir.rstrip("/")
    local_page_path, url_path = _page_path(url, mirror_root)

    video = bs_page.find("video")
    if video is not None:
        _mirror_video_page(bs_page, video, local_page_path, url_path, mirror_root)
    else:
        _mirror_regular_page(bs_page, local_page_path, mirror_root)


def _mirror_regular_page(bs_page, local_page_path, mirror_root):
    _remove_page_artifacts(local_page_path, mirror_root)
    os.makedirs(local_page_path, exist_ok=True)
    _rewrite_hrefs(bs_page)
    html_filename = local_page_path + "/index.html"
    _write_html(html_filename, bs_page)
    logger.info("Saved %s", html_filename)


def _mirror_video_page(bs_page, video, local_page_path, url_path, mirror_root):
    source_tag = _video_source_tag(video)
    if source_tag is None:
        error = VideoDownloadError(
            "no video source for page %s" % local_page_path
        )
        logger.error("Failed to mirror video page %s: %s", local_page_path, error)
        raise error

    video_url = urljoin("https://www.place.holder/", source_tag["src"])
    filename = os.path.basename(urlparse(video_url).path)
    if not filename:
        error = VideoDownloadError("video URL %s has no filename" % video_url)
        logger.error("Failed to mirror video page %s: %s", local_page_path, error)
        raise error

    local_video_path = local_page_path + "/" + filename
    local_absolute_video_path = _local_absolute_path(url_path + "/" + filename)

    _remove_page_artifacts(local_page_path, mirror_root)
    os.makedirs(local_page_path, exist_ok=True)

    try:
        download_video(video_url, local_video_path)
        # The rewritten src must resolve to a file that really exists on disk.
        if not os.path.isfile(local_video_path):
            raise VideoDownloadError(
                "video %s was not written to %s" % (video_url, local_video_path)
            )
    except Exception as exc:
        logger.error(
            "Failed to mirror video page %s: %s (%s)",
            local_page_path, exc, video_url,
        )
        raise

    # Point the markup at the file that is really on disk.
    if video.get("src"):
        video["src"] = local_absolute_video_path
    else:
        source_tag["src"] = local_absolute_video_path

    _rewrite_hrefs(bs_page)
    html_filename = local_page_path + (".html" if url_path else "/index.html")
    _write_html(html_filename, bs_page)
    logger.info("Saved %s (video %s)", html_filename, local_absolute_video_path)


def _rewrite_hrefs(bs_page):
    for tag_name, attribute_name in [("a", "href"), ("link", "href"), ("base", "href")]:
        for tag in bs_page.find_all(tag_name, **{attribute_name: True}):
            if tag[attribute_name].startswith("https://www.place.holder/"):
                tag[attribute_name] = tag[attribute_name].replace("https://www.place.holder", "")


def _write_html(html_filename, bs_page):
    with open(html_filename, "w", encoding="utf-8") as file:
        file.write(str(bs_page))


def mirror_pages(links, context):
    """Mirror every link, logging failures without stopping the remaining pages."""
    for link in links:
        logger.info(link)
        try:
            download_webpage(link, context)
        except Exception:
            logger.exception(
                "Failed to mirror %s; continuing with remaining pages", link
            )


if __name__ == '__main__':
    if not os.path.exists(fulldir):
        os.makedirs(fulldir)
    links = get_sitemap()
    headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    }
    with sync_playwright() as p:
        # The full Chromium, not the default headless shell: the shell reads no
        # managed policies, so it would ignore the CA distrust in the image.
        browser = p.chromium.launch(channel="chromium")
        context = browser.new_context(extra_http_headers=headers)
        mirror_pages(links, context)
        browser.close()

