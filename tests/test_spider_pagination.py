# -*- coding: utf-8 -*-
"""逐页采集记录与停止原因的回归测试（不访问网络）。

真实的 ``main_ed.py`` 会在依赖桩（customtkinter、tkinter、PIL、requests）
下被加载，测试中再用伪造的 session 响应替换模块级 session，因此：

* 不会发起任何真实网络请求（同时有 socket 层面的网络守卫兜底）；
* ``time.sleep`` 被替换为记录调用参数的空操作，测试无需等待 3 秒。

覆盖五类场景：正常结束、空列表、nextId 重复、手动停止、关键词过滤，
另外补充数量上限、请求间隔、失败重试与生成器提前关闭的测试。

Run with::

    python -X utf8 -m unittest discover -s tests -v
"""

import copy
import importlib.util
import os
import socket
import sys
import types
import unittest
from unittest import mock

MAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main_ed.py"
)


# --------------------------------------------------------------------------- #
# Dependency stubs                                                            #
# --------------------------------------------------------------------------- #

class _StubTk(object):
    def __init__(self, *args, **kwargs):
        pass


class _StubMessageBox(object):
    def __init__(self):
        self.calls = []

    def _record(self, kind, title, message):
        self.calls.append({"kind": kind, "title": title, "message": message})

    def showinfo(self, title, message=None, **kwargs):
        self._record("showinfo", title, message)

    def showwarning(self, title, message=None, **kwargs):
        self._record("showwarning", title, message)

    def showerror(self, title, message=None, **kwargs):
        self._record("showerror", title, message)

    def askyesno(self, title, message=None, **kwargs):
        self._record("askyesno", title, message)
        return False


class _ForbiddenSession(object):
    """任何真实网络访问都会直接失败。"""

    def _forbidden(self, *args, **kwargs):
        raise AssertionError("network access is not allowed in the test suite")

    get = _forbidden
    post = _forbidden
    put = _forbidden
    delete = _forbidden
    head = _forbidden
    request = _forbidden


class _StubRequestException(Exception):
    pass


class _StubTimeout(_StubRequestException):
    pass


def _build_stub_modules():
    ctk = types.ModuleType("customtkinter")
    ctk.CTk = _StubTk
    ctk.set_appearance_mode = lambda mode: None
    ctk.set_default_color_theme = lambda theme: None

    tkinter = types.ModuleType("tkinter")
    tkinter.filedialog = types.SimpleNamespace(
        asksaveasfilename=lambda **kwargs: "",
        askopenfilename=lambda **kwargs: "",
    )
    tkinter.messagebox = _StubMessageBox()

    pil = types.ModuleType("PIL")
    pil.Image = types.SimpleNamespace()
    pil.ImageTk = types.SimpleNamespace()

    requests = types.ModuleType("requests")
    requests.session = lambda: _ForbiddenSession()
    requests.get = _ForbiddenSession()._forbidden
    requests.post = _ForbiddenSession()._forbidden
    requests.exceptions = types.SimpleNamespace(
        RequestException=_StubRequestException,
        Timeout=_StubTimeout,
        ConnectionError=_StubRequestException,
        HTTPError=_StubRequestException,
    )

    return {
        "customtkinter": ctk,
        "tkinter": tkinter,
        "PIL": pil,
        "requests": requests,
    }


