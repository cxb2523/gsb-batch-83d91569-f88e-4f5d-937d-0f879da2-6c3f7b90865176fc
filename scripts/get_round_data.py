import asyncio
import json
import os
import sys
from datetime import datetime


def _configure_console():
    """Fuerza UTF-8 en la consola para que los emojis/chino no rompan la salida."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _emit(text=""):
    """print tolerante a consolas con codificación limitada (p. ej. GBK)."""
    stream = sys.stdout
    text = str(text)
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")


_configure_console()

try:
    # Se importa de forma diferida para poder ejecutar los procesadores en local
    # (por ejemplo, con datos de muestra) sin instalar el cliente oficial.
    from fantasy import APIClient, Client
except ImportError:  # pragma: no cover - depende del entorno de ejecución
    APIClient = None
    Client = None

# Mapeo de normalización de códigos de equipo
TEAM_CODE_OVERRIDES = {
    "RBS": "VRB",
    "RBR": "RED",
}

SUMMARY_SEPARATOR = "=" * 72


def _resolve_data_dir(data_dir=None):
    """Permite usar un directorio de datos alternativo (útil para pruebas locales)."""
    return data_dir or os.getenv("F1_FANTASY_DATA_DIR") or "data"


def safe_float(value, default=0.0):
    """Convierte un valor a float de forma segura si está vacío o es nulo."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_percentage(value, default=0.0):
    """
    Convierte un valor de porcentaje (0 a 100) a float relativo (0.0 a 1.0).
    Ejemplo: '36' -> 0.36, '1' -> 0.01, '0.5' -> 0.005.
    """
    if value is None or value == "":
        return default
    try:
        clean_val = str(value).replace("%", "").strip()
        val = float(clean_val)
        return round(val / 100.0, 4)
    except (ValueError, TypeError):
        return default


def is_active(item):
    """Comprueba si la entidad está activa en el gran premio actual."""
    return str(item.get("IsActive", "")).strip() == "1"


def _is_number(value):
    if value is None or value == "":
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _fmt_num(value):
    """Formatea un valor numérico de forma estable para la consola."""
    return f"{safe_float(value):.1f}"


def _has_round_score(record):
    """
    Indica si la ficha obtuvo puntuación en la ronda actual.
    Se considera cualquier componente de puntos distinto de cero (incluidos
    los negativos, que también son actividad real en pista).
    """
    for field in (
        "Round_Fantasy_Points",
        "Qualifying_Points",
        "Sprint_Points",
        "Race_Points",
    ):
        if abs(safe_float(record.get(field))) > 0:
            return True
    return False


def _selection_key(record):
    """
    Orden de preferencia para elegir la ficha que se conserva al fusionar
    registros duplicados: primero actividad/puntuación en la ronda y después
    el Value más alto.
    """
    return (_has_round_score(record), safe_float(record.get("Value")))


def _record_description(record, name_key):
    """Describe una ficha de forma compacta para poder auditarla en consola."""
    return (
        f'"{record.get(name_key, "N/A")}"'
        f'（GamedayPoints={_fmt_num(record.get("Round_Fantasy_Points"))}, '
        f'Q/S/R={_fmt_num(record.get("Qualifying_Points"))}/'
        f'{_fmt_num(record.get("Sprint_Points"))}/'
        f'{_fmt_num(record.get("Race_Points"))}, '
        f'Value={_fmt_num(record.get("Value"))}）'
    )


