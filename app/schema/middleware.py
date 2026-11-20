"""子平台与中间件的传输契约。"""
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field,
    SecretStr, StrictBool, StrictInt, StrictStr, field_validator, model_validator,
)


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("必填文本不能为空白")
    return value


def passports(value):
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        raise ValueError("通行证需要数组或历史标量")
    return value


Text = Annotated[StrictStr, AfterValidator(nonblank)]
Identifier = Annotated[Text, Field(max_length=128)]
Person = Annotated[Text, Field(max_length=200)]
Passports = Annotated[tuple[Text, ...], BeforeValidator(passports)]
PlatformCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]


class WireModel(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class SessionInfo(WireModel):
    code: PlatformCode
    expires_in_seconds: Annotated[StrictInt, Field(gt=0)]
    heartbeat_interval_seconds: Annotated[StrictInt, Field(gt=0)]

    @model_validator(mode="after")
    def check_interval(self):
        if self.heartbeat_interval_seconds >= self.expires_in_seconds:
            raise ValueError("心跳间隔必须小于有效期")
        return self


class Login(SessionInfo):
    access_token: SecretStr = Field(repr=False)
    token_type: Literal["bearer"]

    @field_validator("access_token")
    @classmethod
    def header_safe(cls, value):
        token = value.get_secret_value()
        if not token or not token.isascii() or not token.isprintable() or " " in token:
            raise ValueError("平台令牌格式无效")
        return value


class UserLogin(WireModel):
    userid: Text | None
    username: Text | None
    is_logged_in: StrictBool
    ttl: Annotated[StrictInt, Field(ge=0)]
    departments: tuple[Text, ...] | None = None
    employment_status: Literal["employed", "resigned"] | None = None

    @model_validator(mode="before")
    @classmethod
    def legacy_profile(cls, value):
        if isinstance(value, dict) and value.get("is_logged_in") is True:
            return {"departments": [], "employment_status": "employed", **value}
        return value

    @model_validator(mode="after")
    def complete_identity(self):
        profile = (self.userid, self.username, self.departments, self.employment_status)
        if self.is_logged_in:
            if None in profile or self.ttl <= 0:
                raise ValueError("用户身份无效")
        elif any(v is not None for v in profile) or self.ttl:
            raise ValueError("无效用户响应携带身份或有效期")
        return self


class UserPermission(WireModel):
    file_level: Annotated[StrictInt, Field(ge=0)] | None


class RequestFields(WireModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Identifier
    name: Annotated[Text, Field(max_length=200)]
    abstract: Annotated[Text, Field(max_length=10000)]
    note: StrictStr = Field(default="", max_length=10000)


class IngestionRequest(RequestFields):
    reviewer: Person
    file_extension: str = Field(pattern=r"^[A-Za-z0-9]{1,16}$")


class DeletionRequest(RequestFields):
    passport: Annotated[Passports, Field(min_length=1)]
    uploader: Person
    applicant: Person


@dataclass(frozen=True)
class PublishOutcome:
    state: Literal["published", "duplicate", "retry", "blocked", "uncertain"]
    message_id: str | None = None
    code: str | None = None


class Stream(str, Enum):
    INGESTION = "ingestion-results"
    DELETION = "deletion-results"
    FILE_LEVEL = "file-permission-adjustments"


class Feedback(WireModel):
    message_id: Identifier
    target_platform_code: PlatformCode
    created_at: AwareDatetime
    reviewer: Person
    note: StrictStr = Field(max_length=10000)

    @field_validator("created_at", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        if not isinstance(value, str) or not value or not ("T" in value or " " in value):
            raise ValueError("需要带时区的时间字符串")
        return value


class IngestionResult(Feedback):
    request_id: Identifier
    passport: Passports
    file_level: StrictInt | None = None

    @field_validator("file_level", mode="before")
    @classmethod
    def present_level_is_integer(cls, value):
        # 历史消息可能缺字段；显式 null 不是注册中心签发的等级。
        if type(value) is not int:
            raise ValueError("文件等级必须是整数")
        return value


class DeletionResult(Feedback):
    request_id: Identifier
    approved: StrictBool


class FileLevelAdjustment(Feedback):
    source_id: Identifier
    file_level: StrictInt


Message = TypeVar("Message", bound=Feedback)


class Delivery(WireModel, Generic[Message]):
    offset: Annotated[StrictInt, Field(ge=0)]
    message: Message


class Ack(WireModel):
    status: Literal["acknowledged"]
    message_id: Identifier
    offset: Annotated[StrictInt, Field(ge=0)]
