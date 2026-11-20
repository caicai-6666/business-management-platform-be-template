import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.config.dingtalk import DingTalkSettings
from app.infrastructure.dingtalk import DingTalkClient, DingTalkError


class DingTalkTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, proxy="http://127.0.0.1:22888"):
        return DingTalkSettings(corp_id="corp", app_key="key", app_secret="private-secret", proxy_url=proxy)

    async def test_optional_identity_and_proxy(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(DingTalkSettings.from_env())
            os.environ.update(DINGTALK_APP_KEY="key", DINGTALK_APP_SECRET="private-secret", DINGTALK_CORP_ID="corp")
            for proxy in ("", "ftp://localhost", "http://localhost/path"):
                os.environ["DINGTALK_PROXY_URL"] = proxy
                with self.assertRaises(ValueError) as error:
                    DingTalkSettings.from_env()
                self.assertNotIn("private-secret", str(error.exception))
            os.environ["DINGTALK_PROXY_URL"] = "http://user:proxy-pass@localhost:3128"
            settings = DingTalkSettings.from_env()
            self.assertNotIn("proxy-pass", repr(settings))
            self.assertNotIn("private-secret", repr(settings))

    async def test_proxy_failure_uses_one_connect(self):
        lines = []

        async def proxy(reader, writer):
            lines.append((await reader.readuntil(b"\r\n\r\n")).splitlines()[0])
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        async with server:
            url = "http://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
            async with DingTalkClient(self.settings(url)) as client:
                with self.assertRaisesRegex(DingTalkError, "transport_unknown"):
                    await client.access_token()
        self.assertEqual(lines, [b"CONNECT api.dingtalk.com:443 HTTP/1.1"])

    async def test_token_cache_and_failed_writes(self):
        counts = [0, 0]

        async def handler(req):
            if req.url.path.endswith("/oauth2/accessToken"):
                counts[0] += 1
                self.assertEqual(json.loads(req.content), {"appKey": "key", "appSecret": "private-secret"})
                return httpx.Response(200, json={"accessToken": f"token-{counts[0]}", "expireIn": 7200})
            counts[1] += 1
            self.assertEqual(req.headers["x-acs-dingtalk-access-token"], "token-1")
            return httpx.Response(401, text="private-secret")

        mock_http = httpx.AsyncClient(base_url="https://api.dingtalk.com", transport=httpx.MockTransport(handler))
        with patch("app.infrastructure.dingtalk.httpx.AsyncClient", return_value=mock_http) as make:
            async with DingTalkClient(self.settings()) as client:
                opts = make.call_args.kwargs
                self.assertFalse(opts["trust_env"])
                self.assertFalse(opts["follow_redirects"])
                self.assertTrue(opts["verify"])
                self.assertEqual(opts["proxy"], "http://127.0.0.1:22888")
                await asyncio.gather(client.access_token(), client.access_token())
                with self.assertRaisesRegex(DingTalkError, "openapi http_401"):
                    await client.request("POST", "/v1.0/fixture", json={"test": True})
                with self.assertRaises(ValueError):
                    await client.request("GET", "https://other.test")
                self.assertEqual((await client.access_token()).get_secret_value(), "token-2")
        self.assertEqual(counts, [2, 1])
