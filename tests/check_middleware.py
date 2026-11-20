"""使用专用测试平台检查中间件健康、登录和心跳；仅输出阶段与状态。"""
import getpass
import json
import math
import os
import sys
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CheckError(Exception):
    pass


def main():
    origin = os.environ["MIDDLEWARE_BASE_URL"].rstrip("/")
    url = urlsplit(origin)
    if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.path or url.query or url.fragment:
        raise CheckError("MIDDLEWARE_BASE_URL 只填写协议、主机和可选端口")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise CheckError("远程联调请使用 HTTPS，本机测试支持环回 HTTP")
    code = os.environ["MIDDLEWARE_PLATFORM_CODE"]
    timeout = float(os.environ.get("MIDDLEWARE_REQUEST_TIMEOUT_SECONDS", "30"))
    if not math.isfinite(timeout) or timeout <= 0:
        raise CheckError("请求超时必须为有限正数")
    if not code.strip():
        raise CheckError("MIDDLEWARE_PLATFORM_CODE 不能为空")
    opener = build_opener(NoRedirect())

    def call(method, path, payload=None, token=None):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(origin + "/middleware-service/api/" + path, body, headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as response:
                if response.status != 200:
                    raise CheckError(f"{path} HTTP {response.status}")
                result = json.load(response)
        except HTTPError as exc:
            exc.close()
            raise CheckError(f"{path} HTTP {exc.code}") from None
        except (URLError, OSError, HTTPException):
            raise CheckError(f"{path} 未取得完整响应，请核对服务状态") from None
        except ValueError:
            raise CheckError(f"{path} 响应格式异常") from None
        if not isinstance(result, dict):
            raise CheckError(f"{path} 响应格式异常")
        return result

    if call("GET", "health").get("status") != "ok":
        raise CheckError("health 响应异常")
    print("health OK")
    secret = os.environ.get("MIDDLEWARE_SECRET") or getpass.getpass("测试平台密钥：")
    session = call("POST", "platform/login", {"platform_code": code, "secret": secret})
    token = session.get("access_token")
    if not isinstance(token, str) or not token.isascii() or not token.isprintable() or " " in token:
        raise CheckError("login 响应异常")
    if not token or session.get("code") != code or session.get("token_type") != "bearer":
        raise CheckError("login 响应异常")
    print("login OK")
    beat = call("POST", "platform/heartbeat", token=token)
    interval = beat.get("heartbeat_interval_seconds")
    expires = beat.get("expires_in_seconds")
    if beat.get("code") != code or type(interval) is not int or type(expires) is not int or not 0 < interval < expires:
        raise CheckError("heartbeat 响应异常")
    print("heartbeat OK")


if __name__ == "__main__":
    try:
        main()
    except CheckError as error:
        sys.exit(str(error))
    except (KeyError, ValueError, EOFError, OSError, OverflowError):
        sys.exit("配置或连接异常，请检查环境变量和密钥输入")