def _describe_merge(group_code, records, name_key, label):
    """
    Genera las líneas de auditoría de un grupo de registros duplicados.
    El registro elegido se identifica con el mismo criterio que
    merge_driver_records: primero "hay puntuación en la ronda", luego Value.
    """
    chosen_index = max(range(len(records)), key=lambda i: _selection_key(records[i]))
    chosen = records[chosen_index]
    others = [r for i, r in enumerate(records) if i != chosen_index]

    scored_others = [r for r in others if _has_round_score(r)]
    unscored_others = [r for r in others if not _has_round_score(r)]
    values = ", ".join(f"{safe_float(r.get('Value')):.1f}" for r in records)

    if not _has_round_score(chosen) and not scored_others:
        basis = (
            "依据: 全部记录本场均无得分，按 Value 取较大值"
            f"（{values}）"
        )
    elif unscored_others and not scored_others:
        basis = "依据: 本场有得分优先（其余记录本场均无得分）"
    else:
        basis = (
            "依据: 本场有得分优先（其余记录同样有得分），"
            f"再按 Value 取较大值（{values}）"
        )

    raw_sum = sum(safe_float(r.get("Selected_Percentage")) for r in records)
    merged_pct = round(min(max(raw_sum, 0.0), 1.0), 4)
    percentages = " + ".join(
        f"{safe_float(r.get('Selected_Percentage')):.4f}" for r in records
    )

    if raw_sum > 1.0:
        clamp_note = f"原始合计 {raw_sum:.4f} 超过上限，已截断为 1.0000"
    elif raw_sum < 0.0:
        clamp_note = f"原始合计 {raw_sum:.4f} 小于下限，已截断为 0.0000"
    else:
        clamp_note = f"原始合计 {raw_sum:.4f} 未超过 1.0"

    lines = [f"  - {group_code}（{label}，{len(records)} 条记录）"]
    lines.append(
        f"      采用记录: {_record_description(chosen, name_key)}"
        f"；本场有得分={_has_round_score(chosen)}（{basis}）"
    )
    if others:
        lines.append(
            "      舍弃记录: "
            + "；".join(_record_description(r, name_key) for r in others)
        )
    lines.append(
        f"      Selected_Percentage: {percentages} = {merged_pct:.4f}"
        f"（{clamp_note}，保留四位小数）"
    )
    return lines


def _load_previous_round(season, previous_race_id, data_dir=None):
    """
    Lee el JSON de la ronda previa con estado detallado. El estado permite
    distinguir entre archivo ausente, error de lectura y estructura inválida,
    de forma que la consola nunca continúe en silencio desde cero.
    """
    filename = os.path.join(
        _resolve_data_dir(data_dir), str(season), f"round_{previous_race_id:02d}.json"
    )
    status = {
        "ok": False,
        "filename": filename,
        "kind": None,
        "message": "",
        "driver_entries": 0,
        "team_entries": 0,
    }

    if not os.path.exists(filename):
        status["kind"] = "missing"
        status["message"] = "文件不存在"
        return {}, {}, status

    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        status["kind"] = "read_error"
        status["message"] = f"{type(e).__name__}: {e}"
        return {}, {}, status

    if not isinstance(data, dict):
        status["kind"] = "invalid_structure"
        status["message"] = f"顶层类型为 {type(data).__name__}，期望 dict"
        return {}, {}, status

    drivers = data.get("Drivers")
    teams = data.get("Teams")
    if not isinstance(drivers, list) or not isinstance(teams, list):
        status["kind"] = "invalid_structure"
        status["message"] = "缺少 Drivers/Teams 列表"
        return {}, {}, status

    d_totals = {}
    t_totals = {}

    for entry in drivers:
        if not isinstance(entry, dict):
            status["kind"] = "invalid_structure"
            status["message"] = "Drivers 中存在非对象条目"
            return {}, {}, status
        code = entry.get("Driver_Code")
        points = entry.get("Season_Fantasy_Points")
        if not isinstance(code, str) or not code or not _is_number(points):
            status["kind"] = "invalid_structure"
            status["message"] = "Drivers 条目缺少 Driver_Code/Season_Fantasy_Points"
            return {}, {}, status
        d_totals[code] = safe_float(points)

    for entry in teams:
        if not isinstance(entry, dict):
            status["kind"] = "invalid_structure"
            status["message"] = "Teams 中存在非对象条目"
            return {}, {}, status
        code = entry.get("Team_Code")
        points = entry.get("Season_Fantasy_Points")
        if not isinstance(code, str) or not code or not _is_number(points):
            status["kind"] = "invalid_structure"
            status["message"] = "Teams 条目缺少 Team_Code/Season_Fantasy_Points"
            return {}, {}, status
        t_totals[code] = safe_float(points)

    status["ok"] = True
    status["driver_entries"] = len(drivers)
    status["team_entries"] = len(teams)
    return d_totals, t_totals, status


def load_previous_round_totals(season, previous_race_id, data_dir=None, with_status=False):
    """
    Si se procesa una ronda individual, lee el JSON de la ronda previa
    para mantener la continuidad de los puntos acumulados.

    Devuelve ({}, {}) cuando el archivo no existe o no se puede leer; con
    with_status=True devuelve además el estado detallado de la lectura.
    """
    d_totals, t_totals, status = _load_previous_round(
        season, previous_race_id, data_dir=data_dir
    )
    if with_status:
        return d_totals, t_totals, status
    return d_totals, t_totals


