"""Private local browser worker client. Cookies travel in a Unix socket body."""
from __future__ import annotations

import http.client
import json
import hashlib
import os
import socket
from pathlib import Path

from .client import RedditError

SUPPORTED_TOOLS = ('reddit_search', 'reddit_subreddit_posts')
ERRORS = {
    'browser': 'browser_unavailable 浏览器工作进程未就绪，请在平台管理页启动浏览器。',
    'missing': 'login_required 缺少 reddit_session，请先更新 Reddit 登录凭证。',
    'busy': 'browser_busy 浏览器正在处理其他请求，请稍后重试。',
    'unsupported': '浏览器试点暂不支持此接口或翻页，请切回 HTTP 后端。',
    'bad_input': '浏览器请求参数无效。',
    'network': '浏览器请求 timeout，已中止本次请求。',
    'forbidden': 'Reddit HTTP 403 Forbidden，浏览器访问被拒；不能仅凭此结果确认 Cookie 失效。',
    'rate_limit': 'Reddit HTTP 429 rate limit，已暂停浏览器请求，等待冷却。',
    'risk': 'Reddit captcha 平台验证，请在浏览器处理后重新检测。',
    'auth': 'Reddit login_required，需要更新并验证登录会话。',
    'interface': '浏览器接口返回异常，响应结构尚未确认。',
}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def worker_call(payload, *, timeout=36, path=None):
    path = path or os.environ.get('REDDIT_BROWSER_SOCKET') or str(Path.home() / '.webmirage/reddit-browser.sock')
    connection = UnixConnection(path, timeout)
    try:
        connection.request('POST', '/', body=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('response too large')
        result = json.loads(raw)
        if not isinstance(result, dict) or type(result.get('ok')) is not bool:
            raise ValueError('invalid worker envelope')
        if not result['ok']:
            category = result.get('category', 'interface')
            raise RedditError(ERRORS.get(category, ERRORS['interface']))
        return result
    except RedditError:
        raise
    except (TimeoutError, socket.timeout):
        raise RedditError(ERRORS['network']) from None
    except (OSError, ValueError, http.client.HTTPException):
        raise RedditError(ERRORS['browser']) from None
    finally:
        connection.close()


def runtime_status(config):
    try:
        raw = worker_call({'action': 'status', 'revision': hashlib.sha256(config.get('reddit_cookie', '').encode()).hexdigest()}, timeout=2)['status']
        status = {k: raw[k] for k in ('available', 'version', 'running', 'session_imported', 'busy',
                                     'last_activity', 'last_failure', 'cooldown_until', 'idle_seconds', 'session_current') if k in raw}
    except (RedditError, KeyError, TypeError):
        status = {'available': False, 'running': False, 'session_imported': False}
    return {'backend': config.get('reddit_backend', 'http'), 'backend_locked': bool(os.environ.get('REDDIT_BACKEND')),
            'supported_tools': list(SUPPORTED_TOOLS), **status}


class BrowserRedditClient:
    def __init__(self, cookie_str=''):
        self.cookie = cookie_str

    def _query(self, tool, args):
        result = worker_call({'action': 'query', 'tool': tool, 'args': args, 'cookie': self.cookie})
        rows = result.get('rows')
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('id'), str)
                                              or not isinstance(r.get('title'), str) for r in rows):
            raise RedditError(ERRORS['interface'])
        return rows

    def search(self, query, sort='relevance', limit=25, subreddit=''):
        return self._query('reddit_search', {'query': query, 'sort': sort, 'limit': max(1, min(limit, 100)), 'subreddit': subreddit})

    def get_subreddit_posts(self, subreddit, sort='hot', limit=25, after=''):
        if after:
            raise RedditError(ERRORS['unsupported'])
        return self._query('reddit_subreddit_posts', {'subreddit': subreddit, 'sort': sort, 'limit': max(1, min(limit, 100))}), ''

    def get_post(self, *args, **kwargs):
        raise RedditError(ERRORS['unsupported'])

    get_user_profile = get_post
    get_user_posts = get_post
