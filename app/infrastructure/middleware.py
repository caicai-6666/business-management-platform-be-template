"""中间件 HTTP 客户端。使用平台 Bearer，关闭代理继承、重定向和自动重发。"""
import asyncio
from typing import BinaryIO

import httpx
from pydantic import SecretStr

from app.config.middleware import MiddlewareSettings
from app.schema.middleware import (
    Ack, DeletionRequest, DeletionResult, Delivery, FileLevelAdjustment, IngestionRequest,
    IngestionResult, Login, PublishOutcome, SessionInfo, Stream, UserLogin, UserPermission,
)


class MiddlewareError(RuntimeError):
    def __init__(self, stage: str, code: str, status: int | None = None):
        self.stage = stage
        self.code = code
        self.status = status
        super().__init__(f"{stage} {code}")


_DELIVERIES = {
    Stream.INGESTION: Delivery[IngestionResult],
    Stream.DELETION: Delivery[DeletionResult],
    Stream.FILE_LEVEL: Delivery[FileLevelAdjustment],
}


class MiddlewareClient:
    def __init__(self, settings: MiddlewareSettings, *, transport=None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.base_url + "/middleware-service/api/", transport=transport,
            timeout=settings.request_timeout_seconds, follow_redirects=False, trust_env=False,
        )

    async def close(self):
        await self._http.aclose()

    async def _request(self, path, *, token=None, **kwargs):
        headers = {"Authorization": "Bearer " + token.get_secret_value()} if token else {}
        async with asyncio.timeout(self.settings.request_timeout_seconds):
            return await self._http.post(path, headers=headers, **kwargs)

    async def _read(self, path, model, *, token=None, allow_empty=False, **kwargs):
        try:
            response = await self._request(path, token=token, **kwargs)
        except (httpx.RequestError, TimeoutError):
            raise MiddlewareError(path, "transport_unknown") from None
        if allow_empty and response.status_code == 204:
            return None
        if response.status_code != 200:
            raise MiddlewareError(path, f"http_{response.status_code}", response.status_code)
        try:
            return model.model_validate(response.json())
        except (ValueError, RecursionError):
            raise MiddlewareError(path, "invalid_response") from None

    async def login(self):
        info = await self._read("platform/login", Login, json={
            "platform_code": self.settings.platform_code, "secret": self.settings.secret.get_secret_value()})
        if info.code != self.settings.platform_code:
            raise MiddlewareError("platform/login", "platform_mismatch")
        return info

    async def heartbeat(self, token):
        info = await self._read("platform/heartbeat", SessionInfo, token=token)
        if info.code != self.settings.platform_code:
            raise MiddlewareError("platform/heartbeat", "platform_mismatch")
        return info

    async def query_user_login(self, token, user_token: SecretStr):
        return await self._read("user/login-cache", UserLogin, token=token,
                                json={"access_token": user_token.get_secret_value()})

    async def query_user_permission(self, token, userid: str):
        permission = await self._read("user/file-permission", UserPermission, token=token, json={"userid": userid})
        return permission.file_level

    async def publish_ingestion(self, token, fields: IngestionRequest, file: bytes | BinaryIO):
        return await self._publish("ingestion-requests/publish", token, fields, "该平台的 source_id 已有尚未确认的入库请求",
                                   files={"file": ("upload." + fields.file_extension, file, "application/octet-stream")})

    async def publish_deletion(self, token, fields: DeletionRequest):
        return await self._publish("deletion-requests/publish", token, fields, "该平台的 source_id 已有尚未确认的删除申请")

    async def _publish(self, path, token, fields, duplicate_detail, **kwargs):
        try:
            response = await self._request(path, token=token, data=fields.model_dump(mode="json"), **kwargs)
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            return PublishOutcome("retry", code="connect_failed")
        except (httpx.RequestError, TimeoutError, OSError):
            return PublishOutcome("uncertain", code="transport_unknown")
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            payload = None
        status = response.status_code
        detail = payload.get("detail") if isinstance(payload, dict) else None
        receipt = payload if status == 201 else detail
        message_id = receipt.get("message_id") if isinstance(receipt, dict) else None
        if not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 128:
            message_id = None
        if status == 201 and message_id and receipt.get("status") == "published":
            return PublishOutcome("published", message_id)
        if status == 409 and message_id and detail.get("message") == duplicate_detail:
            offset = detail.get("offset")
            if "offset" in detail and (offset is None or type(offset) is int and offset >= 0):
                return PublishOutcome("duplicate", message_id)
        if status == 401:
            return PublishOutcome("retry", code="unauthorized")
        if status in (403, 422):
            return PublishOutcome("blocked", code=f"http_{status}")
        if (status == 503 and detail == "消息服务暂不可用，请稍后重试"
                or path.startswith("ingestion-") and status == 500 and detail == "文件保存失败"):
            return PublishOutcome("retry", code=f"http_{status}")
        # 代理错误、异常 2xx、确认丢失及去重状态未知都不能证明消息没有写入。
        return PublishOutcome("uncertain", message_id, f"http_{status}")

    async def pull(self, token, stream: Stream):
        path = stream.value + "/pull"
        delivery = await self._read(path, _DELIVERIES[stream], token=token, allow_empty=True)
        if delivery is not None and delivery.message.target_platform_code != self.settings.platform_code:
            raise MiddlewareError(path, "platform_mismatch")
        return delivery

    async def ack(self, token, stream: Stream, delivery: Delivery):
        if not isinstance(delivery, _DELIVERIES[stream]) or delivery.message.target_platform_code != self.settings.platform_code:
            raise MiddlewareError(stream.value + "/ack", "delivery_mismatch")
        message_id = delivery.message.message_id
        path = stream.value + "/ack"
        ack = await self._read(path, Ack, token=token, json={"message_id": message_id})
        if ack.message_id != message_id or ack.offset != delivery.offset:
            raise MiddlewareError(path, "receipt_mismatch")
        return ack