def merge_driver_records(records):
    """
    Si existiese más de un registro activo para el mismo piloto,
    prioriza la ficha con actividad en pista y consolida la selección.
    El Selected_Percentage resultante nunca supera 1.0 y se redondea a 4 decimales.
    """
    if not records:
        raise ValueError("merge_driver_records requiere al menos un registro")

    if len(records) == 1:
        merged = dict(records[0])
        merged["Selected_Percentage"] = round(
            min(max(safe_float(merged.get("Selected_Percentage")), 0.0), 1.0), 4
        )
        return merged

    active_record = max(records, key=_selection_key)

    total_selected = sum(safe_float(r.get("Selected_Percentage")) for r in records)

    merged = dict(active_record)
    merged["Selected_Percentage"] = round(
        min(max(total_selected, 0.0), 1.0), 4
    )

    return merged


def save_round_json(
    processed_drivers, processed_teams, race_id=1, season=None, data_dir=None
):
    """Guarda la información de la ronda en un archivo JSON independiente."""
    if season is None:
        season = datetime.now().year

    payload = {
        "Meta": {
            "season": season,
            "race_id": race_id,
            "generated_at": datetime.now().isoformat(),
        },
        "Drivers": processed_drivers,
        "Teams": processed_teams,
    }

    output_dir = os.path.join(_resolve_data_dir(data_dir), str(season))
    os.makedirs(output_dir, exist_ok=True)

    filename = os.path.join(output_dir, f"round_{race_id:02d}.json")

    # Escritura atómica: si el volcado falla, no se destruye el JSON existente.
    tmp_filename = filename + ".tmp"
    try:
        with open(tmp_filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        os.replace(tmp_filename, filename)
    except Exception:
        try:
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)
        except OSError:
            pass
        raise

    _emit(f"📁 Guardado local: {filename}")
    return filename


def _print_failure_summary(season, race_id, reason, cumulative_drivers, cumulative_teams):
    """Resumen inequívoco de una ronda sin datos válidos."""
    _emit(f"\n{SUMMARY_SEPARATOR}")
    _emit(f"📋 第 {race_id:02d} 站处理汇总（赛季 {season}）")
    _emit(SUMMARY_SEPARATOR)
    _emit("生成文件: 无（本站未写入 JSON）")
    _emit(f"失败原因: {reason}")
    _emit("说明: JSON 文件未生成或未覆盖，累计值保持上一站状态，本站不参与累计。")
    _emit("实际写入: Drivers 0 条 | Teams 0 条")
    _emit(
        "累计值: 未被改动"
        f"（Drivers {len(cumulative_drivers)} 键, Teams {len(cumulative_teams)} 键）"
    )
    _emit(SUMMARY_SEPARATOR + "\n")


