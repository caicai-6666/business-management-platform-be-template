"""通过应用专属代理取得并复用钉钉企业内部应用令牌。"""
import asyncio
import logging
from contextvars import ContextVar
from time import monotonic

import httpx
from pydantic import SecretStr

from app.config.dingtalk import DingTalkSettings


_private_request = ContextVar("dingtalk_private_request", default=False)


class _RequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _private_request.get()


class DingTalkError(RuntimeError):
    """只暴露阶段与脱敏的错误原因。"""


class DingTalkClient:
    def __init__(self, settings: DingTalkSettings):
        self._settings = settings
        self._http = httpx.AsyncClient(base_url="https://api.dingtalk.com",
                                       proxy=settings.proxy_url.get_secret_value(), trust_env=False,
                                       timeout=settings.timeout_seconds, verify=True, follow_redirects=False)
        # 底层 HTTP 调试日志可能包含查询参数和代理认证头；仅屏蔽本次钉钉调用。
        for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
                     "httpcore.proxy", "httpcore.socks"):
            logger = logging.getLogger(name)
            if not any(isinstance(item, _RequestLogFilter) for item in logger.filters):
                logger.addFilter(_RequestLogFilter())
        self._lock = asyncio.Lock()
        self._token = None
        self._expires_at = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._http.aclose()
        self._token = None

    async def _send(self, stage, method, path, **kwargs):
        marker = _private_request.set(True)
        try:
            async with asyncio.timeout(self._settings.timeout_seconds):
                return await self._http.request(method, path, **kwargs)
        except (httpx.RequestError, TimeoutError):
            raise DingTalkError(f"{stage} transport_unknown") from None
        finally:
            _private_request.reset(marker)

    async def access_token(self) -> SecretStr:
        async with self._lock:
            if self._http.is_closed:
                raise DingTalkError("token client_closed")
            if self._token is None or monotonic() >= self._expires_at:
                started = monotonic()
                response = await self._send("token", "POST", "/v1.0/oauth2/accessToken", json={
                    "appKey": self._settings.app_key.get_secret_value(),
                    "appSecret": self._settings.app_secret.get_secret_value(),
                })
                if response.status_code != 200:
                    raise DingTalkError(f"token http_{response.status_code}")
                try:
                    data = response.json()
                    token, ttl = data["accessToken"], data["expireIn"]
                    if (type(ttl) is not int or ttl <= 0 or not isinstance(token, str) or not token
                            or not token.isascii() or not token.isprintable() or " " in token):
                        raise ValueError
                    self._expires_at = started + ttl - min(60, ttl / 10)
                    if self._expires_at <= monotonic():
                        raise ValueError
                    self._token = SecretStr(token)
                except (ValueError, KeyError, TypeError, OverflowError):
                    raise DingTalkError("token invalid_response") from None
            return self._token

    async def request(self, method: str, path: str, *, params=None, json=None):
        """新版 OpenAPI 的固定目标请求，调用方使用受控路径并验证业务响应。"""
        if not path.startswith("/v1.0/") or any(c in path for c in ("?", "#", "\\", "://")):
            raise ValueError("需要钉钉 /v1.0/ 接口路径")
        token = await self.access_token()
        response = await self._send("openapi", method, path, params=params, json=json,
                                    headers={"x-acs-dingtalk-access-token": token.get_secret_value()})
        if response.status_code == 401 and self._token == token:
            self._token = None
        if not 200 <= response.status_code < 300:
            raise DingTalkError(f"openapi http_{response.status_code}")
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            raise DingTalkError("openapi invalid_response") from None
