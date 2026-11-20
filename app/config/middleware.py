"""可选的平台会话配置，显式启用时校验完整身份。"""
import os
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class MiddlewareSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    base_url: str
    platform_code: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    secret: SecretStr = Field(repr=False)
    request_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    retry_interval_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def origin_only(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
                or url.path not in {"", "/"} or url.query or url.fragment
                or any(c.isspace() for c in value)):
            raise ValueError("请填写中间件服务根地址")
        _ = url.port
        return value.rstrip("/")

    @field_validator("secret")
    @classmethod
    def valid_secret(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("中间件密钥不能为空白")
        return value

    @classmethod
    def from_env(cls):
        values = {key: os.environ["MIDDLEWARE_" + key.upper()] for key in cls.model_fields
                  if "MIDDLEWARE_" + key.upper() in os.environ}
        if not any(values.get(key) for key in ("base_url", "platform_code", "secret")):
            return None
        try:
            return cls.model_validate(values)
        except ValueError:
            raise ValueError("中间件地址、平台身份或超时配置无效") from None
