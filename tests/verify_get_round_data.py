"""
Verificación local de scripts/get_round_data.py.

No usa credenciales reales ni red: inyecta un cliente falso y escribe los JSON
en un directorio temporal (directorio de datos aislado por caso).

Ejecutar con:
    python -I tests/verify_get_round_data.py
"""

import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# El script vive en ../scripts respecto a este archivo.
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

import get_round_data as grd  # noqa: E402


class FakeAPI:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def request(self, method, url):
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.api = FakeAPI(response=response, error=error)


def make_item(**overrides):
    item = {
        "PositionName": "DRIVER",
        "IsActive": "1",
        "DriverTLA": "VER",
        "DisplayName": "M. Verstappen",
        "TeamName": "Red Bull Racing",
        "GamedayPoints": "25",
        "SelectedPercentage": "18",
        "Value": "28.5",
        "QualifyingPoints": "7",
        "SprintPoints": "0",
        "RacePoints": "18",
    }
    item.update(overrides)
    return item


def feed(*items):
    return {"Data": {"Value": list(items)}}


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def assert_summary_matches_json(test, out, payload, data_dir, race_id, season=2025):
    """El texto de consola debe reflejar exactamente lo escrito en el JSON."""
    test.assertIn(
        f"实际写入: Drivers {len(payload['Drivers'])} 条"
        f" | Teams {len(payload['Teams'])} 条",
        out,
    )
    path = os.path.join(data_dir, str(season), f"round_{race_id:02d}.json")
    test.assertIn(f"生成文件: {path}", out)

    for d in payload["Drivers"]:
        test.assertIn(
            f"    {d['Driver_Code']}: 本场 {d['Round_Fantasy_Points']:.1f}"
            f" → 累计 {d['Season_Fantasy_Points']:.1f}",
            out,
        )
    for t in payload["Teams"]:
        test.assertIn(
            f"    {t['Team_Code']}: 本场 {t['Round_Fantasy_Points']:.1f}"
            f" → 累计 {t['Season_Fantasy_Points']:.1f}",
            out,
        )


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Directorio de datos propio por caso; nunca toca data/ del repo.
        self.data_dir = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data_dir, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_round(self, client, race_id, season=2025, cumulative=None):
        cumulative_drivers = {} if cumulative is None else cumulative[0]
        cumulative_teams = {} if cumulative is None else cumulative[1]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = asyncio.run(
                grd.process_single_round(
                    client,
                    race_id,
                    season,
                    cumulative_drivers,
                    cumulative_teams,
                    data_dir=self.data_dir,
                )
            )
        return ok, out.getvalue(), cumulative_drivers, cumulative_teams

    def round_path(self, race_id, season=2025):
        return os.path.join(self.data_dir, str(season), f"round_{race_id:02d}.json")


