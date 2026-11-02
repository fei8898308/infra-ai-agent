"""Explicit environment loading; secret values never appear in repr/errors."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    webhook_token: SecretStr = Field(min_length=32, max_length=512)
    dry_run: bool = True
    flowise_base_url: str = "http://flowise:3000"
    flowise_chatflow_id: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]*$", max_length=128)
    flowise_api_key: SecretStr = SecretStr("")
    flowise_read_only_confirmed: bool = False
    flowise_allow_insecure_http: bool = False
    flowise_timeout_seconds: float = Field(default=45, ge=1, le=120)
    max_body_bytes: int = Field(default=65536, ge=1024, le=262144)
    body_timeout_seconds: float = Field(default=10, ge=1, le=30)
    dedup_ttl_seconds: float = Field(default=300, ge=1, le=3600)
    dedup_max_entries: int = Field(default=1024, ge=1, le=10000)
    max_inflight: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def validate_configuration(self):
        for secret in (self.webhook_token, self.flowise_api_key):
            value = secret.get_secret_value()
            if value and (not value.isascii() or any(c.isspace() for c in value)):
                raise ValueError("Tokens must contain only non-whitespace ASCII characters")
            if any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise ValueError("Tokens must contain only printable ASCII characters")
            if value.lower().startswith(("change", "replace", "your-", "example")):
                raise ValueError("Replace placeholder credentials before starting")
        try:
            url = urlsplit(self.flowise_base_url)
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname
                and url.port != 0
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and url.path in {"", "/"}
                and not any(c.isspace() or ord(c) < 32 for c in self.flowise_base_url)
                and "\\" not in self.flowise_base_url
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "FLOWISE_BASE_URL must be an HTTP(S) origin without credentials or path"
            )
        if not self.dry_run:
            if not self.flowise_read_only_confirmed:
                raise ValueError(
                    "Review the tool-free flow and set FLOWISE_READ_ONLY_CONFIRMED=true"
                )
            if not self.flowise_chatflow_id or not self.flowise_api_key.get_secret_value():
                raise ValueError("Live analysis requires a chatflow ID and its API key")
            if url.scheme == "http" and not self.flowise_allow_insecure_http:
                raise ValueError("Use HTTPS or explicitly allow HTTP on the trusted lab network")
        return self

    @classmethod
    def from_environment(cls):
        values = {}
        for name in cls.model_fields:
            key = name.upper()
            if key in os.environ:
                values[name] = os.environ[key]
        for name in ("webhook_token", "flowise_api_key"):
            filename = os.environ.get(name.upper() + "_FILE")
            if filename:
                if values.get(name):
                    raise ValueError(f"Set either {name.upper()} or its _FILE variant")
                with Path(filename).open("r", encoding="utf-8") as handle:
                    value = handle.read(4097)
                if len(value) > 4096:
                    raise ValueError("Secret file is too large")
                values[name] = value.strip()
        return cls(**values)