def _print_success_summary(
    season,
    race_id,
    filename,
    processed_drivers,
    processed_teams,
    driver_merges,
    team_merges,
    normalizations,
    cumulative_desc,
    cumulative_drivers,
    cumulative_teams,
    raw_driver_count,
    raw_team_count,
):
    """Resumen auditable de una ronda escrita correctamente."""
    _emit(f"\n{SUMMARY_SEPARATOR}")
    _emit(f"📋 第 {race_id:02d} 站处理汇总（赛季 {season}）")
    _emit(SUMMARY_SEPARATOR)
    _emit(f"生成文件: {filename}")
    _emit(
        f"实际写入: Drivers {len(processed_drivers)} 条"
        f" | Teams {len(processed_teams)} 条"
    )
    _emit(
        f"原始有效记录: 车手 {raw_driver_count} 条、车队 {raw_team_count} 条"
        f"（过滤未激活/非本类条目后；重复编码去重后写入了上述条数）"
    )

    if driver_merges:
        _emit(f"重复车手编码合并: {len(driver_merges)} 组")
        for code, records in sorted(driver_merges.items()):
            for line in _describe_merge(code, records, "Driver_Name", "车手"):
                _emit(line)
    else:
        _emit("重复车手编码合并: 无")

    if normalizations:
        mapping = ", ".join(f"{raw}→{norm}" for raw, norm, _ in normalizations)
        _emit(f"车队编码归一化: {mapping}")
        for raw, norm, name in normalizations:
            _emit(
                f'  - {raw}→{norm}: 归一化后 Team_Code={norm}（原始车队 "{name}"）'
            )
    else:
        _emit("车队编码归一化: 无（本站未出现 RBS/RBR 编码）")

    if team_merges:
        _emit(f"重复车队编码合并（归一化后同码）: {len(team_merges)} 组")
        for code, records in sorted(team_merges.items()):
            for line in _describe_merge(code, records, "Team_Name", "车队"):
                _emit(line)

    _emit(f"累计起点: {cumulative_desc}")
    _emit(
        "累计值: 已更新"
        f"（Drivers {len(cumulative_drivers)} 键, Teams {len(cumulative_teams)} 键）"
    )

    # 明细逐行对齐 JSON：编码、本场得分、写入文件中的累计值。
    _emit("累计明细（与 JSON 的 Season_Fantasy_Points 一致）:")
    _emit("  Drivers:")
    for d in processed_drivers:
        _emit(
            f"    {d['Driver_Code']}: 本场 {_fmt_num(d['Round_Fantasy_Points'])}"
            f" → 累计 {_fmt_num(d['Season_Fantasy_Points'])}"
        )
    _emit("  Teams（使用归一化后的编码）:")
    for t in processed_teams:
        _emit(
            f"    {t['Team_Code']}: 本场 {_fmt_num(t['Round_Fantasy_Points'])}"
            f" → 累计 {_fmt_num(t['Season_Fantasy_Points'])}"
        )
    _emit(SUMMARY_SEPARATOR + "\n")


def _resolve_cumulative_start(
    season, race_id, cumulative_drivers, cumulative_teams, data_dir=None
):
    """
    Garantiza un punto de partida explícito para los acumulados y devuelve
    (base_drivers, base_teams, descripción). Nunca continúa en silencio desde
    cero cuando falta el archivo de la ronda anterior.
    """
    base_drivers = dict(cumulative_drivers)
    base_teams = dict(cumulative_teams)

    if race_id <= 1:
        if base_drivers or base_teams:
            return (
                base_drivers,
                base_teams,
                "首个分站（race_id=1），沿用内存中提供的累计值"
                f"（Drivers {len(base_drivers)} 键, Teams {len(base_teams)} 键）",
            )
        return base_drivers, base_teams, "首个分站（race_id=1），累计从零开始"

    if base_drivers and base_teams:
        return (
            base_drivers,
            base_teams,
            f"内存中已有累计值（Drivers {len(base_drivers)} 键, Teams {len(base_teams)} 键），无需读取上一站文件",
        )

    # Estado parcial: se completa solo la parte que falta, sin sobrescribir la
    # parte que ya estaba en memoria.
    prev_d, prev_t, status = load_previous_round_totals(
        season, race_id - 1, data_dir=data_dir, with_status=True
    )

    if status["ok"]:
        had_drivers = bool(base_drivers)
        had_teams = bool(base_teams)
        if not base_drivers:
            base_drivers.update(prev_d)
        if not base_teams:
            base_teams.update(prev_t)

        desc = (
            f"读取上一站文件 {status['filename']}"
            f"（Drivers {status['driver_entries']} 条, Teams {status['team_entries']} 条）"
        )
        if had_drivers and not had_teams:
            desc += "；只补齐 Teams，Drivers 沿用内存值"
        elif had_teams and not had_drivers:
            desc += "；只补齐 Drivers，Teams 沿用内存值"
        if not cumulative_drivers and not prev_d:
            desc += "；文件存在但 Drivers 为空，Drivers 累计从零开始"
        if not cumulative_teams and not prev_t:
            desc += "；文件存在但 Teams 为空，Teams 累计从零开始"
        return base_drivers, base_teams, desc

    if status["kind"] == "missing":
        desc = f"上一站文件 {status['filename']} 不存在，累计从零开始"
    elif status["kind"] == "read_error":
        desc = (
            f"上一站文件 {status['filename']} 读取失败"
            f"（{status['message']}），累计从零开始"
        )
    else:
        desc = (
            f"上一站文件 {status['filename']} 结构不符"
            f"（{status['message']}），累计从零开始"
        )

    if cumulative_drivers:
        desc += f"；Drivers 沿用内存中 {len(cumulative_drivers)} 键"
    if cumulative_teams:
        desc += f"；Teams 沿用内存中 {len(cumulative_teams)} 键"
    return base_drivers, base_teams, desc