def _load_main_module():
    """在依赖桩就位的情况下导入真实的 ``main_ed.py``。"""
    stubs = _build_stub_modules()
    previous = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("main_ed_under_test", MAIN_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["main_ed_under_test"] = module
        spec.loader.exec_module(module)
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        sys.modules.pop("main_ed_under_test", None)
    return module


MAIN = _load_main_module()


# --------------------------------------------------------------------------- #
# Network guard                                                               #
# --------------------------------------------------------------------------- #

_NETWORK_GUARDS = []


def _network_forbidden(*args, **kwargs):
    raise AssertionError("network access is not allowed in the test suite")


def setUpModule():
    _NETWORK_GUARDS.extend([
        mock.patch.object(socket.socket, "connect", _network_forbidden),
        mock.patch.object(socket, "create_connection", _network_forbidden),
    ])
    for guard in _NETWORK_GUARDS:
        guard.start()


def tearDownModule():
    for guard in reversed(_NETWORK_GUARDS):
        guard.stop()
    _NETWORK_GUARDS.clear()


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #

class FakeResponse(object):
    """伪造的 requests 响应对象。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession(object):
    """按预置页码顺序返回响应的伪造 session，并记录每次请求的入参。"""

    def __init__(self, pages):
        # pages: [(status_code, payload), ...] 或 FakeResponse 列表
        self.pages = list(pages)
        self.calls = []
        self._index = 0

    def post(self, url, headers=None, cookies=None, json=None, timeout=None):
        # requests 在发送瞬间序列化请求体，这里同样快照一份，
        # 避免后续对同一个可变 dict 的修改污染历史调用记录
        self.calls.append({
            "url": url,
            "headers": headers,
            "cookies": cookies,
            "json": copy.deepcopy(json),
            "timeout": timeout,
        })
        if self._index >= len(self.pages):
            raise AssertionError("采集器发起了超出预置响应数量的额外请求")
        page = self.pages[self._index]
        self._index += 1
        if isinstance(page, FakeResponse):
            return page
        status_code, payload = page
        return FakeResponse(payload, status_code)


def make_item(name, item_id=None, price="10.50"):
    return {
        "c2cItemsName": name,
        "showPrice": price,
        "c2cItemsId": item_id if item_id is not None else "id-%s" % name,
    }


def make_items(n, prefix="item"):
    return [make_item("%s-%d" % (prefix, i), item_id="%s-id-%d" % (prefix, i))
            for i in range(n)]


def make_payload(items, next_id):
    return {"code": 0, "message": "0", "data": {"data": items, "nextId": next_id}}


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #

class SpiderPaginationTestCase(unittest.TestCase):
    def setUp(self):
        # 跳过真实的 3 秒等待，只记录 sleep 收到的间隔参数
        self.sleeps = []
        self.sleep_patcher = mock.patch.object(
            MAIN.time, "sleep", side_effect=lambda seconds: self.sleeps.append(seconds)
        )
        self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

        # 登录检查直接放行，不发起任何请求
        self.login_patcher = mock.patch.object(MAIN, "requet1", return_value=True)
        self.login_mock = self.login_patcher.start()
        self.addCleanup(self.login_patcher.stop)

    def make_crawler(self, gui_callback=None):
        return MAIN.SpiderCrawler("a=1; b=2", gui_callback=gui_callback)

    def run_spider(self, pages, keyword=None, crawler=None):
        crawler = crawler or self.make_crawler()
        fake_session = FakeSession(pages)
        with mock.patch.object(MAIN, "session", fake_session):
            products = list(crawler.spider("默认", "综合", "默认", keyword))
        return crawler, fake_session, products

    # -- 场景一：正常到达最后一页 ------------------------------------------- #

    def test_normal_end_records_every_page_and_last_page_reason(self):
        pages = [
            (200, make_payload(make_items(3, "a"), next_id="next-1")),
            (200, make_payload(make_items(2, "b"), next_id=None)),
        ]
        crawler, fake_session, products = self.run_spider(pages)

        self.assertEqual(crawler.stop_reason, MAIN.SpiderCrawler.STOP_REASON_LAST_PAGE)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(crawler.page_records, [
            {"page": 1, "returned_count": 3, "produced_count": 3,
             "next_id_empty": False},
            {"page": 2, "returned_count": 2, "produced_count": 2,
             "next_id_empty": True},
        ])
        self.assertEqual(len(products), 5)
        # 逐页记录不得改变导出商品的 name、price、link 三个字段
        self.assertEqual(set(products[0].keys()), {"name", "price", "link"})
        self.assertEqual(products[0]["name"], "a-0")
        self.assertEqual(products[0]["price"], 10.5)
        self.assertIn("itemsId=a-id-0", products[0]["link"])

        # 每页恰好一个请求，且 nextId 被正确带到下一页请求体
        self.assertEqual(len(fake_session.calls), 2)
        self.assertIsNone(fake_session.calls[0]["json"]["nextId"])
        self.assertEqual(fake_session.calls[1]["json"]["nextId"], "next-1")
        # 每页请求前固定等待 3 秒
        self.assertEqual(self.sleeps, [3, 3])

    # -- 场景二：接口返回空列表 --------------------------------------------- #

    def test_empty_list_stops_with_empty_list_reason(self):
        pages = [
            (200, make_payload(make_items(2, "a"), next_id="next-1")),
            (200, make_payload([], next_id=None)),
        ]
        crawler, fake_session, products = self.run_spider(pages)

        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_EMPTY_LIST)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(crawler.page_records[0], {
            "page": 1, "returned_count": 2, "produced_count": 2,
            "next_id_empty": False,
        })
        # 空列表页同样留下逐页记录：返回 0 条、产出 0 条
        self.assertEqual(crawler.page_records[1], {
            "page": 2, "returned_count": 0, "produced_count": 0,
            "next_id_empty": True,
        })
        self.assertEqual(len(products), 2)
        self.assertEqual(len(fake_session.calls), 2)

    # -- 场景三：nextId 重复（翻页停滞） ------------------------------------ #

    def test_duplicated_next_id_stops_immediately_without_further_request(self):
        pages = [
            (200, make_payload(make_items(2, "a"), next_id="stuck-id")),
            (200, make_payload(make_items(2, "b"), next_id="stuck-id")),
            # 预置第三页响应，但停滞时绝不允许请求它
            (200, make_payload(make_items(2, "c"), next_id="next-3")),
        ]
        crawler, fake_session, products = self.run_spider(pages)

        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_NEXT_ID_DUPLICATED)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(crawler.page_records[1], {
            "page": 2, "returned_count": 2, "produced_count": 2,
            "next_id_empty": False,
        })
        self.assertEqual(len(products), 4)
        # 只发出两页请求，停滞页之后不再发请求
        self.assertEqual(len(fake_session.calls), 2)
        self.assertEqual(fake_session.calls[1]["json"]["nextId"], "stuck-id")

    # -- 场景四：用户手动停止 ----------------------------------------------- #

    def test_manual_stop_during_page_iteration_records_partial_page(self):
        crawler = self.make_crawler()
        state = {"yielded": 0}

        def stop_after_fourth_product(product, offset, elapsed_time, interval):
            state["yielded"] += 1
            if state["yielded"] == 4:
                crawler.stop()

        crawler.gui_callback = stop_after_fourth_product
        pages = [
            (200, make_payload(make_items(3, "a"), next_id="next-1")),
            (200, make_payload(make_items(3, "b"), next_id="next-2")),
            (200, make_payload(make_items(3, "c"), next_id="next-3")),
        ]
        _crawler, fake_session, products = self.run_spider(pages, crawler=crawler)

        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_MANUAL_STOP)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(crawler.page_records[0], {
            "page": 1, "returned_count": 3, "produced_count": 3,
            "next_id_empty": False,
        })
        # 第二页只产出了第一条就被手动停止，但接口返回条数仍按整页记录
        self.assertEqual(crawler.page_records[1], {
            "page": 2, "returned_count": 3, "produced_count": 1,
            "next_id_empty": False,
        })
        self.assertEqual(len(products), 4)
        # 停止后不再发起第三页请求
        self.assertEqual(len(fake_session.calls), 2)

    def test_manual_stop_via_generator_close_still_leaves_conclusion(self):
        # 模拟界面线程停止后不再迭代生成器的情形
        crawler = self.make_crawler()
        pages = [
            (200, make_payload(make_items(3, "a"), next_id="next-1")),
            (200, make_payload(make_items(3, "b"), next_id="next-2")),
        ]
        fake_session = FakeSession(pages)
        with mock.patch.object(MAIN, "session", fake_session):
            generator = crawler.spider("默认", "综合", "默认")
            collected = [next(generator), next(generator), next(generator)]
            crawler.stop()
            generator.close()

        self.assertEqual(len(collected), 3)
        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_MANUAL_STOP)
        # 第一页已完整处理，留有逐页记录；第二页请求从未发出
        self.assertEqual(len(crawler.page_records), 1)
        self.assertEqual(crawler.page_records[0]["page"], 1)
        self.assertEqual(crawler.page_records[0]["produced_count"], 3)
        self.assertEqual(len(fake_session.calls), 1)

    # -- 场景五：关键词过滤 ------------------------------------------------- #

    def test_keyword_filter_only_affects_produced_count(self):
        keyword = "手办"
        pages = [
            (200, make_payload([
                make_item("手办A"), make_item("明信片"),
                make_item("手办B"), make_item("徽章"),
            ], next_id="next-1")),
            (200, make_payload([
                make_item("海报"), make_item("钥匙扣"),
            ], next_id=None)),
        ]
        crawler, fake_session, products = self.run_spider(pages, keyword=keyword)

        # 关键词不影响停止判定：最后一页 nextId 为空，仍属正常结束
        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_LAST_PAGE)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(crawler.page_records[0], {
            "page": 1, "returned_count": 4, "produced_count": 2,
            "next_id_empty": False,
        })
        # 第二页无命中：返回 2 条、实际产出 0 条，页码仍正常递增
        self.assertEqual(crawler.page_records[1], {
            "page": 2, "returned_count": 2, "produced_count": 0,
            "next_id_empty": True,
        })
        self.assertEqual([p["name"] for p in products], ["手办A", "手办B"])
        # offset 按接口返回条数累计，不受过滤影响
        self.assertEqual(crawler.offset, 6)
        self.assertEqual(len(fake_session.calls), 2)

    # -- 补充：数量上限 ----------------------------------------------------- #

    def test_keyword_cap_of_200_stops_with_limit_reason(self):
        keyword = "item"
        pages = [
            (200, make_payload(make_items(100, "item"), next_id="next-1")),
            (200, make_payload(make_items(100, "item"), next_id="next-2")),
            (200, make_payload(make_items(100, "item"), next_id="next-3")),
        ]
        crawler, fake_session, products = self.run_spider(pages, keyword=keyword)

        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_LIMIT_REACHED)
        self.assertEqual(len(crawler.page_records), 2)
        self.assertEqual(
            [record["produced_count"] for record in crawler.page_records],
            [100, 100],
        )
        self.assertEqual(crawler.offset, 200)
        self.assertEqual(len(products), 200)
        # 达到上限后不再请求第三页
        self.assertEqual(len(fake_session.calls), 2)

    def test_default_limit_and_interval_constants(self):
        self.assertEqual(MAIN.SpiderCrawler.REQUEST_INTERVAL, 3)
        self.assertEqual(MAIN.SpiderCrawler.DEFAULT_MAX_OFFSET, 20000)
        self.assertEqual(MAIN.SpiderCrawler.KEYWORD_MAX_OFFSET, 200)

    # -- 补充：失败请求重试不会产生页码记录 -------------------------------- #

    def test_failed_request_is_retried_without_consuming_a_page(self):
        pages = [
            (500, {"code": -1, "message": "server error"}),
            (200, make_payload(make_items(2, "a"), next_id=None)),
        ]
        crawler, fake_session, products = self.run_spider(pages)

        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_LAST_PAGE)
        self.assertEqual(len(crawler.page_records), 1)
        self.assertEqual(crawler.page_records[0]["page"], 1)
        self.assertEqual(crawler.page_records[0]["returned_count"], 2)
        self.assertEqual(len(products), 2)
        # 失败请求与成功请求各等待一次 3 秒间隔
        self.assertEqual(self.sleeps, [3, 3])
        self.assertEqual(len(fake_session.calls), 2)

    def test_each_crawl_run_resets_previous_records(self):
        first_pages = [(200, make_payload(make_items(1, "a"), next_id=None))]
        crawler, _fake, _products = self.run_spider(first_pages)
        self.assertEqual(len(crawler.page_records), 1)
        self.assertIsNotNone(crawler.stop_reason)

        second_pages = [(200, make_payload([], next_id=None))]
        crawler, _fake, products = self.run_spider(second_pages, crawler=crawler)
        self.assertEqual(products, [])
        self.assertEqual(len(crawler.page_records), 1)
        self.assertEqual(crawler.page_records[0]["page"], 1)
        self.assertEqual(crawler.stop_reason,
                         MAIN.SpiderCrawler.STOP_REASON_EMPTY_LIST)


if __name__ == "__main__":
    unittest.main()