class NormalRoundTest(BaseCase):
    def test_single_round_writes_and_summary_matches_json(self):
        items = [
            make_item(DriverTLA="VER", DisplayName="M. Verstappen", GamedayPoints="25"),
            make_item(
                DriverTLA="NOR",
                DisplayName="L. Norris",
                TeamName="McLaren",
                GamedayPoints="41",
                SelectedPercentage="26",
                Value="29.3",
            ),
            make_item(
                PositionName="CONSTRUCTOR",
                DriverTLA="RBR",
                DisplayName="Red Bull Racing",
                GamedayPoints="30",
                SelectedPercentage="8",
                Value="33.6",
            ),
            make_item(
                PositionName="CONSTRUCTOR",
                DriverTLA="RBS",
                DisplayName="Racing Bulls",
                GamedayPoints="12",
                SelectedPercentage="5",
                Value="18.3",
            ),
        ]
        ok, out, cum_d, cum_t = self.run_round(FakeClient(feed(*items)), race_id=1)

        self.assertTrue(ok)
        payload = read_json(self.round_path(1))
        self.assertEqual(payload["Meta"]["season"], 2025)
        self.assertEqual(payload["Meta"]["race_id"], 1)

        # El resumen debe coincidir exactamente con lo escrito en el JSON.
        assert_summary_matches_json(self, out, payload, self.data_dir, 1)
        self.assertEqual(len(payload["Drivers"]), 2)
        self.assertEqual(len(payload["Teams"]), 2)

        team_codes = {t["Team_Code"] for t in payload["Teams"]}
        self.assertEqual(team_codes, {"RED", "VRB"})
        self.assertIn("RBR→RED", out)
        self.assertIn("RBS→VRB", out)
        self.assertIn("归一化后 Team_Code=VRB", out)

        # race_id=1: la consola declara explícitamente el punto de partida.
        self.assertIn("首个分站（race_id=1），累计从零开始", out)
        self.assertIn("累计值: 已更新", out)

        ver = next(d for d in payload["Drivers"] if d["Driver_Code"] == "VER")
        self.assertEqual(ver["Season_Fantasy_Points"], 25.0)
        self.assertEqual(cum_d["VER"], 25.0)

        red = next(t for t in payload["Teams"] if t["Team_Code"] == "RED")
        self.assertEqual(red["Season_Fantasy_Points"], 30.0)
        self.assertEqual(cum_t["RED"], 30.0)

        # Ningún porcentaje supera 1.0 ni tiene más de 4 decimales.
        for row in payload["Drivers"] + payload["Teams"]:
            self.assertLessEqual(row["Selected_Percentage"], 1.0)
            self.assertEqual(
                round(row["Selected_Percentage"], 4), row["Selected_Percentage"]
            )

    def test_inactive_entries_are_excluded(self):
        items = [
            make_item(DriverTLA="VER"),
            make_item(DriverTLA="STR", IsActive="0"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=1)
        self.assertTrue(ok)
        payload = read_json(self.round_path(1))
        self.assertEqual(
            [d["Driver_Code"] for d in payload["Drivers"]], ["VER"]
        )
        self.assertIn("实际写入: Drivers 1 条 | Teams 1 条", out)


class DuplicateDriverMergeTest(BaseCase):
    def test_two_records_merged_with_score_basis_and_clamped_percentage(self):
        items = [
            # Ficha con actividad en pista pero Value menor -> debe ser la elegida.
            make_item(
                DriverTLA="VER",
                DisplayName="M. Verstappen",
                GamedayPoints="25",
                SelectedPercentage="60",
                Value="20.0",
            ),
            # Ficha sin puntuación pero Value mayor -> se descarta.
            make_item(
                DriverTLA="VER",
                DisplayName="M. Verstappen (dup)",
                GamedayPoints="0",
                QualifyingPoints="0",
                SprintPoints="0",
                RacePoints="0",
                SelectedPercentage="70",
                Value="99.9",
            ),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, cum_d, _ = self.run_round(FakeClient(feed(*items)), race_id=1)

        self.assertTrue(ok)
        payload = read_json(self.round_path(1))
        self.assertEqual(len(payload["Drivers"]), 1)
        merged = payload["Drivers"][0]

        # La ficha elegida es la que puntuó (Value 20.0), no la de Value 99.9.
        self.assertEqual(merged["Value"], 20.0)
        self.assertEqual(merged["Round_Fantasy_Points"], 25.0)
        # 0.60 + 0.70 = 1.30 -> se recorta a 1.0 con 4 decimales.
        self.assertEqual(merged["Selected_Percentage"], 1.0)
        self.assertEqual(cum_d["VER"], 25.0)

        assert_summary_matches_json(self, out, payload, self.data_dir, 1)

        # La consola debe explicar el criterio y el cálculo del porcentaje.
        self.assertIn("重复车手编码合并: 1 组", out)
        self.assertIn("VER", out)
        self.assertIn("本场有得分=True", out)
        self.assertIn("依据: 本场有得分优先", out)
        self.assertIn("0.6000 + 0.7000 = 1.0000", out)
        self.assertIn("原始合计 1.3000 超过上限，已截断为 1.0000", out)
        self.assertIn("舍弃记录", out)
        self.assertIn('"M. Verstappen (dup)"', out)

    def test_merge_below_one_keeps_sum(self):
        items = [
            make_item(DriverTLA="VER", GamedayPoints="25", SelectedPercentage="12"),
            make_item(DriverTLA="VER", GamedayPoints="0", SelectedPercentage="9"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=1)
        self.assertTrue(ok)
        merged = read_json(self.round_path(1))["Drivers"][0]
        self.assertEqual(merged["Selected_Percentage"], 0.21)
        self.assertIn("0.1200 + 0.0900 = 0.2100", out)

    def test_merge_driver_records_direct(self):
        records = [
            {
                "Driver_Code": "AAA",
                "Selected_Percentage": 0.8,
                "Value": 5.0,
                "Round_Fantasy_Points": 0.0,
                "Qualifying_Points": 0.0,
                "Sprint_Points": 0.0,
                "Race_Points": 0.0,
            },
            {
                "Driver_Code": "AAA",
                "Selected_Percentage": 0.8,
                "Value": 1.0,
                "Round_Fantasy_Points": -4.0,
                "Qualifying_Points": 0.0,
                "Sprint_Points": 0.0,
                "Race_Points": -4.0,
            },
        ]
        merged = grd.merge_driver_records(records)
        # Puntos negativos siguen siendo actividad real en pista.
        self.assertEqual(merged["Value"], 1.0)
        self.assertEqual(merged["Selected_Percentage"], 1.0)


class MissingPreviousRoundTest(BaseCase):
    def test_missing_previous_round_is_reported_and_starts_from_zero(self):
        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR", GamedayPoints="30"),
        ]
        ok, out, cum_d, cum_t = self.run_round(FakeClient(feed(*items)), race_id=2)

        self.assertTrue(ok)
        missing_path = self.round_path(1)
        self.assertFalse(os.path.exists(missing_path))

        payload = read_json(self.round_path(2))
        assert_summary_matches_json(self, out, payload, self.data_dir, 2)
        self.assertIn(
            f"上一站文件 {missing_path} 不存在，累计从零开始",
            out,
        )
        self.assertIn("累计起点:", out)
        self.assertIn("累计值: 已更新", out)

        ver = next(d for d in payload["Drivers"] if d["Driver_Code"] == "VER")
        self.assertEqual(ver["Season_Fantasy_Points"], 25.0)
        self.assertEqual(cum_d["VER"], 25.0)
        self.assertEqual(cum_t["RED"], 30.0)

    def test_previous_round_read_continues_cumulative(self):
        prev_items = [
            make_item(DriverTLA="VER", GamedayPoints="11"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBS", GamedayPoints="7"),
        ]
        self.assertTrue(self.run_round(FakeClient(feed(*prev_items)), race_id=1)[0])

        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBS", GamedayPoints="5"),
        ]
        ok, out, cum_d, cum_t = self.run_round(FakeClient(feed(*items)), race_id=2)
        self.assertTrue(ok)

        prev_path = self.round_path(1)
        self.assertIn(f"读取上一站文件 {prev_path}", out)

        payload = read_json(self.round_path(2))
        assert_summary_matches_json(self, out, payload, self.data_dir, 2)
        ver = next(d for d in payload["Drivers"] if d["Driver_Code"] == "VER")
        self.assertEqual(ver["Season_Fantasy_Points"], 36.0)
        vrb = next(t for t in payload["Teams"] if t["Team_Code"] == "VRB")
        self.assertEqual(vrb["Season_Fantasy_Points"], 12.0)
        self.assertEqual(cum_d["VER"], 36.0)
        self.assertEqual(cum_t["VRB"], 12.0)

    def test_corrupt_previous_round_is_reported_as_read_error(self):
        prev_path = self.round_path(1)
        os.makedirs(os.path.dirname(prev_path), exist_ok=True)
        with open(prev_path, "w", encoding="utf-8") as f:
            f.write("{ esto no es json valido ")

        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=2)
        self.assertTrue(ok)
        self.assertIn("读取失败", out)
        self.assertIn("累计从零开始", out)
        self.assertIn("JSONDecodeError", out)

    def test_previous_round_with_bad_structure_is_reported(self):
        prev_path = self.round_path(1)
        os.makedirs(os.path.dirname(prev_path), exist_ok=True)
        with open(prev_path, "w", encoding="utf-8") as f:
            json.dump({"Meta": {}, "Drivers": "nope", "Teams": []}, f)

        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=2)
        self.assertTrue(ok)
        self.assertIn("结构不符", out)
        self.assertIn("累计从零开始", out)


