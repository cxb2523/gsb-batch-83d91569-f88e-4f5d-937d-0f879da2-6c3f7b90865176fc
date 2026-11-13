"""Local gateway console: authenticated, deliberately narrow Mihomo API facade."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import sqlite3
import time
import statistics
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from .history_store import query_history
    from .health_checks import ProbeManager, probe_history, CHECK_URL
    from .platform_monitor import PlatformMonitor, PlatformError, PLATFORMS
    from .platform_worker import RequiredCredentialError
except ImportError:
    from history_store import query_history
    from health_checks import ProbeManager, probe_history, CHECK_URL
    from platform_monitor import PlatformMonitor, PlatformError, PLATFORMS
    from platform_worker import RequiredCredentialError

ROOT_GROUP = "XFLTD"
AUTO_GROUP = "自动故障转移"
MANUAL_GROUP = "手动节点"
COOKIE = "mirage_session"
SESSION_SECONDS = 8 * 3600
logger = logging.getLogger("gateway")


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PolicyBody(BaseModel):
    mode: Literal["auto", "manual"]
    node: str | None = Field(default=None, max_length=512)


class ProbeBody(BaseModel):
    scope: Literal['current', 'page', 'provider', 'all']
    provider: str | None = Field(default=None, max_length=128)
    nodes: list[str] = Field(default_factory=list, max_length=12)


class PlatformCheckBody(BaseModel):
    platform: str | None = Field(default=None, max_length=64)
    tool: str | None = Field(default=None, max_length=128)


class PlatformCredentialBody(BaseModel):
    platform: str = Field(max_length=64)
    updates: dict


class PlatformMonitoringBody(BaseModel):
    enabled: bool
    interval_minutes: Literal[15, 30, 60, 120]


class RedditBackendBody(BaseModel):
    backend: Literal['http', 'opencli']


class RedditBrowserBody(BaseModel):
    operation: Literal['start', 'stop']


def resolve_node(groups: dict, name: str) -> str:
    seen = set()
    while name in groups and groups[name].get("now") and name not in seen:
        seen.add(name)
        name = groups[name]["now"]
    return name


def summarize(groups_data: dict, providers_data: dict, connections: dict, version: dict, config: dict) -> dict:
    groups = groups_data.get("proxies", {})
    configured = config.get("proxy-providers", {})
    labels = {"managed-primary": "主订阅", "managed-backup1": "备用订阅 01",
              "managed-backup2": "备用订阅 02", "managed-rescue": "本地救援"}
    providers = []
    nodes = []
    incoming = providers_data.get("providers", {})
    priority = list(configured)
    ordered = sorted(incoming, key=lambda key: (priority.index(key) if key in priority else len(priority), key))
    for key in ordered:
        provider = incoming[key]
        if not key.startswith("managed-"):
            continue
        definition = configured.get(key, {})
        source_nodes = []
        for raw in provider.get("proxies", []):
            history, alive = probe_history(raw)
            history = history[-10:]
            last = history[-1] if history else {}
            successful = [h['delay'] for h in history if isinstance(h.get('delay'), (int, float)) and h['delay'] > 0]
            try:
                stamp = datetime.fromisoformat(last['time'].replace('Z', '+00:00'))
                age = max(0, time.time() - (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp())
            except (KeyError, ValueError, TypeError):
                age = None
            interval = definition.get('health-check', {}).get('interval', 900)
            row = {"name": raw.get("name", ""), "provider": key,
                   "type": raw.get("type", ""), "alive": alive,
                   "tested": bool(history), "delay": last.get("delay", 0),
                   "checked_at": last.get("time"),
                   "stale": age is not None and age > interval + 80,
                   "samples": len(history), "success_rate": round(len(successful) / len(history) * 100, 1) if history else None,
                   "median_delay": statistics.median(successful) if successful else None,
                   "jitter": max(successful) - min(successful) if len(successful) > 1 else None,
                   "history": [h.get("delay", 0) for h in history]}
            source_nodes.append(row)
        providers.append({"id": key, "label": labels.get(key, key.removeprefix("managed-")),
                          "host": urlsplit(definition.get("url", "")).hostname or "本地缓存",
                          "local": definition.get("type") == "file" or key == "managed-rescue",
                          "count": len(source_nodes),
                          "alive": sum(n["alive"] and n["tested"] for n in source_nodes),
                          "updated_at": provider.get("updatedAt")})
        nodes.extend(source_nodes)
    root = groups.get(ROOT_GROUP, {})
    ready = (root.get("type") == "Selector"
             and groups.get(AUTO_GROUP, {}).get("type") == "Fallback"
             and groups.get(MANUAL_GROUP, {}).get("type") == "Selector")
    pools = groups.get(AUTO_GROUP, {}).get('all', [])
    optimized = bool(pools) and all(groups.get(p, {}).get('type') == 'URLTest' for p in pools)
    mode = "manual" if root.get("now") == MANUAL_GROUP else "auto"
    current = resolve_node(groups, ROOT_GROUP)
    active = next((n for n in nodes if n["name"] == current), None)
    rows = []
    for raw in connections.get("connections") or []:
        meta = raw.get("metadata") or {}
        rows.append({"id": raw.get("id"), "host": meta.get("host") or meta.get("destinationIP", ""),
                     "port": meta.get("destinationPort"), "source": meta.get("sourceIP", ""),
                     "process": meta.get("process", ""), "network": meta.get("network", ""),
                     "inbound": meta.get("inboundName", ""), "chains": raw.get("chains", []),
                     "rule": raw.get("rule", ""), "upload": raw.get("upload", 0),
                     "download": raw.get("download", 0), "start": raw.get("start", "")})
    return {"timestamp": time.time(), "version": version.get("version", "unknown"),
            "health_check": {"url": CHECK_URL, "unified_delay": bool(config.get('unified-delay')),
                             "full_interval": next((p.get('health-check', {}).get('interval', 900) for k, p in configured.items() if k.startswith('managed-')), 900),
                             "exit_interval": next((g.get('interval', 120) for g in config.get('proxy-groups', []) if g.get('name') == AUTO_GROUP), 120)},
            "policy": {"mode": mode, "ready": ready, "optimized": optimized, "node": current,
                       "latency_tolerance_ms": next((g.get('tolerance', 30) for g in config.get('proxy-groups', []) if g.get('name') in pools), 30),
                       "provider": active["provider"] if active else None,
                       "delay": active["delay"] if active else None,
                       "manual_node": groups.get(MANUAL_GROUP, {}).get("now")},
            "providers": providers, "nodes": nodes, "connections": rows,
            "totals": {"upload": connections.get("uploadTotal", 0),
                       "download": connections.get("downloadTotal", 0)}}


def create_app(*, admin_password: str | None = None, controller_secret: str | None = None,
               controller_url: str | None = None, transport=None, config_path: Path | None = None,
               history_path: Path | None = None, platform_runner=None) -> FastAPI:
    if admin_password is None:
        password_file = Path(os.environ.get("GATEWAY_ADMIN_PASSWORD_FILE", "/run/secrets/admin_password"))
        admin_password = password_file.read_text().strip() if password_file.is_file() else ""
    controller_secret = controller_secret if controller_secret is not None else os.environ.get("MIHOMO_API_SECRET", "")
    controller_url = controller_url or os.environ.get("MIHOMO_CONTROLLER", "http://mihomo:9090")
    config_path = config_path or Path(os.environ.get("GATEWAY_CONFIG", "/state/mihomo/config.yaml"))
    cookie_path = os.environ.get("GATEWAY_COOKIE_PATH", "/")
    history_path = history_path or Path(os.environ.get('GATEWAY_HISTORY_DB', str(Path(__file__).parent / 'data/history.sqlite3')))
    signing_key = hashlib.sha256((admin_password + "\0" + controller_secret).encode()).digest()
    switch_lock = asyncio.Lock()
    snapshot_lock = asyncio.Lock()
    failures: dict[str, list[float]] = {}

    @asynccontextmanager
    async def lifespan(application):
        async with httpx.AsyncClient(base_url=controller_url, timeout=10, trust_env=False,
                                     headers={"Authorization": "Bearer " + controller_secret},
                                     transport=transport) as client:
            application.state.controller = client
            application.state.snapshot = None
            application.state.probes = ProbeManager(client)
            try:
                application.state.platforms = PlatformMonitor(history_path.with_name('platforms.sqlite3'),
                                                             **({'runner': platform_runner} if platform_runner else {}))
                await application.state.platforms.start()
            except (OSError, sqlite3.Error):
                logger.error('Platform monitoring storage unavailable; gateway remains available')
                application.state.platforms = None
            try:
                yield
            finally:
                await application.state.probes.close()
                if application.state.platforms:
                    await application.state.platforms.close()

    application = FastAPI(title="Mirage Gateway", lifespan=lifespan, docs_url=None, redoc_url=None,
                          openapi_url=None)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == '/api/platforms/credentials':
            return JSONResponse(status_code=422, content={'detail': '凭证更新参数无效；未回显输入内容'})
        return await request_validation_exception_handler(request, exc)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def token(expiry: int) -> str:
        value = str(expiry)
        return value + "." + hmac.new(signing_key, value.encode(), hashlib.sha256).hexdigest()

    def authenticated(request: Request) -> bool:
        value = request.cookies.get(COOKIE, "")
        try:
            expiry = int(value.split(".", 1)[0])
            return bool(admin_password) and time.time() < expiry <= time.time() + SESSION_SECONDS + 60 and hmac.compare_digest(value, token(expiry))
        except (ValueError, TypeError):
            return False

    def require_auth(request: Request):
        if not authenticated(request):
            raise HTTPException(401, "请先登录管理台")
        if request.method != "GET" and request.headers.get("X-Gateway-Request") != "1":
            raise HTTPException(403, "请求来源校验失败")

    async def upstream(path: str, payload: dict | None = None):
        try:
            client = application.state.controller
            result = await (client.put(path, json=payload) if payload is not None else client.get(path))
            result.raise_for_status()
            return result.json() if result.content else {}
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "暂时无法连接 Mihomo，请稍后刷新") from None

    @application.get("/api/session")
    async def session(request: Request):
        return {"authenticated": authenticated(request), "configured": bool(admin_password)}

    @application.post("/api/login")
    async def login(body: LoginBody, request: Request, response: Response):
        if not admin_password:
            raise HTTPException(503, "管理密码尚未配置")
        key = request.client.host if request.client else "local"
        recent = [t for t in failures.get(key, []) if t > time.time() - 60]
        if len(recent) >= 5:
            raise HTTPException(429, "尝试次数过多，请一分钟后重试")
        if not hmac.compare_digest(body.password.encode(), admin_password.encode()):
            failures[key] = recent + [time.time()]
            raise HTTPException(401, "管理密码不正确")
        failures.pop(key, None)
        response.set_cookie(COOKIE, token(int(time.time()) + SESSION_SECONDS), max_age=SESSION_SECONDS,
                            httponly=True, secure=request.url.scheme == "https", samesite="strict", path=cookie_path)
        return {"ok": True}

    @application.post("/api/logout", dependencies=[Depends(require_auth)])
    async def logout(response: Response):
        response.delete_cookie(COOKIE, path=cookie_path)
        return {"ok": True}

    @application.get("/api/snapshot", dependencies=[Depends(require_auth)])
    async def snapshot():
        async with snapshot_lock, switch_lock:
            cached = application.state.snapshot
            if cached and time.time() - cached["timestamp"] < 2:
                return cached
            groups, providers, connections, version = await asyncio.gather(
                upstream("/proxies"), upstream("/providers/proxies"),
                upstream("/connections"), upstream("/version"))
            try:
                config = yaml.safe_load(config_path.read_text()) or {}
            except (OSError, yaml.YAMLError):
                config = {}
            result = summarize(groups, providers, connections, version, config)
            application.state.snapshot = result
            return result

    @application.get('/api/healthcheck', dependencies=[Depends(require_auth)])
    async def probe_status():
        return application.state.probes.public()

    def platform_manager():
        monitor = application.state.platforms
        if monitor is None:
            raise HTTPException(503, '平台监控存储暂时不可用；网关管理仍可使用')
        return monitor

    @application.get('/api/platforms', dependencies=[Depends(require_auth)])
    async def platform_status(platform: str | None = Query(default=None, max_length=64),
                              page: int = Query(default=1, ge=1, le=500)):
        monitor = platform_manager()
        if platform is not None and platform not in PLATFORMS:
            raise HTTPException(400, '未知平台')
        return monitor.snapshot(platform, page)

    @application.post('/api/platforms/refresh', dependencies=[Depends(require_auth)], status_code=202)
    async def refresh_platform_status():
        monitor = platform_manager()
        monitor.request_refresh()
        return {'scheduled': True, 'message': '仅同步本地 MCP 状态，不调用平台接口'}

    @application.post('/api/platforms/check', dependencies=[Depends(require_auth)], status_code=202)
    async def platform_check(body: PlatformCheckBody):
        try:
            return platform_manager().start_checks(body.platform, body.tool)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except PlatformError as exc:
            raise HTTPException(409, str(exc)) from None

    @application.post('/api/platforms/monitoring', dependencies=[Depends(require_auth)])
    async def configure_platform_monitoring(body: PlatformMonitoringBody):
        return platform_manager().configure_auto(body.enabled, body.interval_minutes)

    @application.post('/api/platforms/reddit/backend', dependencies=[Depends(require_auth)])
    async def reddit_backend(body: RedditBackendBody):
        try:
            return await platform_manager().update_credentials('reddit', {'reddit_backend': body.backend})
        except PlatformError:
            raise HTTPException(409, '请求方式未更新，请等待当前任务结束，或检查环境变量配置') from None

    @application.post('/api/platforms/reddit/browser', dependencies=[Depends(require_auth)])
    async def reddit_browser(body: RedditBrowserBody):
        try:
            return await platform_manager().reddit_browser(body.operation)
        except PlatformError:
            raise HTTPException(409, '浏览器操作未确认，请检查工作进程、登录凭证或当前检测任务') from None

    @application.post('/api/platforms/credentials', dependencies=[Depends(require_auth)])
    async def platform_credentials(body: PlatformCredentialBody):
        if not body.updates or any(not isinstance(v, str) or not v.strip() or len(v) > 16000
                                   or any(c in v for c in ('\r', '\n', '\0')) for v in body.updates.values()):
            raise HTTPException(400, '凭证字段不能为空、过长或包含换行')
        try:
            return await platform_manager().update_credentials(body.platform, body.updates)
        except RequiredCredentialError as exc:
            raise HTTPException(400, str(exc)) from None
        except ValueError:
            raise HTTPException(400, '请选择本平台允许更新的字段') from None
        except PlatformError as exc:
            raise HTTPException(409, str(exc)) from None
        except OSError:
            raise HTTPException(503, '凭证更新未确认：请检查环境变量覆盖或 MCP 服务；页面不会将其标为恢复') from None

    @application.post('/api/healthcheck', dependencies=[Depends(require_auth)], status_code=202)
    async def start_probe(body: ProbeBody):
        manager = application.state.probes
        if manager.public()['status'] == 'running':
            return manager.public()
        if manager.public()['cooldown_seconds']:
            raise HTTPException(429, '请等待冷却结束后再检测，避免重复请求')
        providers = (await upstream('/providers/proxies')).get('providers', {})
        candidates = [(key, n['name']) for key, provider in providers.items() if key.startswith('managed-')
                      for n in provider.get('proxies', []) if n.get('name')]
        if body.scope == 'current':
            groups = (await upstream('/proxies')).get('proxies', {})
            name = resolve_node(groups, ROOT_GROUP)
            candidates = [n for n in candidates if n[1] == name]
        elif body.scope == 'provider':
            if body.provider not in providers or not body.provider.startswith('managed-'):
                raise HTTPException(400, '请选择有效的订阅来源')
            candidates = [n for n in candidates if n[0] == body.provider]
        elif body.scope == 'page':
            names = set(body.nodes)
            if not names or names - {n[1] for n in candidates}:
                raise HTTPException(400, '节点列表已变化，请刷新后重试')
            candidates = [n for n in candidates if n[1] in names]
        if not candidates:
            raise HTTPException(400, '没有可检测的节点')
        try:
            # No await between final duplicate/cooldown check and task creation.
            result = manager.start(list(dict.fromkeys(candidates)), body.scope)
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from None
        application.state.snapshot = None
        return result

    @application.get('/api/history', dependencies=[Depends(require_auth)])
    def history(start: float, end: float,
                group_by: Literal['category', 'domain', 'source', 'node', 'route', 'inbound'] = 'category',
                search: str = Query(default='', max_length=200),
                group_value: str | None = Query(default=None, max_length=512),
                route: Literal['all', 'direct', 'proxy', 'reject', 'unknown'] = 'all',
                page: int = Query(default=1, ge=1, le=100000),
                group_page: int = Query(default=1, ge=1, le=100000),
                page_size: int = Query(default=20, ge=1, le=100)):
        if not history_path.is_file():
            raise HTTPException(503, '历史采集尚未启动，请稍后刷新')
        try:
            return query_history(history_path, start=start, end=end, now=time.time(), group_by=group_by,
                                 search=search, group_value=group_value, route=route,
                                 page=page, group_page=group_page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except sqlite3.Error:
            logger.exception('History database query failed')
            raise HTTPException(503, '历史记录暂时无法读取，请稍后重试') from None

    @application.post("/api/policy", dependencies=[Depends(require_auth)])
    async def policy(body: PolicyBody):
        async with switch_lock:
            groups = (await upstream("/proxies")).get("proxies", {})
            if (groups.get(ROOT_GROUP, {}).get("type") != "Selector"
                    or AUTO_GROUP not in groups or MANUAL_GROUP not in groups):
                raise HTTPException(409, "网关尚未启用自动／手动切换配置")
            if body.mode == "manual":
                providers = (await upstream("/providers/proxies")).get("providers", {})
                node = next((n for k, p in providers.items() if k.startswith("managed-")
                             for n in p.get("proxies", []) if n.get("name") == body.node), None)
                if not node:
                    raise HTTPException(400, "节点不存在，请刷新节点列表")
                history, alive = probe_history(node)
                if not alive or not history:
                    raise HTTPException(400, "该节点最近检测未通过，请选择可用节点")
            before_root = groups[ROOT_GROUP].get("now")
            before_manual = groups[MANUAL_GROUP].get("now")

            async def select(group: str, node: str):
                await upstream("/proxies/" + quote(group, safe=""), {"name": node})

            try:
                if body.mode == "manual":
                    await select(MANUAL_GROUP, body.node)
                target = MANUAL_GROUP if body.mode == 'manual' else AUTO_GROUP
                await select(ROOT_GROUP, target)
                actual = (await upstream("/proxies")).get("proxies", {})
                expected = target
                if actual[ROOT_GROUP].get("now") != expected:
                    raise HTTPException(503, "出口状态尚未生效")
                if body.mode == "manual" and resolve_node(actual, ROOT_GROUP) != body.node:
                    raise HTTPException(503, "手动节点尚未生效")
            except HTTPException:
                try:
                    if before_manual:
                        await select(MANUAL_GROUP, before_manual)
                    if before_root:
                        await select(ROOT_GROUP, before_root)
                except HTTPException:
                    raise HTTPException(503, "切换失败且自动恢复未完成，请检查当前出口") from None
                raise HTTPException(503, "切换未成功，已恢复原出口") from None
            finally:
                application.state.snapshot = None
            logger.info("gateway policy changed: mode=%s node=%s", body.mode, body.node or "automatic")
            return {"ok": True, "mode": body.mode, "node": resolve_node(actual, ROOT_GROUP)}

    static = Path(os.environ.get("GATEWAY_STATIC_DIR", str(Path(__file__).parent / "frontend/dist")))
    if static.is_dir():
        application.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @application.get("/favicon.svg")
        async def favicon():
            return FileResponse(static / "favicon.svg")

        @application.get("/")
        async def index():
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
