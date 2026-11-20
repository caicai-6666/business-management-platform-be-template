"""单 worker 的中间件会话与提交后确认的消费入口。"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Awaitable, BinaryIO, Callable, Literal

from pydantic import SecretStr

from app.config.middleware import MiddlewareSettings
from app.infrastructure.middleware import MiddlewareClient, MiddlewareError
from app.schema.middleware import DeletionRequest, Delivery, IngestionRequest, PublishOutcome, Stream

logger = logging.getLogger(__name__)
Handler = Callable[[Delivery], Awaitable[Literal["committed", "replayed"]]]


class MiddlewarePlatform:
    def __init__(self, settings: MiddlewareSettings, *, transport=None):
        self.settings = settings
        self._client = MiddlewareClient(settings, transport=transport)
        self._token = None
        self._expires_at = 0.0
        self._ready = asyncio.Event()
        self._wake = asyncio.Event()
        self._closed = False
        self._session_task = None
        self._consumers = {}
        self._locks = {stream: asyncio.Lock() for stream in Stream}

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self):
        if self._closed:
            raise RuntimeError("中间件连接已关闭")
        if self._session_task is None:
            self._session_task = asyncio.create_task(self._maintain_session())

    async def close(self):
        self._closed = True
        tasks = list(self._consumers.values())
        if self._session_task is not None:
            tasks.append(self._session_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._token = None
        self._ready.set()
        await self._client.close()

    def _current_token(self):
        if not self._closed and time.monotonic() < self._expires_at:
            return self._token
        return None

    async def wait_ready(self, timeout=None):
        if self._session_task is None:
            raise RuntimeError("请先启动中间件连接")
        async with asyncio.timeout(timeout):
            while self._current_token() is None:
                if self._closed:
                    raise RuntimeError("中间件连接已关闭")
                self._ready.clear()
                await self._ready.wait()

    def _invalidate(self, token):
        # 迟到的 401 只能撤销发起该请求时使用的令牌。
        if token is not None and self._token == token:
            self._token = None
            self._ready.clear()
            self._wake.set()

    async def _maintain_session(self):
        interval = None
        while True:
            self._wake.clear()
            token = self._current_token()
            stage = "heartbeat" if token else "login"
            started = time.monotonic()
            try:
                if token is None:
                    self._token = None
                    self._ready.clear()
                    info = await self._client.login()
                    token = info.access_token
                    if time.monotonic() >= started + info.expires_in_seconds:
                        started = time.monotonic()
                        info = await self._client.heartbeat(token)
                else:
                    info = await self._client.heartbeat(token)
                    if self._token != token:
                        continue
                self._expires_at = started + info.expires_in_seconds
                if self._expires_at <= time.monotonic():
                    raise MiddlewareError(stage, "expired_response")
                self._token = token
                self._ready.set()
                interval = info.heartbeat_interval_seconds
                delay = max(0, started + interval - time.monotonic())
            except MiddlewareError as exc:
                logger.warning("middleware stage=%s code=%s", stage, exc.code)
                delay = self.settings.retry_interval_seconds
                if exc.status == 401:
                    self._invalidate(token)
                if interval and not (stage == "login" and exc.status in (401, 403)):
                    delay = min(interval, delay)
                if self._token is not None:
                    delay = min(delay, max(0, self._expires_at - time.monotonic()))
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except TimeoutError:
                pass

    @asynccontextmanager
    async def _authorization(self):
        token = self._current_token()
        if token is None:
            raise MiddlewareError("session", "not_ready")
        try:
            yield token
        except MiddlewareError as exc:
            if exc.status == 401:
                self._invalidate(token)
            raise

    async def query_user_login(self, user_token: SecretStr):
        async with self._authorization() as token:
            return await self._client.query_user_login(token, user_token)

    async def query_user_permission(self, userid: str):
        async with self._authorization() as token:
            return await self._client.query_user_permission(token, userid)

    async def _publish(self, method, *args):
        token = self._current_token()
        if token is None:
            return PublishOutcome("retry", code="session_not_ready")
        result = await method(token, *args)
        if result.code == "unauthorized":
            self._invalidate(token)
        return result

    async def publish_ingestion(self, fields: IngestionRequest, file: bytes | BinaryIO):
        return await self._publish(self._client.publish_ingestion, fields, file)

    async def publish_deletion(self, fields: DeletionRequest):
        return await self._publish(self._client.publish_deletion, fields)

    async def consume_once(self, stream: Stream | str, handler: Handler) -> bool:
        stream = Stream(stream)
        async with self._locks[stream]:
            async with self._authorization() as token:
                delivery = await self._client.pull(token, stream)
            if delivery is None:
                return False
            # 业务修改与持久回执须在回调返回前提交；重投由回调核对回执。
            if await handler(delivery) not in ("committed", "replayed"):
                raise MiddlewareError(stream.value, "uncommitted")
            async with self._authorization() as token:
                await self._client.ack(token, stream, delivery)
            return True

    def start_consumer(self, stream: Stream | str, handler: Handler):
        stream = Stream(stream)
        if self._closed or self._session_task is None:
            raise RuntimeError("请在已启动的平台连接上注册消费者")
        if stream in self._consumers:
            raise RuntimeError("该流已注册消费者")
        self._consumers[stream] = asyncio.create_task(self._consume(stream, handler))

    async def _consume(self, stream, handler):
        while True:
            await self.wait_ready()
            try:
                if await self.consume_once(stream, handler):
                    continue
            except Exception as exc:
                code = exc.code if isinstance(exc, MiddlewareError) else "handler_failed"
                logger.warning("middleware stage=%s code=%s", stream.value, code)
            await asyncio.sleep(self.settings.retry_interval_seconds)
