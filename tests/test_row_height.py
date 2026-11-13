"""Tests for the density-scaled default list row height."""

import datetime as dt
from unittest.mock import patch

import pytest

from custom_components.eink_dashboard.const import (
    DEFAULT_ROW_H,
    DEVICE_PRESETS,
    default_list_row_height,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets._helpers import (
    _max_row_height,
)
from tests.test_render_entities import MOCK_ENTITIES_STATES
from tests.test_render_waste_schedule import (
    _PATCH_NOW,
    _TODAY,
    MOCK_WASTE_SCHEDULE_STATES,
)


class TestDefaultListRowHeight:
    """Unit tests for default_list_row_height()."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("kindle_pw", DEFAULT_ROW_H),
            ("kindle_4", 44),
            ("kindle_pw4", 79),
            ("trmnl_og", 33),
            ("trmnl_x", 60),
            ("reterminal_e1002", 34),
        ],
    )
    def test_scales_with_preset_ppi(self, model: str, expected: int) -> None:
        # Rows keep the physical height of 56 px at 212 ppi.
        assert default_list_row_height({"device_model": model}) == expected

    @pytest.mark.parametrize(
        "options",
        [{}, {"device_model": "custom"}, {"device_model": "trmnl_rgb"}],
    )
    def test_unknown_density_keeps_default(
        self, options: dict[str, str]
    ) -> None:
        # Custom displays and presets without a ppi fall back to 56 px.
        assert default_list_row_height(options) == DEFAULT_ROW_H

    def test_custom_uses_entered_ppi(self) -> None:
        # Custom displays scale by the user-entered pixel density.
        opts = {"device_model": "custom", "ppi": 124}
        assert default_list_row_height(opts) == 33

    def test_preset_ignores_stale_ppi(self) -> None:
        # A leftover ppi option never overrides a preset's density.
        opts = {"device_model": "kindle_pw", "ppi": 124}
        assert default_list_row_height(opts) == DEFAULT_ROW_H

    def test_unknown_model_keeps_default(self) -> None:
        # A stale or removed device_model must not raise.
        opts = {"device_model": "no_such_device"}
        assert default_list_row_height(opts) == DEFAULT_ROW_H

    def test_reference_preset_has_reference_ppi(self) -> None:
        # The 56 px baseline was designed on the Kindle Paperwhite.
        assert DEVICE_PRESETS["kindle_pw"].ppi == 212


class TestMaxRowHeight:
    """Unit tests for _max_row_height() precedence."""

    def test_widget_value_wins(self) -> None:
        # An explicit widget row_height overrides the display default.
        assert _max_row_height({"row_height": 70}, {"row_height": 33}) == 70

    def test_display_default_used(self) -> None:
        # Without a widget value, the display's scaled default applies.
        assert _max_row_height({}, {"row_height": 33}) == 33

    def test_falls_back_to_default_row_h(self) -> None:
        # Configs without row_height (e.g. older callers) keep 56 px.
        assert _max_row_height({}, {}) == DEFAULT_ROW_H


class TestListWidgetsUseDisplayDefault:
    """List widgets size rows from the display's default row height."""

    @pytest.mark.parametrize(
        "widget",
        [
            {
                "type": "entities",
                "entities": ["sensor.temperature", "sensor.humidity"],
            },
            {
                "type": "waste_schedule",
                "entity": "sensor.waste_collection",
                "entries": [
                    {"attribute": "Restmuell", "label": "Restmuell"},
                    {"attribute": "Biotonne", "label": "Bio"},
                ],
            },
        ],
    )
    def test_auto_height_uses_display_row_height(
        self, widget: dict[str, object]
    ) -> None:
        # Without h or row_height, two rows at the display's 33 px.
        w = {"x": 0, "y": 0, "w": 400, **widget}
        config = {
            "width": 800,
            "height": 480,
            "row_height": 33,
            "states": {
                **MOCK_ENTITIES_STATES,
                **MOCK_WASTE_SCHEDULE_STATES,
            },
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, config)
        assert 'height="66"' in svg
