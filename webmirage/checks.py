"""Shared safe probe catalog and business-result classification."""
from __future__ import annotations

import re
import hashlib
import json

CHECK_TOOL = 'webmirage_check_health'
SCHEMA_VERSION = 1

PLATFORMS = {
    'twitter': {'label': 'X / Twitter', 'route': '代理', 'fields': ['twitter_auth_token', 'twitter_ct0'], 'anonymous': False},
    'xueqiu': {'label': '雪球', 'route': '代理', 'fields': ['xueqiu_cookie'], 'anonymous': True},
    'xianyu': {'label': '闲鱼', 'route': '代理', 'fields': ['xianyu_cookie', 'xianyu_user_id'], 'anonymous': False},
    'reddit': {'label': 'Reddit', 'route': '代理', 'fields': ['reddit_cookie'], 'anonymous': True},
    'github': {'label': 'GitHub', 'route': '直连', 'fields': ['github_tokens'], 'anonymous': True},
}
PROBES = {
    'twitter_me': ('当前登录账号', {}),
    'twitter_search': ('搜索推文', {'query': 'OpenAI', 'max_results': 1}),
    'xueqiu_quote': ('股票行情', {'symbol': 'SH600519'}),
    'xueqiu_hot_posts': ('热门讨论', {'limit': 1}),
    'xianyu_search_products': ('商品搜索', {'keyword': '键盘', 'page': 1, 'page_size': 1}),
    'xianyu_get_items': ('我的商品', {'page': 1, 'page_size': 1}),
    'reddit_subreddit_posts': ('社区帖子', {'subreddit': 'python', 'limit': 1}),
    'reddit_search': ('帖子搜索', {'query': 'python', 'limit': 1}),
    'github_get_repository': ('仓库信息', {'repository': 'MetaCubeX/mihomo'}),
    'github_search_repositories': ('仓库搜索', {'query': 'repo:MetaCubeX/mihomo', 'per_page': 1}),
}
WRITE_TOOLS = {'xianyu_confirm_delivery'}


def configuration_revision(config, platform):
    keys = PLATFORMS[platform]['fields'] + (['reddit_backend'] if platform == 'reddit' else [])
    values = {key: config.get(key, 'http' if key == 'reddit_backend' else None) for key in keys}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


MESSAGES = {
    'ok': ('只读接口检测通过', '其他接口需分别确认，当前结果不代表所有工具均可用。'),
    'auth': ('登录凭证无效或已过期', '在浏览器重新登录，更新本平台凭证后重新检测。'),
    'rate_limit': ('接口限流', '暂停主动检测，等待限流解除；不要连续换 Cookie 重试。'),
    'risk': ('平台风控或验证码拦截', '降低访问频率，在浏览器完成验证；必要时再更新登录凭证。'),
    'forbidden': ('平台拒绝访问（403）', '可能是出口、权限或登录状态限制，不能仅凭 403 判断 Cookie 失效。'),
    'network': ('网络连接失败或响应超时', '先检查代理出口和目标站连通性；不建议直接更换 Cookie。'),
    'upstream': ('平台服务异常', '保留凭证，稍后再检测平台服务。'),
    'interface': ('接口返回异常', '检查接口兼容性及参数；凭证失效尚未确认。'),
    'unregistered': ('工具尚未注册', '检查平台配置及 MCP 工具列表，必要时重新启动 WebMirage 应用。'),
    'unknown': ('尚无可确认的检测结果', '可手动运行代表接口检查。'),
    'mcp': ('MCP 通信未完成', '先检查 WebMirage 服务；本次无法确认平台接口是否可用。'),
    'browser': ('浏览器尚未就绪', '在 Reddit 请求方式区域检查工作进程、启动浏览器或等待当前请求完成。'),
    'missing': ('缺少必要凭证', '补齐页面列出的字段并热加载，再检测只读接口。'),
}


def classify(text: str, is_error: bool = False) -> str:
    lower = text.lower()
    failed = is_error or bool(re.match(
        r'^(error\b|invalid\b|(?:twitter|xueqiu|reddit|github)\s+api error\b|'
        r'闲鱼接口(?:错误|异常|返回错误|返回非\s*json|\s*http)|闲鱼风控拦截|'
        r'详情获取失败|❌[^\n]*(?:失败|错误)|fail_sys_[a-z_]+::)',
        lower.lstrip()))
    if not failed:
        return 'ok'
    # Risk and 403 are deliberately not called expired credentials.
    for category, markers in (
        ('browser', ('browser_unavailable', 'browser_busy')),
        ('rate_limit', ('429', 'rate limit', 'too many requests', '限流')),
        ('risk', ('rgv587', 'captcha', '风控', '验证码', 'anti-bot')),
        ('auth', ('401', 'unauthorized', 'bad credentials', 'login_required', 'session_expired',
                  'token_expired', 'expired token', 'invalid token', 'could not authenticate',
                  'not authenticated', 'login required', 'fail_sys_token_ex', 'fail_sys_token_empty',
                  'fail_sys_user_validate', 'token失效', 'token 失效', '登录过期', 'cookie expired')),
        ('forbidden', ('403', 'forbidden', 'access denied')),
        ('network', ('timeout', 'timed out', 'network', 'connection', 'dns', 'resolve', '超时', '网络请求失败')),
        ('upstream', ('http 500', 'http 502', 'http 503', 'http 504', 'service unavailable')),
    ):
        if any(marker in lower for marker in markers):
            return category
    return 'interface'
