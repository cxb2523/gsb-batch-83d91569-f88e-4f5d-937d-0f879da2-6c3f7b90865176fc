"""games 命令逐页结局的端到端测试。

全部使用本地 httpx.MockTransport 构造搜索结果页与 appdetails 响应，
不依赖真实 Steam 网络。断言覆盖：
- 逐页结局（已完成/失败/未尝试）的内容与失败原因；
- SQLite 中保留的游戏数据；
- 断点（页面级与 AppID 级）状态及 --resume 的跳过语义；
- 存在失败页时命令以非零状态退出。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import httpx
import pytest

from steam_scraper.cli import main
from steam_scraper.config import Config
from steam_scraper.models import GameInfo
from steam_scraper.scrapers.game_scraper import GameScraper, SteamSearchError
from steam_scraper.utils.checkpoint import Checkpoint
from steam_scraper.utils.page_outcomes import (
    PAGE_COMPLETED,
    PAGE_FAILED,
    PAGE_UNTRIED,
    STATUS_LABELS,
    PageOutcome,
    render_page_outcomes,
)
from steam_scraper.utils.ui import UIManager

_PAGE_HTML = {
    1: '<div class="search_pagination_left">Showing 1 - 25 of 75</div>'
    '<a data-ds-appid="10"></a><a data-ds-appid="11"></a>',
    2: '<div class="search_pagination_left">Showing 1 - 25 of 75</div>'
    '<a data-ds-appid="20"></a><a data-ds-appid="21"></a>',
    3: '<div class="search_pagination_left">Showing 1 - 25 of 75</div>'
    '<a data-ds-appid="30"></a><a data-ds-appid="31"></a>',
}
_ALL_APP_IDS = [10, 11, 20, 21, 30, 31]


def _detail_response(request: httpx.Request) -> httpx.Response:
    app_id = int(request.url.params["appids"])
    return httpx.Response(
        200,
        json={
            str(app_id): {
                "success": True,
                "data": {"name": f"Game {app_id}"},
            }
        },
    )


def _is_list_request(request: httpx.Request) -> bool:
    """计数请求没有 sort_by 参数，借此只统计真正的列表页扫描。"""
    return "appdetails" not in str(request.url) and "sort_by" in request.url.params


def make_search_transport(
    page_overrides: dict[int, httpx.Response] | None = None,
    gate: Callable[[int], Awaitable[None]] | None = None,
) -> httpx.MockTransport:
    """构造搜索结果页传输；page_overrides 可让指定页码返回错误响应。

    gate 在返回指定页码响应前 await，用于保证前序页先完整落库，避免
    依赖调度时序的竞态（页面失败时在途 Worker 会被取消）。
    """
    page_overrides = page_overrides or {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if "appdetails" in str(request.url):
            return _detail_response(request)
        page = int(request.url.params.get("page", "1"))
        if gate is not None:
            await gate(page)
        if page in page_overrides:
            return page_overrides[page]
        return httpx.Response(200, text=_PAGE_HTML[page])

    return httpx.MockTransport(handler)


def make_persist_gate(scraper: GameScraper, required_app_ids: set[int]):
    """返回 (transport 门控协程, 保存包装)，保证 required_app_ids 全部落库后放行。"""
    persisted = asyncio.Event()
    loop = asyncio.get_running_loop()
    original_save = scraper.db.save_games_batch

    def save_and_notify(games, commit=True):
        original_save(games, commit=commit)
        if required_app_ids <= set(scraper.db.get_all_app_ids()):
            loop.call_soon_threadsafe(persisted.set)

    async def gate(page: int) -> None:
        if page >= 2:
            await asyncio.wait_for(persisted.wait(), timeout=5)

    return gate, save_and_notify


def attach_transport(scraper: GameScraper, transport: httpx.MockTransport) -> None:
    scraper.client._client = httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_all_pages_completed_records_full_outcome(app_config):
    app_config.http.max_retries = 0
    checkpoint = Checkpoint(config=app_config, save_interval=0)
    scraper = GameScraper(config=app_config, checkpoint=checkpoint)
    attach_transport(scraper, make_search_transport())
    try:
        app_ids = await scraper.run()

        assert sorted(app_ids) == sorted(_ALL_APP_IDS)
        outcomes = scraper.get_page_outcomes()
        assert [outcome.page for outcome in outcomes] == [1, 2, 3]
        assert all(outcome.status == PAGE_COMPLETED for outcome in outcomes)
        assert all(outcome.reason == "" for outcome in outcomes)

        assert sorted(scraper.get_app_ids()) == sorted(_ALL_APP_IDS)
        for page in (1, 2, 3):
            assert checkpoint.is_page_completed(page)
        for app_id in _ALL_APP_IDS:
            assert checkpoint.is_appid_completed(app_id)
    finally:
        await scraper.client.close()
        scraper.db.close()


@pytest.mark.asyncio
async def test_page_two_503_marks_failed_and_keeps_page_one(app_config, monkeypatch):
    app_config.http.max_retries = 0
    checkpoint = Checkpoint(config=app_config, save_interval=0)
    scraper = GameScraper(config=app_config, checkpoint=checkpoint)
    gate, save_and_notify = make_persist_gate(scraper, {10, 11})
    monkeypatch.setattr(scraper.db, "save_games_batch", save_and_notify)
    attach_transport(
        scraper,
        make_search_transport({2: httpx.Response(503, text="unavailable")}, gate=gate),
    )
    try:
        with pytest.raises(SteamSearchError) as error:
            await scraper.run()
        assert "第 2 页" in str(error.value)

        outcomes = scraper.get_page_outcomes()
        assert outcomes == [
            PageOutcome(1, PAGE_COMPLETED, ""),
            PageOutcome(2, PAGE_FAILED, outcomes[1].reason),
            PageOutcome(3, PAGE_UNTRIED, outcomes[2].reason),
        ]
        assert "第 2 页" in outcomes[1].reason
        assert outcomes[2].reason  # 未尝试必须带原因，不能伪装成成功

        # 第 1 页数据已落库，失败页/未尝试页没有任何数据
        assert sorted(scraper.get_app_ids()) == [10, 11]
        assert checkpoint.is_page_completed(1)
        assert not checkpoint.is_page_completed(2)
        assert not checkpoint.is_page_completed(3)
        assert checkpoint.is_appid_completed(10)
        assert checkpoint.is_appid_completed(11)
        for app_id in (20, 21, 30, 31):
            assert not checkpoint.is_appid_completed(app_id)
    finally:
        await scraper.client.close()
        scraper.db.close()


@pytest.mark.asyncio
async def test_invalid_appid_marks_page_failed_without_half_page(
    app_config, monkeypatch
):
    app_config.http.max_retries = 0
    checkpoint = Checkpoint(config=app_config, save_interval=0)
    scraper = GameScraper(config=app_config, checkpoint=checkpoint)
    gate, save_and_notify = make_persist_gate(scraper, {10, 11})
    monkeypatch.setattr(scraper.db, "save_games_batch", save_and_notify)

    invalid_html = (
        '<div class="search_pagination_left">Showing 1 - 25 of 75</div>'
        '<a data-ds-appid="20"></a><a data-ds-appid="bad"></a>'
    )
    attach_transport(
        scraper,
        make_search_transport({2: httpx.Response(200, text=invalid_html)}, gate=gate),
    )
    try:
        with pytest.raises(SteamSearchError) as error:
            await scraper.run()
        assert "无效 AppID" in str(error.value)

        outcomes = scraper.get_page_outcomes()
        assert [outcome.status for outcome in outcomes] == [
            PAGE_COMPLETED,
            PAGE_FAILED,
            PAGE_UNTRIED,
        ]
        assert outcomes[1].page == 2
        assert "无效 AppID" in outcomes[1].reason
        assert outcomes[2].page == 3 and outcomes[2].reason

        # 非法 AppID 页的任何 AppID 都不得落库
        assert sorted(scraper.get_app_ids()) == [10, 11]
        assert checkpoint.is_page_completed(1)
        assert not checkpoint.is_page_completed(2)
        assert not checkpoint.is_page_completed(3)
    finally:
        await scraper.client.close()
        scraper.db.close()


@pytest.mark.asyncio
async def test_stop_mid_run_marks_remaining_pages_untried(app_config, monkeypatch):
    stop_event = threading.Event()
    checkpoint = Checkpoint(config=app_config, save_interval=0)
    scraper = GameScraper(
        config=app_config, checkpoint=checkpoint, stop_event=stop_event
    )
    attach_transport(scraper, make_search_transport())

    async def stop_on_first_details(app_id: int) -> GameInfo:
        stop_event.set()
        return GameInfo(app_id=app_id, name=f"Game {app_id}")

    monkeypatch.setattr(scraper, "get_total_pages", AsyncMock(return_value=2))
    monkeypatch.setattr(scraper, "get_game_details", stop_on_first_details)
    try:
        await scraper.run()  # 优雅停止，不抛错

        outcomes = scraper.get_page_outcomes()
        assert [outcome.page for outcome in outcomes] == [1, 2]
        # 第 1 页未全部结算、第 2 页未扫描，都不能标记为已完成或失败
        assert all(outcome.status == PAGE_UNTRIED for outcome in outcomes)
        assert all(outcome.reason for outcome in outcomes)
        assert not checkpoint.is_page_completed(1)
        assert not checkpoint.is_page_completed(2)
    finally:
        await scraper.client.close()
        scraper.db.close()


def test_render_page_outcomes_prints_labels_and_summary(app_config, capsys) -> None:
    ui = UIManager()
    render_page_outcomes(
        [
            PageOutcome(1, PAGE_COMPLETED),
            PageOutcome(2, PAGE_FAILED, "爬取第 2 页列表失败: 503"),
            PageOutcome(3, PAGE_UNTRIED, "采集中途停止，该页未扫描"),
        ],
        ui,
    )
    output = capsys.readouterr().out
    assert "逐页采集结局" in output
    for label in STATUS_LABELS.values():
        assert label in output
    # 页码列与原因分列展示：原因文本完整出现，且不属于已完成/未尝试行
    assert "爬取第 2 页列表失败: 503" in output
    assert "采集中途停止，该页未扫描" in output
    assert "已完成 1 页，失败 1 页，未尝试 1 页" in output


def test_cli_failure_run_exits_nonzero_and_reports_each_page(
    app_config, monkeypatch, capsys
):
    app_config.http.max_retries = 0
    monkeypatch.setattr(Config, "load", lambda: app_config)

    # 第一次运行：第 2 页 503，第 1 页成功落库
    original_init = GameScraper.__init__
    persisted = threading.Event()

    def init_with_mock(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        original_save = self.db.save_games_batch

        def save_and_notify(games, commit=True):
            original_save(games, commit=commit)
            if {10, 11} <= set(self.db.get_all_app_ids()):
                persisted.set()

        self.db.save_games_batch = save_and_notify

        async def gate(page: int):
            if page >= 2:
                await asyncio.to_thread(persisted.wait, 5)

        self.client._client = httpx.AsyncClient(
            transport=make_search_transport(
                {2: httpx.Response(503, text="unavailable")}, gate=gate
            )
        )

    monkeypatch.setattr(GameScraper, "__init__", init_with_mock)

    with pytest.raises(SystemExit) as exc:
        main(["games"])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    assert "逐页采集结局" in output
    assert "已完成" in output and "失败" in output and "未尝试" in output
    assert "爬取完成" not in output

    # 数据库与断点保留第 1 页成果
    checkpoint = Checkpoint(config=app_config)
    assert checkpoint.is_page_completed(1)
    assert not checkpoint.is_page_completed(2)
    assert not checkpoint.is_page_completed(3)
    database = GameScraper(config=app_config)
    try:
        assert sorted(database.get_app_ids()) == [10, 11]
    finally:
        database.db.close()


def test_cli_resume_only_requests_unfinished_pages(app_config, monkeypatch, capsys):
    app_config.http.max_retries = 0
    monkeypatch.setattr(Config, "load", lambda: app_config)

    # 预置第一次运行后的断点：第 1 页已完成
    checkpoint = Checkpoint(config=app_config, save_interval=0)
    for app_id in (10, 11):
        checkpoint.mark_appid_completed(app_id)
    checkpoint.mark_page_completed(1)
    checkpoint.save()

    # 预置第 1 页已落库的游戏数据，验证恢复不会清除既有数据
    seed_scraper = GameScraper(config=app_config)
    try:
        seed_scraper.db.save_games_batch(
            [GameInfo(10, "Game 10"), GameInfo(11, "Game 11")]
        )
    finally:
        seed_scraper.db.close()

    visited_list_pages: list[str] = []

    async def tracking_handler(request: httpx.Request) -> httpx.Response:
        if "appdetails" in str(request.url):
            return _detail_response(request)
        if _is_list_request(request):
            visited_list_pages.append(request.url.params["page"])
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, text=_PAGE_HTML[page])

    original_init = GameScraper.__init__

    def init_with_mock(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(tracking_handler)
        )

    monkeypatch.setattr(GameScraper, "__init__", init_with_mock)

    main(["games", "--resume"])  # 全部成功，退出码为 0

    # 恢复运行只扫描未完成的第 2、3 页
    assert visited_list_pages == ["2", "3"]

    output = capsys.readouterr().out
    assert "逐页采集结局" in output
    assert output.count("已完成") >= 3  # 三页均为已完成
    # 成功运行的汇总里失败与未尝试计数均为 0，且不会出现非零计数
    assert "失败 0 页" in output
    assert "未尝试 0 页" in output
    assert "失败 1 页" not in output
    assert "未尝试 1 页" not in output

    resumed_checkpoint = Checkpoint(config=app_config)
    for page in (1, 2, 3):
        assert resumed_checkpoint.is_page_completed(page)
    for app_id in _ALL_APP_IDS:
        assert resumed_checkpoint.is_appid_completed(app_id)

    verify_scraper = GameScraper(config=app_config)
    try:
        assert sorted(verify_scraper.get_app_ids()) == sorted(_ALL_APP_IDS)
    finally:
        verify_scraper.db.close()
