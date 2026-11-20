import asyncio
import json
import os
import unittest
from email.parser import BytesParser
from email.policy import default
from urllib.parse import parse_qs
from unittest.mock import patch

import httpx
from pydantic import SecretStr, ValidationError

from app.config.middleware import MiddlewareSettings
from app.infrastructure.middleware import MiddlewareError
from app.schema.middleware import DeletionRequest, IngestionRequest, Stream
from app.service.middleware import MiddlewarePlatform


def feedback(stream):
    msg = dict(message_id="feedback-1", reviewer="审核员", note="", created_at="2026-11-20T10:00:00Z",
               target_platform_code="fixture")
    if stream == Stream.FILE_LEVEL:
        msg.update(source_id="EQ/001", file_level=-1)
    elif stream == Stream.INGESTION:
        msg.update(request_id="request-1", passport=[" P ", " P "], file_level=0)
    else:
        msg.update(request_id="request-1", approved=False)
    return {"offset": 5, "message": msg}


class PlatformTests(unittest.IsolatedAsyncioTestCase):
    async def platform(self, handler, on_heartbeat=None):
        self.logins = 0
        settings = MiddlewareSettings(base_url="http://127.0.0.1", platform_code="fixture",
                                      secret="fixture-secret", retry_interval_seconds=0.05)

        async def dispatch(req):
            prefix = "/middleware-service/api/"
            self.assertTrue(req.url.path.startswith(prefix))
            path = req.url.path.removeprefix(prefix)
            if path == "platform/login":
                self.assertEqual(json.loads(req.content), {"platform_code": "fixture", "secret": "fixture-secret"})
                self.logins += 1
                return httpx.Response(200, json=dict(code="fixture", access_token=f"token-{self.logins}",
                                                     token_type="bearer", expires_in_seconds=10, heartbeat_interval_seconds=1))
            self.assertEqual(req.headers["Authorization"], f"Bearer token-{self.logins}")
            if path == "platform/heartbeat":
                self.assertEqual(req.content, b"")
                if on_heartbeat:
                    return on_heartbeat()
                return httpx.Response(200, json=dict(code="fixture", expires_in_seconds=10, heartbeat_interval_seconds=1))
            return await handler(path, req)

        platform = MiddlewarePlatform(settings, transport=httpx.MockTransport(dispatch))
        await platform.start()
        self.addAsyncCleanup(platform.close)
        await platform.wait_ready(2)
        return platform

    async def test_config(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(MiddlewareSettings.from_env())
            os.environ["MIDDLEWARE_SECRET"] = "fixture-secret"
            with self.assertRaises(ValueError) as e:
                MiddlewareSettings.from_env()
            self.assertNotIn("fixture-secret", str(e.exception))

    async def test_heartbeat_relogin_and_identity(self):
        beat = asyncio.Event()

        def expire():
            beat.set()
            return httpx.Response(401)

        async def user(path, req):
            if path == "user/login-cache":
                self.assertEqual(json.loads(req.content), {"access_token": "user-fixture"})
                return httpx.Response(200, json=dict(is_logged_in=True, userid="u1", username="tester", ttl=5))
            self.assertEqual(json.loads(req.content), {"userid": "u1"})
            return httpx.Response(200, json={"file_level": 0})

        platform = await self.platform(user, expire)
        await asyncio.wait_for(beat.wait(), 3)
        await platform.wait_ready(2)
        self.assertEqual(self.logins, 2)
        identity = await platform.query_user_login(SecretStr("user-fixture"))
        self.assertEqual(await platform.query_user_permission(identity.userid), 0)

    async def test_publish_wire_and_unknown_delivery(self):
        ingestion = IngestionRequest(source_id="EQ-001", name="验收", abstract="资料", reviewer="合成人", file_extension="docx")
        deletion = DeletionRequest(source_id="EQ-001", name="验收", abstract="资料",
                                   uploader="u", applicant="a", passport=[" P ", " P ", "other"])
        with self.assertRaises(ValidationError):
            DeletionRequest(**{**deletion.model_dump(), "passport": []})
        calls = []
        responses = [
            (201, {"status": "published", "message_id": "published-1"}),
            (409, {"detail": {"message": "该平台的 source_id 已有尚未确认的删除申请", "message_id": "old", "offset": None}}),
            (503, {"detail": {"message": "消息发布未获确认，需核对投递结果", "message_id": "candidate"}}),
            (409, {"detail": {"message": "其他冲突", "message_id": "candidate", "offset": 1}}),
            (422, {"detail": "fixture-secret"}),
            (401, {}), (201, {}), (0, {}),
        ]

        async def publish(path, req):
            calls.append(path)
            if path == "ingestion-requests/publish":
                mime = BytesParser(policy=default).parsebytes(
                    b"Content-Type: " + req.headers["content-type"].encode() + b"\r\n\r\n" + req.content)
                parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in mime.iter_parts()}
                self.assertEqual(parts.pop("file"), b"fixture-file")
                self.assertEqual({k: v.decode() for k,v in parts.items()}, ingestion.model_dump())
            else:
                self.assertEqual(path, "deletion-requests/publish")
                self.assertEqual(parse_qs(req.content.decode(), keep_blank_values=True)["passport"], [" P ", " P ", "other"])
            status, body = responses.pop(0)
            if not status:
                raise httpx.ReadTimeout("fixture-secret", request=req)
            return httpx.Response(status, json=body)

        platform = await self.platform(publish)
        self.assertEqual((await platform.publish_ingestion(ingestion, b"fixture-file")).message_id, "published-1")
        for state in ("duplicate", "uncertain", "uncertain", "blocked", "retry", "uncertain", "uncertain"):
            result = await platform.publish_deletion(deletion)
            self.assertEqual(result.state, state)
            if result.code == "unauthorized":
                await platform.wait_ready(2)
        self.assertEqual(len(calls), 8)

    async def test_commit_replay_and_competing_consumers(self):
        for stream in Stream:
            with self.subTest(stream=stream):
                envelope = feedback(stream)
                released = False
                acks = 0
                effects = []

                async def exchange(path, req):
                    nonlocal acks, released
                    if path == stream.value + "/pull":
                        self.assertEqual(req.content, b"")
                        return httpx.Response(204) if released else httpx.Response(200, json=envelope)
                    self.assertEqual(path, stream.value + "/ack")
                    self.assertEqual(json.loads(req.content), {"message_id": "feedback-1"})
                    acks += 1
                    if acks == 1:
                        raise httpx.ReadTimeout("lost ack", request=req)
                    released = True
                    return httpx.Response(200, json=dict(status="acknowledged", message_id="feedback-1", offset=5))

                async def apply(delivery):
                    if delivery.message.message_id in effects:
                        return "replayed"
                    effects.append(delivery.message.message_id)
                    return "committed"

                async def unfinished(delivery):
                    return None

                platform = await self.platform(exchange)
                with self.assertRaisesRegex(MiddlewareError, "uncommitted"):
                    await platform.consume_once(stream, unfinished)
                self.assertEqual(acks, 0)
                with self.assertRaisesRegex(MiddlewareError, "transport_unknown"):
                    await platform.consume_once(stream, apply)
                await platform.close()
                reopened = await self.platform(exchange)
                self.assertEqual(await asyncio.gather(reopened.consume_once(stream, apply),
                                                      reopened.consume_once(stream, apply)), [True, False])
                self.assertEqual(effects, ["feedback-1"])
                await reopened.close()

    async def test_invalid_deliveries_and_ack_identity(self):
        for stream, bad in [(Stream.INGESTION, {"file_level": None}), (Stream.INGESTION, {"passport": None}),
                            (Stream.DELETION, {"approved": 1}), (Stream.FILE_LEVEL, {"file_level": True}),
                            (Stream.FILE_LEVEL, {"target_platform_code": "other"})]:
            envelope = feedback(stream)
            envelope["message"].update(bad)

            async def exchange(path, req):
                self.assertTrue(path.endswith("/pull"))
                return httpx.Response(200, json=envelope)

            platform = await self.platform(exchange)
            with self.assertRaises(MiddlewareError):
                await platform.consume_once(stream, lambda _: self.fail("无效消息进入业务"))
            await platform.close()

        async def mismatch(path, req):
            if path.endswith("/pull"):
                data = feedback(Stream.INGESTION)
                del data["message"]["file_level"]
                data["message"]["passport"] = " P "
                return httpx.Response(200, json=data)
            return httpx.Response(200, json=dict(status="acknowledged", message_id="request-1", offset=5))

        async def apply(delivery):
            self.assertEqual(delivery.message.passport, (" P ",))
            self.assertNotIn("file_level", delivery.message.model_fields_set)
            return "committed"

        platform = await self.platform(mismatch)
        with self.assertRaisesRegex(MiddlewareError, "receipt_mismatch"):
            await platform.consume_once(Stream.INGESTION, apply)
