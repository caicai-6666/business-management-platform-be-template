"""企业内部应用的身份与单一白名单出口。"""
import os
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class DingTalkSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    corp_id: str = Field(min_length=1, max_length=128)
    app_key: SecretStr = Field(repr=False, exclude=True)
    app_secret: SecretStr = Field(repr=False, exclude=True)
    proxy_url: SecretStr = Field(repr=False, exclude=True)
    timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    @field_validator("corp_id")
    @classmethod
    def valid_corp_id(cls, value):
        if not value.strip():
            raise ValueError("缺少 CorpId")
        return value

    @field_validator("app_key", "app_secret")
    @classmethod
    def not_blank(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("缺少钉钉应用凭据")
        return value

    @field_validator("proxy_url")
    @classmethod
    def valid_proxy(cls, value):
        raw = value.get_secret_value()
        try:
            url = urlsplit(raw)
            if (url.scheme not in ("http", "https") or not url.hostname or url.path not in ("", "/")
                    or url.query or url.fragment or url.port == 0 or any(c.isspace() for c in raw)):
                raise ValueError
        except ValueError:
            raise ValueError("需要 HTTP/HTTPS 正向代理地址") from None
        return value

    @classmethod
    def from_env(cls):
        values = {key: os.environ["DINGTALK_" + key.upper()] for key in cls.model_fields
                  if "DINGTALK_" + key.upper() in os.environ}
        if not any(values.get(k) for k in ("corp_id", "app_key", "app_secret", "proxy_url")):
            return None
        try:
            return cls.model_validate(values)
        except ValueError:
            raise ValueError("钉钉身份、固定出口或超时配置无效") from None
