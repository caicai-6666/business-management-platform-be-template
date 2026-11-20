"""用环回 HTTP 服务验证中间件验收命令的请求与脱敏输出。"""
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tests/check_middleware.py"


class MiddlewareCheckTest(unittest.TestCase):
    def run_check(self, replies, timeout="3"):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                requests.append((self.command, self.path, self.headers.get("Authorization"), body))
                status, payload = replies[len(requests) - 1]
                if status is None:
                    return
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            do_GET = do_POST = respond

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            worker.start()
            try:
                env = dict(os.environ, MIDDLEWARE_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                           MIDDLEWARE_PLATFORM_CODE="sample", MIDDLEWARE_SECRET="fixture-secret",
                           MIDDLEWARE_REQUEST_TIMEOUT_SECONDS=timeout, no_proxy="127.0.0.1")
                result = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True,
                                        text=True, timeout=10)
            finally:
                server.shutdown()
                worker.join()
        for private in ("fixture-secret", "fixture-token"):
            self.assertNotIn(private, result.stdout + result.stderr)
        return result, requests

    health = (200, {"status": "ok"})
    login = (200, {"code": "sample", "token_type": "bearer", "access_token": "fixture-token"})
    heartbeat = (200, {"code": "sample", "heartbeat_interval_seconds": 5, "expires_in_seconds": 15})

    def test_session(self):
        result, requests = self.run_check([self.health, self.login, self.heartbeat])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["health OK", "login OK", "heartbeat OK"])
        prefix = "/middleware-service/api/"
        self.assertEqual(requests[0], ("GET", prefix + "health", None, b""))
        method, path, auth, body = requests[1]
        self.assertEqual((method, path, auth), ("POST", prefix + "platform/login", None))
        self.assertEqual(json.loads(body), {"platform_code": "sample", "secret": "fixture-secret"})
        self.assertEqual(requests[2:], [("POST", prefix + "platform/heartbeat", "Bearer fixture-token", b"")])

    def test_failures_stop_at_expected_stage(self):
        cases = [
            ([self.health, (401, "fixture-secret")], "platform/login HTTP 401"),
            ([self.health, (409, {})], "platform/login HTTP 409"),
            ([self.health, (None, None)], "platform/login 未取得完整响应"),
            ([self.health, (200, dict(self.login[1], access_token="fixture-token\ninvalid"))], "login 响应异常"),
            ([(200, ["fixture-secret"])], "health 响应格式异常"),
            ([self.health, self.login, (200, dict(self.heartbeat[1], expires_in_seconds=True))], "heartbeat 响应异常"),
        ]
        for replies, message in cases:
            with self.subTest(message=message):
                result, requests = self.run_check(replies)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(len(requests), len(replies))

    def test_invalid_timeout_before_request(self):
        for timeout in ("0", "nan", "inf"):
            with self.subTest(timeout=timeout):
                result, requests = self.run_check([], timeout)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("请求超时必须为有限正数", result.stderr)
                self.assertFalse(requests)


if __name__ == "__main__":
    unittest.main()