class TeamNormalizationTest(BaseCase):
    def test_rbs_and_vrb_collapse_into_one_normalized_team(self):
        items = [
            make_item(DriverTLA="VER"),
            make_item(
                PositionName="CONSTRUCTOR",
                DriverTLA="RBS",
                DisplayName="Racing Bulls",
                GamedayPoints="12",
                SelectedPercentage="30",
            ),
            make_item(
                PositionName="CONSTRUCTOR",
                DriverTLA="VRB",
                DisplayName="RB",
                GamedayPoints="8",
                SelectedPercentage="20",
            ),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=1)
        self.assertTrue(ok)
        payload = read_json(self.round_path(1))
        assert_summary_matches_json(self, out, payload, self.data_dir, 1)

        self.assertEqual(len(payload["Teams"]), 1)
        team = payload["Teams"][0]
        self.assertEqual(team["Team_Code"], "VRB")
        # Se conserva la ficha con puntos (ambas puntúan) de mayor Value.
        self.assertEqual(team["Round_Fantasy_Points"], 12.0)
        self.assertEqual(team["Selected_Percentage"], 0.5)

        self.assertIn("RBS→VRB", out)
        self.assertIn("归一化后 Team_Code=VRB", out)
        self.assertIn("重复车队编码合并（归一化后同码）: 1 组", out)
        self.assertIn("0.3000 + 0.2000 = 0.5000", out)
        self.assertIn("累计明细（与 JSON 的 Season_Fantasy_Points 一致）", out)

    def test_percentage_keeps_four_decimals(self):
        items = [
            make_item(DriverTLA="VER", SelectedPercentage="33.3333"),
            make_item(
                DriverTLA="VER",
                DisplayName="Verstappen dup",
                SelectedPercentage="16.6667",
                Value="10.0",
            ),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, out, _, _ = self.run_round(FakeClient(feed(*items)), race_id=1)
        self.assertTrue(ok)
        merged = read_json(self.round_path(1))["Drivers"][0]
        # 0.3333 + 0.1667 = 0.5 exacto, redondeado a 4 decimales.
        self.assertEqual(merged["Selected_Percentage"], 0.5)
        self.assertIn("Selected_Percentage: 0.3333 + 0.1667 = 0.5000", out)


class EmptyResponseTest(BaseCase):
    def assert_failure(self, out, reason_fragment):
        self.assertIn("生成文件: 无", out)
        self.assertIn("实际写入: Drivers 0 条 | Teams 0 条", out)
        self.assertIn("累计值: 未被改动", out)
        self.assertIn(reason_fragment, out)

    def test_empty_list_reports_empty_and_leaves_cumulative_untouched(self):
        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        ok, _, cum_d, cum_t = self.run_round(FakeClient(feed(*items)), race_id=1)
        self.assertTrue(ok)
        snapshot_d = dict(cum_d)
        snapshot_t = dict(cum_t)

        ok2, out, cum_d2, cum_t2 = self.run_round(
            FakeClient(feed()), race_id=2, cumulative=(cum_d, cum_t)
        )
        self.assertFalse(ok2)
        self.assertFalse(os.path.exists(self.round_path(2)))
        self.assertIn("返回为空（Data.Value 为空列表）", out)
        self.assertIn("失败原因: 返回为空（Data.Value 为空列表）", out)
        self.assertIn("累计值: 未被改动", out)
        self.assertEqual(cum_d, snapshot_d)
        self.assertEqual(cum_t, snapshot_t)
        self.assertEqual(cum_d2, snapshot_d)
        self.assertEqual(cum_t2, snapshot_t)

    def test_null_value_is_distinguished_from_empty_list(self):
        ok, out, _, _ = self.run_round(
            FakeClient({"Data": {"Value": None}}), race_id=1
        )
        self.assertFalse(ok)
        self.assertIn("返回为空（Data.Value 为 null）", out)
        self.assert_failure(out, "返回为空")

    def test_network_error_reported(self):
        ok, out, _, _ = self.run_round(
            FakeClient(error=ConnectionError("boom")), race_id=1
        )
        self.assertFalse(ok)
        self.assertIn("失败原因: 网络异常（ConnectionError: boom）", out)
        self.assert_failure(out, "网络异常")

    def test_wrong_structure_reported(self):
        ok, out, _, _ = self.run_round(FakeClient(["no", "es", "dict"]), race_id=1)
        self.assertFalse(ok)
        self.assertIn("结构不符", out)
        self.assertIn("list", out)
        self.assert_failure(out, "结构不符")

    def test_write_failure_keeps_previous_file_intact(self):
        items = [
            make_item(DriverTLA="VER", GamedayPoints="25"),
            make_item(PositionName="CONSTRUCTOR", DriverTLA="RBR"),
        ]
        self.assertTrue(self.run_round(FakeClient(feed(*items)), race_id=1)[0])
        before = read_json(self.round_path(1))

        import get_round_data as grd_mod

        real_replace = grd_mod.os.replace

        def boom(src, dst):
            raise OSError("disco lleno")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with mock.patch.object(grd_mod.os, "replace", side_effect=boom):
                ok = asyncio.run(
                    grd_mod.process_single_round(
                        FakeClient(feed(*items)),
                        1,
                        2025,
                        {},
                        {},
                        data_dir=self.data_dir,
                    )
                )
        self.assertFalse(ok)
        self.assertEqual(read_json(self.round_path(1)), before)
        self.assertFalse(os.path.exists(self.round_path(1) + ".tmp"))
        self.assertIn("写入失败（OSError: disco lleno）", out.getvalue())
        self.assertIn("累计值: 未被改动", out.getvalue())

    def test_no_active_entries_is_structural_failure(self):
        ok, out, _, _ = self.run_round(
            FakeClient(feed(make_item(IsActive="0"))), race_id=1
        )
        self.assertFalse(ok)
        self.assertIn("未找到有效参赛记录", out)
        self.assert_failure(out, "结构不符")


if __name__ == "__main__":
    unittest.main(verbosity=2)
