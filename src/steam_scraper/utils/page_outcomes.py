"""games 命令逐页结局记录与终端渲染。

每次 ``games`` 采集都会为扫描范围内的每一页记录一个明确结局：

- ``completed``（已完成）：该页全部 AppID 均已写入数据库，且页面断点已更新；
- ``failed``（失败）：请求失败、AppID 非法或列表无法解析，附带页码与原因；
- ``untried``（未尝试）：采集中途停止或前序页失败后停止，后续页未被扫描。

结局只描述本次运行扫描范围内的页面；断点语义仍由 Checkpoint 负责，
本模块不直接修改断点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from steam_scraper.utils.ui import UIManager, terminal_text

PageStatus = Literal["completed", "failed", "untried"]

PAGE_COMPLETED: PageStatus = "completed"
PAGE_FAILED: PageStatus = "failed"
PAGE_UNTRIED: PageStatus = "untried"

#: 结局在终端中的中文标签，必须与用户可见文案保持稳定，测试据此断言。
STATUS_LABELS: dict[PageStatus, str] = {
    PAGE_COMPLETED: "已完成",
    PAGE_FAILED: "失败",
    PAGE_UNTRIED: "未尝试",
}

_STATUS_STYLES: dict[PageStatus, str] = {
    PAGE_COMPLETED: "green",
    PAGE_FAILED: "red bold",
    PAGE_UNTRIED: "yellow",
}


@dataclass(frozen=True)
class PageOutcome:
    """单个搜索结果页在本次运行中的结局。

    Attributes:
        page: 页码（从 1 开始）。
        status: 页面结局，取值见 ``PageStatus``。
        reason: 失败或未尝试的具体原因；已完成页面为空字符串。
    """

    page: int
    status: PageStatus
    reason: str = ""


def render_page_outcomes(outcomes: list[PageOutcome], ui: UIManager) -> None:
    """在命令结束时打印逐页结局表格与汇总。

    没有任何页面结局（例如搜索计数阶段即失败）时不输出任何内容。
    失败页必须带页码和原因；未尝试页同样给出原因，避免被误读为成功。

    Args:
        outcomes: 按页码升序排列的页面结局列表。
        ui: 负责终端输出的 UI 管理器。
    """
    if not outcomes:
        return

    table = ui.create_table(title="逐页采集结局")
    table.add_column("页码", style="cyan", justify="right")
    table.add_column("结局")
    table.add_column("原因", style="dim")

    for outcome in outcomes:
        label = STATUS_LABELS[outcome.status]
        table.add_row(
            str(outcome.page),
            f"[{_STATUS_STYLES[outcome.status]}]{label}[/{_STATUS_STYLES[outcome.status]}]",
            terminal_text(outcome.reason).plain,
        )

    ui.console.print(table)

    completed = sum(1 for item in outcomes if item.status == PAGE_COMPLETED)
    failed = sum(1 for item in outcomes if item.status == PAGE_FAILED)
    untried = sum(1 for item in outcomes if item.status == PAGE_UNTRIED)
    summary = f"页面汇总：已完成 {completed} 页，失败 {failed} 页，未尝试 {untried} 页"
    if failed:
        ui.print_error(summary)
    else:
        ui.print_warning(summary) if untried else ui.print_success(summary)


def has_failed_pages(outcomes: list[PageOutcome]) -> bool:
    """判断逐页结局中是否存在失败页，用于决定命令的退出状态。

    Returns:
        存在至少一个失败页时返回 True，否则返回 False。
    """
    return any(outcome.status == PAGE_FAILED for outcome in outcomes)