async def process_single_round(
    client,
    race_id,
    season,
    cumulative_drivers,
    cumulative_teams,
    data_dir=None,
):
    """Descarga, procesa y guarda los datos activos de una ronda."""
    url = f"/feeds/drivers/{race_id}_en.json"

    try:
        data = await client.api.request("GET", url)
    except Exception as e:
        reason = f"网络异常（{type(e).__name__}: {e}）"
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    # Clasificación explícita del fallo: nunca se confunde "respuesta vacía"
    # con "estructura inesperada" ni se continúa sin dejar constancia.
    if data is None or (isinstance(data, str) and not data.strip()):
        reason = "返回为空（响应为空/None）"
        _emit(f"ℹ️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    if not isinstance(data, dict):
        reason = f"结构不符（响应类型为 {type(data).__name__}，期望 dict）"
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    data_field = data.get("Data")
    if not isinstance(data_field, dict):
        reason = "结构不符（缺少 dict 类型的 Data 字段）"
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    items = data_field.get("Value")
    if items is None:
        reason = "返回为空（Data.Value 为 null）"
        _emit(f"ℹ️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    if not isinstance(items, list):
        reason = f"结构不符（Data.Value 类型为 {type(items).__name__}，期望 list）"
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    if not items:
        reason = "返回为空（Data.Value 为空列表）"
        _emit(f"ℹ️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    # 1. PROCESAMIENTO DE PILOTOS ACTIVOS
    non_dict = [i for i in items if not isinstance(i, dict)]
    if non_dict:
        reason = (
            "结构不符（Data.Value 中存在非对象条目："
            f"{len(non_dict)} 条，例如 {type(non_dict[0]).__name__}）"
        )
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    raw_drivers = [
        i for i in items if i.get("PositionName") == "DRIVER" and is_active(i)
    ]
    raw_teams = [
        i for i in items if i.get("PositionName") == "CONSTRUCTOR" and is_active(i)
    ]

    if not raw_drivers or not raw_teams:
        reason = (
            "结构不符（响应结构可解析，但未找到有效参赛记录："
            f"活动车手 {len(raw_drivers)} 条, 活动车队 {len(raw_teams)} 条）"
        )
        _emit(f"⚠️ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    drivers_by_code = {}

    for d in raw_drivers:
        driver_code = d.get("DriverTLA", "N/A")

        # Se define Season_Fantasy_Points en su posición exacta
        driver_payload = {
            "Driver_Name": d.get("DisplayName", "N/A"),
            "Driver_Code": driver_code,
            "Team_Name": d.get("TeamName", "N/A"),
            "Round_Fantasy_Points": safe_float(d.get("GamedayPoints")),
            "Season_Fantasy_Points": 0.0,
            "Selected_Percentage": safe_percentage(d.get("SelectedPercentage")),
            "Value": safe_float(d.get("Value")),
            "Qualifying_Points": safe_float(d.get("QualifyingPoints")),
            "Sprint_Points": safe_float(d.get("SprintPoints")),
            "Race_Points": safe_float(d.get("RacePoints")),
        }

        drivers_by_code.setdefault(driver_code, []).append(driver_payload)

    driver_merges = {
        code: records
        for code, records in drivers_by_code.items()
        if len(records) > 1
    }

    processed_drivers = [
        merge_driver_records(records) for records in drivers_by_code.values()
    ]

    # 2. PROCESAMIENTO DE EQUIPOS ACTIVOS (con normalización de códigos)
    teams_by_code = {}
    normalizations = []

    for t in raw_teams:
        raw_code = t.get("DriverTLA", "N/A")
        team_code = TEAM_CODE_OVERRIDES.get(raw_code, raw_code)
        if team_code != raw_code:
            normalizations.append((raw_code, team_code, t.get("DisplayName", "N/A")))

        team_payload = {
            "Team_Name": t.get("DisplayName", "N/A"),
            "Team_Code": team_code,
            "Round_Fantasy_Points": safe_float(t.get("GamedayPoints")),
            "Season_Fantasy_Points": 0.0,
            "Selected_Percentage": safe_percentage(t.get("SelectedPercentage")),
            "Value": safe_float(t.get("Value")),
            "Qualifying_Points": safe_float(t.get("QualifyingPoints")),
            "Sprint_Points": safe_float(t.get("SprintPoints")),
            "Race_Points": safe_float(t.get("RacePoints")),
        }

        teams_by_code.setdefault(team_code, []).append(team_payload)

    team_merges = {
        code: records
        for code, records in teams_by_code.items()
        if len(records) > 1
    }

    processed_teams = [
        merge_driver_records(records) for records in teams_by_code.values()
    ]

    # 3. PUNTO DE PARTIDA DE LOS ACUMULADOS (explícito y verificable)
    base_drivers, base_teams, cumulative_desc = _resolve_cumulative_start(
        season, race_id, cumulative_drivers, cumulative_teams, data_dir=data_dir
    )

    for d in processed_drivers:
        code = d["Driver_Code"]
        prev_points = base_drivers.get(code, 0.0)
        round_points = d["Round_Fantasy_Points"]
        total = round(prev_points + round_points, 1)

        base_drivers[code] = total
        d["Season_Fantasy_Points"] = total

    processed_drivers.sort(
        key=lambda x: x["Season_Fantasy_Points"],
        reverse=True,
    )

    for t in processed_teams:
        code = t["Team_Code"]
        prev_points = base_teams.get(code, 0.0)
        round_points = t["Round_Fantasy_Points"]
        total = round(prev_points + round_points, 1)

        base_teams[code] = total
        t["Season_Fantasy_Points"] = total

    processed_teams.sort(
        key=lambda x: x["Season_Fantasy_Points"],
        reverse=True,
    )

    # 4. GUARDADO LOCAL EN JSON
    try:
        filename = save_round_json(
            processed_drivers=processed_drivers,
            processed_teams=processed_teams,
            race_id=race_id,
            season=season,
            data_dir=data_dir,
        )
    except Exception as e:
        reason = f"写入失败（{type(e).__name__}: {e}）"
        _emit(f"❌ Ronda {race_id}: {reason}")
        _print_failure_summary(
            season, race_id, reason, cumulative_drivers, cumulative_teams
        )
        return False

    # Solo se confirma el acumulado después de escribir el archivo con éxito.
    cumulative_drivers.clear()
    cumulative_drivers.update(base_drivers)
    cumulative_teams.clear()
    cumulative_teams.update(base_teams)

    # 5. RESUMEN AUDITABLE DE LA RONDA
    _print_success_summary(
        season=season,
        race_id=race_id,
        filename=filename,
        processed_drivers=processed_drivers,
        processed_teams=processed_teams,
        driver_merges=driver_merges,
        team_merges=team_merges,
        normalizations=normalizations,
        cumulative_desc=cumulative_desc,
        cumulative_drivers=cumulative_drivers,
        cumulative_teams=cumulative_teams,
        raw_driver_count=len(raw_drivers),
        raw_team_count=len(raw_teams),
    )

    return True


async def main():
    user_guid = os.getenv("F1_USER_GUID")
    token = os.getenv("F1_TOKEN")

    if not user_guid or not token:
        raise ValueError(
            "❌ Error: Las variables de entorno 'F1_USER_GUID' y/o 'F1_TOKEN' no están configuradas."
        )

    if APIClient is None or Client is None:
        raise RuntimeError(
            "❌ Error: no se encontró el paquete 'fantasy' (skelmis-f1-fantasy)."
        )

    client = Client(APIClient(user_guid=user_guid, token=token))

    season = datetime.now().year
    max_rondas = 24
    data_dir = _resolve_data_dir()

    cumulative_drivers = {}
    cumulative_teams = {}

    _emit(f"🚀 Descargando e historizando rondas de la temporada {season}...\n")

    for race_id in range(1, max_rondas + 1):
        _emit(f"Procesando Ronda {race_id}...")
        exito = await process_single_round(
            client,
            race_id,
            season,
            cumulative_drivers,
            cumulative_teams,
            data_dir=data_dir,
        )

        if not exito:
            _emit(f"\n⏹️ Bucle finalizado en Ronda {race_id}. Se han procesado todas las rondas jugadas.")
            break


if __name__ == "__main__":
    asyncio.run(main())
