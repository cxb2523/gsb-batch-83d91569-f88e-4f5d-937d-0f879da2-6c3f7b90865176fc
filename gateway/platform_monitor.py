"""Persisted platform checks over the real, existing WebMirage MCP service.

Local metadata polling and a persisted, low-frequency read-only probe schedule
share one serialized worker. Cached reads never initiate platform requests.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

try:
    from .platform_worker import CHECK_TOOL, PLATFORMS, PROBES, WRITE_TOOLS, MESSAGES, validate_credential_updates
except ImportError:
    from platform_worker import CHECK_TOOL, PLATFORMS, PROBES, WRITE_TOOLS, MESSAGES, validate_credential_updates


class PlatformError(Exception):
    pass


AUTO_INTERVALS = (15, 30, 60, 120)
MAX_BACKOFF = 4 * 3600
PROBE_GAP_SECONDS = 1


async def local_bridge(payload):
    """Use the SDK already installed in WebMirage; no new ports or restarts."""
    if os.environ.get('GATEWAY_PLATFORM_BRIDGE') != '1':
        raise PlatformError('本部署尚未启用本机 WebMirage 桥接')
    script = Path(__file__).with_name('platform_worker.py').read_text()
    process = await asyncio.create_subprocess_exec(
        'docker', 'exec', '-i', 'webmirage', 'python', '-c', script,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=70)
        result = json.loads(output)
        if process.returncode or 'bridge_error' in result:
            raise PlatformError('WebMirage MCP 通信未完成，请检查服务后重试')
        return result
    except (asyncio.TimeoutError, ValueError, OSError):
        raise PlatformError('WebMirage MCP 通信未完成，请检查服务后重试') from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class PlatformMonitor:
    def __init__(self, path: Path, runner=local_bridge):
        self.path, self.runner = path, runner
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, platform TEXT NOT NULL,
                    tool TEXT NOT NULL, category TEXT NOT NULL, elapsed_ms INTEGER,
                    revision TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual');
                CREATE INDEX IF NOT EXISTS checks_platform_time ON checks(platform,timestamp);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            if 'classifier_version' not in {row[1] for row in db.execute('PRAGMA table_info(checks)')}:
                db.execute('ALTER TABLE checks ADD COLUMN classifier_version INTEGER NOT NULL DEFAULT 0')
            columns = {row[1] for row in db.execute('PRAGMA table_info(checks)')}
            for column, definition in [('checker', "TEXT NOT NULL DEFAULT ''"), ('native_id', 'TEXT'), ('backend', "TEXT NOT NULL DEFAULT ''")]:
                if column not in columns:
                    db.execute(f'ALTER TABLE checks ADD COLUMN {column} {definition}')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS checks_native ON checks(native_id) WHERE native_id IS NOT NULL')
        self.path.chmod(0o600)
        self.cache = self.read_state('inventory', {})
        self.connected = False
        self.error = ''
        self.refreshed = 0
        self.lock = asyncio.Lock()
        self.refresh_task = None
        self.job_task = None
        self.last_finished = self.read_state('last_finished', 0)
        self.job = {'status': 'idle', 'total': 0, 'completed': 0, 'passed': 0, 'failed': 0, 'current': None}
        self.loop_task = None
        self.credential_baselines = self.read_state('credential_baselines', {})
        policy = self.read_state('auto_policy', {})
        interval = policy.get('interval_minutes', 30)
        self.auto_policy = {'enabled': policy.get('enabled', True) is True,
                            'interval_minutes': interval if type(interval) is int and interval in AUTO_INTERVALS else 30}
        self.schedules = self.read_state('probe_schedule', {})
        self.auto_retry_at = self.read_state('auto_retry_at', 0)

    @property
    def interval(self):
        return self.auto_policy['interval_minutes'] * 60

    @property
    def freshness_seconds(self):
        return self.interval + 300

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA busy_timeout=5000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def read_state(self, key, default):
        with self.db() as db:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_state(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))

    async def start(self):
        self.loop_task = asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            if time.time() - self.refreshed >= 120:
                await self.refresh()
            self.run_due_checks()
            await asyncio.sleep(30)

    def configure_auto(self, enabled: bool, interval_minutes: int):
        if type(enabled) is not bool or type(interval_minutes) is not int or interval_minutes not in AUTO_INTERVALS:
            raise ValueError('检测周期仅支持 15、30、60、120 分钟')
        self.auto_policy = {'enabled': enabled, 'interval_minutes': interval_minutes}
        self.save_state('auto_policy', self.auto_policy)
        for state in self.schedules.values():
            state['next_at'] = state['last_at'] + self.retry_delay(state['failures'])
        self.save_state('probe_schedule', self.schedules)
        return self.auto_settings()

    def auto_settings(self):
        return {**self.auto_policy, 'freshness_seconds': self.freshness_seconds,
                'max_backoff_minutes': MAX_BACKOFF // 60, 'representative_tools': len(PROBES)}

    def retry_delay(self, failures):
        return min(MAX_BACKOFF, self.interval * 2 ** min(failures, 8))

    def schedule_for(self, tool, revision):
        required = 2  # Only the unified MCP checker supplies health evidence.
        state = self.schedules.get(tool)
        if state and state.get('revision') == revision and state.get('classifier_version', 0) >= required:
            return state
        with self.db() as db:
            rows = db.execute("SELECT timestamp,category FROM checks WHERE tool=? AND revision=? AND classifier_version>=? AND source IN ('manual','auto','mcp') ORDER BY timestamp DESC,id DESC LIMIT 9",
                              (tool, revision, required)).fetchall()
        failures = 0
        for row in rows:
            if row[1] == 'ok':
                break
            failures += 1
        last = rows[0][0] if rows else 0
        return {'revision': revision, 'classifier_version': 2, 'last_at': last, 'failures': failures,
                'next_at': last + self.retry_delay(failures) if last else 0}

    def record_schedule(self, tool, revision, category, checked_at=None):
        previous = self.schedule_for(tool, revision)
        failures = 0 if category == 'ok' else min(previous['failures'] + 1, 8)
        now = checked_at if checked_at is not None else time.time()
        self.schedules[tool] = {'revision': revision, 'classifier_version': 2, 'last_at': now, 'failures': failures,
                                'next_at': now + self.retry_delay(failures)}
        self.save_state('probe_schedule', self.schedules)

    def platform_plan(self, platform):
        meta = self.cache.get('credentials', {}).get(platform, {})
        revision = meta.get('revision', '')
        names = [name for name in PROBES if name.startswith(platform + '_') and name in self.cache.get('registered', [])]
        plans = [self.schedule_for(name, revision) for name in names]
        # Native business counters are diagnostic only. Results from any MCP
        # client update the same persisted per-interface schedule instead.
        reuse_until = 0
        next_at = min((p['next_at'] for p in plans), default=0)
        state = 'backoff' if any(p['failures'] for p in plans) else 'scheduled'
        message = '部分接口失败，按各自退避时间复测' if state == 'backoff' else '等待自动检测'
        if not self.auto_policy['enabled']:
            state, message = 'disabled', '自动检测已暂停'
        elif not self.connected:
            state, message = 'mcp_unavailable', '等待 MCP 连接恢复'
        elif not names:
            state, message = 'unregistered', '代表接口尚未注册'
        elif meta and not meta.get('anonymous') and not meta.get('configured'):
            state, message = 'missing', '等待补齐必要凭证'
        elif self.auto_retry_at > time.time():
            state, message = 'backoff', 'MCP 通信恢复后等待退避结束'
            next_at = max(next_at, self.auto_retry_at)
        return {'state': state, 'message': message,
                'next_check_at': max(time.time(), next_at) if state not in ('disabled', 'mcp_unavailable', 'unregistered', 'missing') else None,
                'reuse_until': reuse_until, 'names': names}

    def run_due_checks(self):
        if (not self.auto_policy['enabled'] or not self.connected or self.lock.locked()
                or (self.job_task and not self.job_task.done()) or self.job_status()['cooldown_seconds']
                or self.auto_retry_at > time.time()):
            return
        names = []
        for platform in PLATFORMS:
            plan = self.platform_plan(platform)
            if plan['state'] in ('missing', 'unregistered'):
                continue
            revision = self.cache.get('credentials', {}).get(platform, {}).get('revision', '')
            names.extend(name for name in plan['names']
                         if max(self.schedule_for(name, revision)['next_at'], plan['reuse_until']) <= time.time())
        if names:
            return self.launch_checks(names, 'auto')

    async def refresh(self):
        if self.lock.locked():
            return
        async with self.lock:
            try:
                data = await self.runner({'action': 'inventory', 'after_id': self.read_state('native_cursor', 0),
                                          'store_id': self.read_state('native_store_id', None)})
                for platform, meta in data['credentials'].items():
                    old = self.cache.get('credentials', {}).get(platform, {})
                    incoming_calls = data.get('passive', {}).get(platform, {}).get('calls', 0)
                    old_calls = self.cache.get('passive', {}).get(platform, {}).get('calls', 0)
                    if incoming_calls < old_calls and platform in self.credential_baselines:
                        self.credential_baselines[platform] = incoming_calls
                    if old and old.get('revision') != meta.get('revision'):
                        self.credential_baselines[platform] = data.get('passive', {}).get(platform, {}).get('calls', 0)
                self.cache = data
                active = data.get('active_health')
                if active:
                    checks = sorted(active['history'] + active['checks'], key=lambda r: r.get('timestamp', 0))
                    for check in checks:
                        if not check.get('pending'):
                            self.ingest_check(check)
                    self.save_state('native_cursor', active['cursor'])
                    self.save_state('native_store_id', active['store_id'])
                self.connected, self.error = True, ''
                self.save_state('inventory', data)
                self.save_state('credential_baselines', self.credential_baselines)
            except (PlatformError, OSError, KeyError, ValueError):
                self.connected, self.error = False, '无法读取 WebMirage MCP 状态；正在保留最后一次记录'
            self.refreshed = time.time()

    def request_refresh(self):
        if self.refresh_task and not self.refresh_task.done():
            return
        # A status refresh cannot become a high-frequency local MCP poll either.
        if time.time() - self.refreshed < 15:
            return
        self.refresh_task = asyncio.create_task(self.refresh())

    def job_status(self):
        return {**self.job, 'cooldown_seconds': max(0, math.ceil(60 - (time.time() - self.last_finished)))}

    def insert_check(self, platform, tool, category, elapsed_ms, revision, source='manual', *, checked_at=None, native_id=None, backend=''):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO checks(timestamp,platform,tool,category,elapsed_ms,revision,source,classifier_version,checker,native_id,backend) VALUES (?,?,?,?,?,?,?,2,?,?,?)',
                       (time.time() if checked_at is None else checked_at, platform, tool, category, elapsed_ms, revision, source, CHECK_TOOL, native_id, backend))
            if native_id and source in ('manual', 'auto'):
                db.execute('UPDATE checks SET source=? WHERE native_id=?', (source, native_id))
            db.execute('DELETE FROM checks WHERE timestamp<?', (time.time() - 30 * 86400,))
            db.execute('DELETE FROM checks WHERE id NOT IN (SELECT id FROM checks ORDER BY timestamp DESC,id DESC LIMIT 10000)')

    def ingest_check(self, check, source='mcp'):
        if check.get('cached'):
            source = 'mcp'  # A cached read must not rewrite the original origin.
        name = check['tool']
        platform = name.split('_', 1)[0]
        revision = self.cache.get('credentials', {}).get(platform, {}).get('revision', '')
        if not check['credential_current']:
            revision = 'previous-native:' + check['id']
        with self.db() as db:
            exists = db.execute('SELECT 1 FROM checks WHERE native_id=?', (check['id'],)).fetchone()
            if exists and check['credential_current']:
                # A rollback can make a previously imported historical result
                # current again. Trust the native checker without duplicating it.
                db.execute('UPDATE checks SET revision=?,backend=? WHERE native_id=?',
                           (revision, check.get('backend', ''), check['id']))
        if not exists and check['credential_current'] and check['timestamp'] >= self.schedule_for(name, revision)['last_at']:
            self.record_schedule(name, revision, check['category'], check['timestamp'])
        self.insert_check(platform, name, check['category'], check['elapsed_ms'], revision, source,
                          checked_at=check['timestamp'], native_id=check['id'], backend=check.get('backend', ''))

    def start_checks(self, platform=None, tool=None):
        if platform is not None and platform not in PLATFORMS:
            raise ValueError('未知平台')
        if tool is not None and (tool not in PROBES or (platform and not tool.startswith(platform + '_'))):
            raise ValueError('该工具不在只读检测白名单内')
        if self.job_task and not self.job_task.done():
            return self.job_status()
        if self.job_status()['cooldown_seconds']:
            raise PlatformError('检测完成后冷却 60 秒，请稍后再试')
        names = [name for name in PROBES if (not platform or name.startswith(platform + '_')) and (not tool or name == tool)]
        if not names:
            raise ValueError('没有可检测的接口')
        return self.launch_checks(names, 'manual')

    def launch_checks(self, names, source):
        self.job = {'status': 'running', 'source': source, 'total': len(names), 'completed': 0, 'passed': 0, 'failed': 0, 'current': None}
        self.job_task = asyncio.create_task(self._check(names, source))
        return self.job_status()

    async def _check(self, names, source):
        try:
            async with self.lock:
                for name in names:
                    if source == 'auto' and not self.auto_policy['enabled']:
                        self.job['status'] = 'cancelled'
                        break
                    platform = name.split('_', 1)[0]
                    self.job['current'] = name
                    meta = self.cache.get('credentials', {}).get(platform, {})
                    category, elapsed = 'mcp', None
                    result = {}
                    started = time.monotonic()
                    if source == 'auto':
                        # Persist a lease before sending; restarts cannot immediately
                        # repeat the same request when its outcome was lost.
                        state = dict(self.schedule_for(name, meta.get('revision', '')))
                        previous_at = state['last_at']
                        state.update(last_at=time.time(), next_at=time.time() + self.retry_delay(state['failures']))
                        self.schedules[name] = state
                        self.save_state('probe_schedule', self.schedules)
                    try:
                        result = await self.runner({'action': 'probe', 'tool': name})
                        if result.get('deferred'):
                            if source == 'auto':
                                state.update(last_at=previous_at, next_at=time.time() + 60)
                                self.schedules[name] = state
                                self.save_state('probe_schedule', self.schedules)
                            self.job['error'] = '统一检测正在执行，保留原结果，稍后重试'
                            break
                        category = result['category'] if result.get('category') in MESSAGES else 'interface'
                        elapsed = result.get('elapsed_ms')
                    except (PlatformError, OSError):
                        # A timed-out session must not hide every other platform.
                        # Confirm the service on a fresh local-only connection.
                        try:
                            await self.runner({'action': 'inventory'})
                            category = 'network' if time.monotonic() - started >= 40 else 'interface'
                        except (PlatformError, OSError):
                            self.job['error'] = 'MCP 通信未完成，未继续检测其余接口'
                    if result.get('id'):
                        self.ingest_check(result, source)
                    else:
                        self.record_schedule(name, meta.get('revision', ''), category)
                        self.insert_check(platform, name, category, elapsed, meta.get('revision', ''), source=source)
                    self.job['completed'] += 1
                    self.job['passed' if category == 'ok' else 'failed'] += 1
                    if category == 'mcp':
                        self.auto_retry_at = time.time() + self.interval
                        self.save_state('auto_retry_at', self.auto_retry_at)
                        break
                    await asyncio.sleep(PROBE_GAP_SECONDS)
                if self.job['status'] != 'cancelled':
                    self.job['status'] = 'error' if self.job.get('error') else 'done'
        except asyncio.CancelledError:
            self.job['status'] = 'cancelled'
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            self.job['status'] = 'error'
            self.job['error'] = '检测任务未完整完成，请查看已保存记录后重试'
        finally:
            self.job['current'] = None
            self.last_finished = time.time()
            self.save_state('last_finished', self.last_finished)
        await self.refresh()

    async def update_credentials(self, platform, updates):
        validate_credential_updates(platform, updates)
        if self.job_status()['status'] == 'running':
            raise PlatformError('正在检测或同步，请完成后再更新凭证')
        async with self.lock:
            result = await self.runner({'action': 'credentials', 'platform': platform, 'updates': updates})
            if not result.get('saved'):
                raise PlatformError('凭证未更新：字段受环境变量覆盖，或 MCP 不支持热加载')
            # Configuration changes never turn an unhealthy platform green.
            self.insert_check(platform, 'credentials', 'unknown', None, '', source='configuration')
            self.credential_baselines[platform] = self.cache.get('passive', {}).get(platform, {}).get('calls', 0)
        await self.refresh()
        return {'saved': True, 'reloaded': bool(result.get('reloaded')), 'message': '凭证已保存并热加载，请重新检测接口'}

    async def reddit_browser(self, operation):
        if operation not in ('start', 'stop'):
            raise ValueError('invalid browser action')
        if self.job_status()['status'] == 'running':
            raise PlatformError('正在检测，请完成后再操作浏览器')
        async with self.lock:
            result = await self.runner({'action': 'reddit_browser', 'operation': operation})
            self.cache['reddit_runtime'] = result['reddit_runtime']
            self.save_state('inventory', self.cache)
        return result

    def snapshot(self, platform=None, page=1):
        now = time.time()
        with self.db() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute('SELECT * FROM checks WHERE timestamp>=? ORDER BY timestamp DESC,id DESC', (now - 30 * 86400,))]
        items = []
        registered = self.cache.get('registered', [])
        for key, spec in PLATFORMS.items():
            meta = self.cache.get('credentials', {}).get(key, {})
            revision = meta.get('revision', '')
            passive = self.cache.get('passive', {}).get(key, {})
            plan = self.platform_plan(key)
            baseline = self.credential_baselines.get(key)
            changed = baseline is not None and passive.get('calls', 0) <= baseline
            endpoints = []
            known = sorted({name for name in registered if name.startswith(key + '_')} | {n for n in PROBES if n.startswith(key + '_')})
            for name in known:
                all_events = [r for r in rows if r['tool'] == name and r['source'] in ('manual', 'auto', 'mcp')]
                obsolete = any(r['revision'] == revision and r['classifier_version'] < 2 for r in all_events)
                events = [r for r in all_events if r['revision'] == revision and r['classifier_version'] >= 2 and r['checker'] == CHECK_TOOL]
                last = events[0] if events else None
                recent = [r for r in events if r['timestamp'] >= now - 86400]
                category = last['category'] if last else 'unknown'
                freshness = ('stale' if now - last['timestamp'] > self.freshness_seconds else 'fresh') if last else ('policy_changed' if obsolete else 'credentials_changed' if all_events or (changed and name in PROBES) else 'never')
                message, advice = MESSAGES[category]
                if last and category == 'unknown':
                    message = '本次检测未确认结果，待复测'
                if name in WRITE_TOOLS:
                    message = '写操作已排除'
                elif name not in registered:
                    message = '工具尚未注册'
                elif freshness == 'credentials_changed':
                    message, advice = '凭证变更，待复测', '旧凭证的记录不用于判断新凭证；等待自动检测或手动复测。'
                elif freshness == 'policy_changed':
                    message, advice = '检测规则已更新，待复测', '旧结果未由统一 MCP 检测工具验证；保留历史，等待重新检测。'
                elif freshness == 'never':
                    message = '尚未检测' if name in PROBES else '未单独验证'
                elif freshness == 'stale':
                    message = '检测结果已过期（上次通过）' if category == 'ok' else '检测结果已过期（上次异常）'
                    advice = '上次结果：' + MESSAGES[category][0] + '；等待下一次自动或手动复测。'
                schedule = self.schedule_for(name, revision) if name in PROBES else None
                endpoints.append({'name': name, 'label': PROBES[name][0] if name in PROBES else name,
                                  'registered': name in registered, 'probeable': name in PROBES,
                                  'write': name in WRITE_TOOLS, 'category': category,
                                  'message': message, 'advice': advice, 'freshness': freshness,
                                  'checked_at': last['timestamp'] if last else None,
                                  'stale': freshness == 'stale', 'check_source': last['source'] if last else None,
                                  'next_check_at': max(now, schedule['next_at'], plan['reuse_until'], self.auto_retry_at)
                                  if schedule and name in registered and plan['next_check_at'] is not None else None,
                                  'elapsed_ms': last['elapsed_ms'] if last else None,
                                  'backend': last['backend'] if last else '',
                                  'samples': len(recent), 'success_rate': round(sum(r['category'] == 'ok' for r in recent) / len(recent) * 100, 1) if recent else None})
            changed = changed and not any(e['checked_at'] for e in endpoints)
            checked = [e for e in endpoints if e['checked_at'] and not e['stale']]
            failed = [e for e in checked if e['category'] != 'ok']
            stale_failed = [e for e in endpoints if e['checked_at'] and e['stale'] and e['category'] != 'ok']
            category = failed[0]['category'] if failed else 'ok' if checked else 'unknown'
            freshness = 'fresh' if checked else 'credentials_changed' if changed else 'stale' if any(e['checked_at'] for e in endpoints) else 'never'
            source = 'mcp_check' if checked else None
            if meta and not meta.get('anonymous') and not meta.get('configured'):
                category = 'missing'
            if category != 'missing' and self.connected and not any(e['registered'] for e in endpoints):
                category = 'unregistered'
            message, advice = MESSAGES[category]
            if category == 'ok':
                message = '统一 MCP 检测通过'
            elif category == 'unknown':
                if freshness == 'credentials_changed':
                    message, advice = '凭证变更，待复测', '旧凭证记录已失效，等待自动检测或手动复测。'
                elif freshness == 'stale':
                    message, advice = '检测结果已过期，待复测', '已有历史结果，但超出当前检测周期的有效期；不代表平台故障。'
                elif checked:
                    message, advice = '本次检测未确认结果，待复测', '请查看具体接口记录，等待自动检测或手动复测。'
                else:
                    message, advice = '尚未检测', '等待自动检测或手动检查代表接口。'
            if stale_failed and not failed:
                category = stale_failed[0]['category']
                freshness = 'stale'
                message = '部分接口旧异常待复测'
                advice = '上次异常：' + MESSAGES[category][0] + '；其他接口通过不能证明该接口恢复。'
            if any(e['freshness'] == 'policy_changed' for e in endpoints) and not failed and category in ('ok', 'unknown'):
                category, freshness, source = 'unknown', 'policy_changed', None
                message, advice = '检测规则已更新，待复测', '等待 webmirage_check_health 验证，旧结果不用于当前健康判定。'
            if self.cache.get('check_tool_available') is False:
                category, source = 'mcp', None
                message, advice = '统一 MCP 检测工具尚未就绪', '需要注册 webmirage_check_health；不使用旧调用计数代替接口检测。'
            if self.job['status'] == 'running' and (self.job.get('current') or '').startswith(key + '_'):
                plan.update(state='running', message='正在检测代表接口')
            items.append({'id': key, **spec, 'message': message, 'advice': advice, 'freshness': freshness,
                          'evidence_source': source, 'last_checked_at': max((e['checked_at'] or 0 for e in endpoints), default=0) or None,
                          'monitoring': {k: v for k, v in plan.items() if k not in ('names', 'reuse_until')},
                          'credentials': {k: v for k, v in meta.items() if k != 'revision'},
                          'passive': passive, 'credential_changed': changed, 'category': category,
                          'registered_count': sum(e['registered'] for e in endpoints),
                          'checked_count': sum(bool(e['checked_at']) for e in endpoints), 'endpoints': endpoints})
        history = [r for r in rows if platform is None or r['platform'] == platform]
        return {'timestamp': now, 'mcp_connected': self.connected, 'syncing': not self.refreshed,
                'reddit_runtime': self.cache.get('reddit_runtime', {'backend': 'http', 'available': False}),
                'synced_at': self.cache.get('timestamp'), 'error': self.error,
                'monitoring': self.auto_settings(), 'health_checker': CHECK_TOOL,
                'health_checker_ready': self.cache.get('check_tool_available', False), 'platforms': items, 'job': self.job_status(),
                'history': {'total': len(history), 'page': page,
                            'rows': [{k: v for k, v in r.items() if k != 'revision'} | (
                                {'category': 'unknown', 'message': '旧版检测结果，待重新验证', 'advice': '原始记录已保留；等待统一 MCP 检测重新验证。'}
                                if r['classifier_version'] < 2 and r['source'] in ('manual', 'auto', 'mcp')
                                else {'message': '凭证已更新，待复测' if r['source'] == 'configuration' else MESSAGES[r['category']][0], 'advice': MESSAGES[r['category']][1]})
                                     for r in history[(page - 1) * 20:page * 20]]}}

    async def close(self):
        tasks = [task for task in (self.loop_task, self.refresh_task, self.job_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
