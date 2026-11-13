"""Fixed local MCP bridge, executed inside the existing WebMirage container.

Input is JSON on stdin; output contains metadata and classified outcomes only.
Never emit credentials, tool response bodies, or exception messages.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import time

from pathlib import Path

if '__file__' in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webmirage.checks import CHECK_TOOL, SCHEMA_VERSION, PLATFORMS, PROBES, WRITE_TOOLS, MESSAGES, classify, configuration_revision
from webmirage.platforms.xianyu.credentials import RequiredCredentialError, missing_cookie_fields


def result_failed(result) -> bool:
    # MCP SDK 2 exposes snake_case Python fields; older clients use camelCase.
    return bool(getattr(result, 'is_error', getattr(result, 'isError', False)))


def decode_health_report(result):
    if result_failed(result):
        raise ValueError('health checker failed')
    report = getattr(result, 'structured_content', getattr(result, 'structuredContent', None))
    if report is None:
        report = json.loads('\n'.join(c.text for c in result.content if getattr(c, 'text', None)))
    if not isinstance(report, dict) or report.get('checker') != CHECK_TOOL or report.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('unsupported health report')
    store_id = report.get('store_id', '')
    if not isinstance(store_id, str) or not re.fullmatch('[a-f0-9]{32}', store_id):
        raise ValueError('invalid health store')
    def clean(row):
        if not isinstance(row, dict):
            raise ValueError('invalid health row')
        name = row.get('tool')
        if name not in PROBES:
            raise ValueError('invalid health tool')
        if row.get('pending'):
            return {'tool': name, 'pending': True}
        seq = row.get('sequence')
        timestamp = row.get('timestamp')
        elapsed = row.get('elapsed_ms')
        if (type(seq) is not int or seq < 1 or row.get('id') != f'{store_id}:{seq}'
                or row.get('checker') != CHECK_TOOL or row.get('category') not in MESSAGES
                or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp <= 0
                or timestamp > time.time() + 60 or type(elapsed) is not int or not 0 <= elapsed <= 120000
                or type(row.get('credential_current')) is not bool):
            raise ValueError('invalid health result')
        backend = row.get('backend', '')
        if backend not in ('', 'http', 'opencli'):
            raise ValueError('invalid health backend')
        return {k: row[k] for k in ('id', 'tool', 'category', 'timestamp', 'elapsed_ms', 'credential_current')} | {'checker': CHECK_TOOL, 'cached': bool(row.get('cached')), 'backend': backend}
    checks, history = report.get('checks'), report.get('history')
    cursor = report.get('cursor')
    if not isinstance(checks, list) or len(checks) > len(PROBES) or not isinstance(history, list) or len(history) > 200 or type(cursor) is not int or cursor < 0:
        raise ValueError('invalid health history')
    return {'store_id': store_id, 'cursor': cursor, 'checks': [clean(r) for r in checks], 'history': [clean(r) for r in history]}


async def probe_health(session, name):
    result = await session.call_tool(CHECK_TOOL, {'mode': 'check', 'platform': name.split('_', 1)[0], 'tool': name}, read_timeout_seconds=50)
    report = decode_health_report(result)
    match = next((r for r in report['checks'] if r['tool'] == name), None)
    if match is None or match.get('pending'):
        return {'tool': name, 'deferred': True}
    if not match['credential_current']:
        raise ValueError('health result uses old credentials')
    return match


def parse_health(text: str) -> dict:
    # Old servers count some business failures as successful calls. Their
    # positive counters must never defer probes or establish availability.
    business_verified = bool(re.search(r'^outcome_policy=business-v1$', text, re.M))
    def timestamp(age):
        match = re.fullmatch(r'([\d.]+)([smhd]) ago', age or '')
        return time.time() - float(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]] if match else None
    result = {}
    for line in text.splitlines():
        match = re.match(r'- (\w+): credential=\w+, calls=(\d+)(?: \(ok=(\d+) fail=(\d+)\))?', line)
        if not match or match[1] not in PLATFORMS:
            continue
        success = re.search(r'last_success=([\d.]+[smhd] ago|never)', line)
        error = re.search(r'last_error=([\d.]+[smhd] ago|never): (.*)', line)
        success_at = timestamp(success[1]) if success else None
        error_at = timestamp(error[1]) if error else None
        result[match[1]] = {'calls': int(match[2]), 'ok': int(match[3] or 0), 'fail': int(match[4] or 0),
                            'business_verified': business_verified,
                            'last_success_age': success[1] if success else None,
                            'last_error_age': error[1] if error else None,
                            'last_success_at': success_at, 'last_error_at': error_at,
                            'category': classify(error[2], True) if error_at and error_at >= (success_at or 0)
                            else 'ok' if success_at else 'unknown'}
    return result


def credentials(config: dict, platform: str) -> dict:
    spec = PLATFORMS[platform]
    fields = spec['fields']
    present = [field for field in fields if config.get(field)]
    missing = []
    cookie_fields = {}
    cookie = str(config.get(platform + '_cookie') or '')
    for pair in cookie.split(';'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            cookie_fields[key.strip()] = value.strip()
    if platform == 'twitter':
        missing = [field for field in fields if not config.get(field)]
    elif platform == 'xianyu':
        missing = missing_cookie_fields(cookie_fields)
    elif platform == 'xueqiu' and not cookie_fields.get('xq_a_token'):
        missing = ['xq_a_token']
    elif platform == 'reddit' and not cookie_fields.get('reddit_session'):
        missing = ['reddit_session（匿名访问可省略）']
    locked = [field for field in fields if os.environ.get(field.upper())]
    if platform == 'github' and any(os.environ.get(k) for k in ('GITHUB_TOKEN', 'GITHUB_TOKEN_2', 'GITHUB_TOKEN_3')):
        locked = ['github_tokens']
    # Private revision is used only by the gateway to invalidate old checks.
    revision = configuration_revision(config, platform)
    return {'configured': bool(present) and (spec['anonymous'] or not missing), 'missing': missing, 'fields': fields, 'locked': locked,
            'anonymous': spec['anonymous'], 'revision': revision}


async def run(payload: dict):
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client
    from webmirage.config import get_config
    action = payload.get('action')
    if action not in ('inventory', 'probe', 'credentials', 'reload', 'reddit_browser'):
        raise ValueError('invalid action')
    async with sse_client('http://127.0.0.1:8084/sse', timeout=5, sse_read_timeout=55) as streams:
        async with ClientSession(*streams, read_timeout_seconds=45) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            if action == 'inventory':
                result = await session.call_tool('webmirage_health', {})
                text = '\n'.join(c.text for c in result.content if getattr(c, 'text', None))
                config = get_config()
                from webmirage.platforms.reddit.browser import runtime_status
                reddit_runtime = await asyncio.to_thread(runtime_status, config)
                active = None
                if CHECK_TOOL in tools:
                    result = await session.call_tool(CHECK_TOOL, {'mode': 'status', 'after_id': payload.get('after_id', 0)})
                    active = decode_health_report(result)
                    if payload.get('store_id') and payload['store_id'] != active['store_id']:
                        active = decode_health_report(await session.call_tool(CHECK_TOOL, {'mode': 'status', 'after_id': 0}))
                return {'timestamp': time.time(), 'registered': sorted(tools), 'passive': parse_health(text),
                        'check_tool_available': CHECK_TOOL in tools, 'active_health': active,
                        'credentials': {p: credentials(config, p) for p in PLATFORMS}, 'reddit_runtime': reddit_runtime}
            if action == 'reddit_browser':
                from webmirage.platforms.reddit.browser import runtime_status, worker_call
                operation = payload.get('operation')
                if operation not in ('start', 'stop'):
                    raise ValueError('invalid browser operation')
                config = get_config()
                await asyncio.to_thread(worker_call, {'action': operation, 'cookie': config.get('reddit_cookie', '')})
                return {'reddit_runtime': await asyncio.to_thread(runtime_status, config)}
            if action == 'reload':
                result = await session.call_tool('webmirage_reload_config', {})
                text = '\n'.join(c.text for c in result.content if getattr(c, 'text', None))
                return {'reloaded': not result_failed(result) and 'warning' not in text.lower() and 'error' not in text.lower()}
            if action == 'probe':
                name = payload.get('tool')
                if name not in PROBES or name in WRITE_TOOLS:
                    raise ValueError('probe not allowed')
                if CHECK_TOOL not in tools:
                    raise ValueError('unified health tool is unavailable')
                return await probe_health(session, name)
            return await update_credentials(session, payload, tools)


COOKIE_VALUE_FIELDS = {
    'reddit': {name: 'reddit_cookie' for name in ('reddit_session', 'token_v2', 'csrf_token', 'session_tracker', 'loid', 'edgebucket', 'csv')},
    'xueqiu': {name: 'xueqiu_cookie' for name in ('xq_a_token', 'acw_tc', 'device_id')},
    'xianyu': {name: 'xianyu_cookie' for name in ('_m_h5_tk', 'unb', '_m_h5_tk_enc', 'cookie2', 'sgcookie', '_tb_token_', 't')},
}
DIRECT_VALUE_FIELDS = {
    'twitter': {'twitter_auth_token': 'auth_token', 'twitter_ct0': 'ct0'},
    'xianyu': {'xianyu_user_id': 'unb'},
    'github': {'github_tokens': None},
}


def validate_credential_updates(platform, updates):
    aliases = COOKIE_VALUE_FIELDS.get(platform, {})
    allowed = set(PLATFORMS.get(platform, {}).get('fields', []))
    allowed.update(aliases)
    if platform == 'reddit':
        allowed.add('reddit_backend')
    if not isinstance(updates, dict) or not updates or set(updates) - allowed:
        raise ValueError('invalid credential fields')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 16000
           or any(c in v for c in ('\r', '\n', '\0')) for v in updates.values()):
        raise ValueError('invalid credential value')
    if len(json.dumps({'action': 'credentials', 'platform': platform, 'updates': updates}).encode()) > 40000:
        raise ValueError('credential payload too large')
    if 'reddit_backend' in updates and updates['reddit_backend'] not in ('http', 'opencli'):
        raise ValueError('invalid reddit backend')
    if platform == 'xianyu':
        missing = missing_cookie_fields(updates.get('xianyu_cookie', updates))
        if missing:
            raise RequiredCredentialError(missing)
    value_fields = {**DIRECT_VALUE_FIELDS.get(platform, {}), **{key: key for key in aliases}}
    for key, value in updates.items():
        if key in aliases and aliases[key] in updates:
            raise ValueError('conflicting credential formats')
        if key in value_fields:
            value = value.strip()
            name = value_fields[key]
            if ';' in value or (name and value.startswith(name + '=')) or (key == 'github_tokens' and value.lower().startswith('bearer ')):
                raise ValueError('invalid credential value format')


def replace_cookie_values(cookie: str, updates: dict) -> str:
    """Replace named values together; retain all other valid cookie pairs."""
    pairs = [pair.strip() for pair in cookie.split(';') if '=' in pair
             and pair.partition('=')[0].strip() not in updates]
    pairs.extend(key + '=' + value.strip() for key, value in updates.items())
    return '; '.join(pairs)


async def update_credentials(session, payload, tools):
    import fcntl
    import tempfile
    from pathlib import Path
    import yaml
    from webmirage.config import CONFIG_FILE, get_config
    platform, updates = payload.get('platform'), payload.get('updates')
    validate_credential_updates(platform, updates)
    meta = credentials(get_config(), platform)
    aliases = COOKIE_VALUE_FIELDS.get(platform, {})
    storage_fields = {aliases.get(key, key) for key in updates}
    if platform == 'reddit' and os.environ.get('REDDIT_BACKEND'):
        meta['locked'].append('reddit_backend')
    if storage_fields & set(meta['locked']):
        return {'saved': False, 'reason': 'environment_override'}
    if 'webmirage_reload_config' not in tools:
        return {'saved': False, 'reason': 'reload_unavailable'}
    path = Path(CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    def atomic(data):
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.gateway-config-')
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    with (path.parent / '.gateway-config.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = path.read_bytes() if path.exists() else b''
        config = yaml.safe_load(before) or {}
        for key, value in updates.items():
            if key not in aliases:
                config[key] = [value.strip()] if key == 'github_tokens' else value.strip()
        for storage in {aliases[key] for key in updates if key in aliases}:
            cookie_updates = {key: value for key, value in updates.items() if aliases.get(key) == storage}
            config[storage] = replace_cookie_values(str(config.get(storage) or ''), cookie_updates)
        after = yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode()
        atomic(after)
        try:
            result = await session.call_tool('webmirage_reload_config', {})
            text = '\n'.join(c.text for c in result.content if getattr(c, 'text', None))
            if result_failed(result) or 'warning' in text.lower() or 'error' in text.lower():
                raise RuntimeError('reload failed')
        except BaseException:
            if path.read_bytes() == after:
                atomic(before)
                try:
                    await session.call_tool('webmirage_reload_config', {})
                except BaseException:
                    pass
            raise
    return {'saved': True, 'reloaded': True, 'fields': sorted(updates)}


def main():
    import logging
    logging.disable(logging.CRITICAL)
    from loguru import logger
    logger.remove()
    try:
        data = sys.stdin.buffer.read(40001)
        if len(data) > 40000:
            raise ValueError('payload too large')
        result = asyncio.run(asyncio.wait_for(run(json.loads(data)), timeout=62))
        print(json.dumps(result, ensure_ascii=False))
    except BaseException as exc:
        # Do not expose the exception string or business response content.
        print(json.dumps({'bridge_error': type(exc).__name__}))
        sys.exit(1)


if __name__ == '__main__':
    main()
