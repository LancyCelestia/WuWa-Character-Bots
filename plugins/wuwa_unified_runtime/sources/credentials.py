"""凭据存储接口（cookie / API key 引用）。

目标：让外部抓取（FetchRequest）能用 "cookie" 或 "api_key" 而不把原始
凭据写进代码、审计日志或消息上下文。调用方只拿 ``CredentialRef``
引用，真正解析在 transport/fetch 边界进行，并且任何 repr / 审计输出
都只显示掩码预览。

安全规则：

- 凭据值不进入 ``AuditRecord.private_debug``、``RuntimeDiagnostic``、
  用户可见消息或 prompt。
- 默认文件路径放在被 git 忽略的 ``data/`` 下，例如
  ``data/credentials.json``。
- 使用 ``WUWA_CREDENTIAL_`` 前缀的环境变量时，值同样只在本模块内
  被读取，不会出现在错误文本里。

扩展方式：实现新的 ``CredentialStore``（例如密码管理器 / keyring），
然后在 ``build_credential_store(config)`` 里按配置选择。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KIND_COOKIE = "cookie"
KIND_API_KEY = "api_key"
KIND_OAUTH = "oauth_token"
SUPPORTED_KINDS = frozenset({KIND_COOKIE, KIND_API_KEY, KIND_OAUTH})

_MASK_VISIBLE_CHARS = 6


@dataclass(frozen=True)
class CredentialRef:
    """指向某个凭据的引用，不含原始值。"""

    ref_id: str
    kind: str
    source: str
    domain: str = ""
    masked_preview: str = ""
    expires_at: str = ""


@dataclass(frozen=True)
class CredentialValue:
    """凭据解析结果；只在 transport/fetch 边界消费。"""

    ref_id: str
    kind: str
    value: str
    domain: str = ""
    expires_at: str = ""


class CredentialMissingError(LookupError):
    """找不到对应凭据引用时抛出。"""


class CredentialStore(Protocol):
    def resolve(self, ref_id: str) -> CredentialValue | None:
        """按引用 id 解析凭据；不存在返回 None。"""

    def refs(self) -> list[CredentialRef]:
        """列出可用引用（只含元数据，不含值）。"""


def _masked_preview(value: str) -> str:
    if not value:
        return ""
    visible = value[: _MASK_VISIBLE_CHARS]
    return f"{visible}…(len={len(value)})"


def _normalize_ref_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise CredentialMissingError("empty credential ref id")
    return normalized


class EnvCredentialStore:
    """从环境变量读取凭据。

    变量名规则：``{prefix}{REF_ID}``，例如 ``WUWA_CREDENTIAL_BILIBILI``。
    可以再用 ``WUWA_CREDENTIAL_BILIBILI_KIND`` 声明类型（cookie/api_key）。
    """

    def __init__(self, *, prefix: str = "WUWA_CREDENTIAL_") -> None:
        self.prefix = prefix

    def resolve(self, ref_id: str) -> CredentialValue | None:
        from os import environ

        normalized = _normalize_ref_id(ref_id)
        key = f"{self.prefix}{normalized}"
        value = environ.get(key)
        if value is None:
            return None
        kind = environ.get(f"{key}_KIND", "").strip().lower() or KIND_COOKIE
        if kind not in SUPPORTED_KINDS:
            kind = KIND_COOKIE
        return CredentialValue(
            ref_id=normalized,
            kind=kind,
            value=value,
            domain=environ.get(f"{key}_DOMAIN", "").strip(),
            expires_at=environ.get(f"{key}_EXPIRES_AT", "").strip(),
        )

    def refs(self) -> list[CredentialRef]:
        from os import environ

        refs: list[CredentialRef] = []
        for key in environ:
            if not key.startswith(self.prefix) or key.endswith(
                ("_KIND", "_DOMAIN", "_EXPIRES_AT")
            ):
                continue
            ref_id = key[len(self.prefix) :]
            resolved = self.resolve(ref_id)
            if resolved is None:
                continue
            refs.append(_ref_from_value(resolved, source="env"))
        return refs


class FileCredentialStore:
    """从 JSON 文件读取凭据。

    文件格式::

        {
          "refs": {
            "bilibili": {
              "kind": "cookie",
              "value": "SESSDATA=...",
              "domain": ".bilibili.com",
              "expires_at": "2026-12-31"
            }
          }
        }
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def _load_refs(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        refs = payload.get("refs")
        if not isinstance(refs, dict):
            return {}
        return {
            str(key): value
            for key, value in refs.items()
            if isinstance(value, dict)
        }

    def resolve(self, ref_id: str) -> CredentialValue | None:
        normalized = _normalize_ref_id(ref_id)
        entry = self._load_refs().get(normalized)
        if entry is None:
            return None
        value = str(entry.get("value", ""))
        if not value:
            return None
        kind = str(entry.get("kind", KIND_COOKIE)).strip().lower()
        if kind not in SUPPORTED_KINDS:
            kind = KIND_COOKIE
        return CredentialValue(
            ref_id=normalized,
            kind=kind,
            value=value,
            domain=str(entry.get("domain", "")),
            expires_at=str(entry.get("expires_at", "")),
        )

    def refs(self) -> list[CredentialRef]:
        refs: list[CredentialRef] = []
        for ref_id in self._load_refs():
            resolved = self.resolve(ref_id)
            if resolved is not None:
                refs.append(_ref_from_value(resolved, source="file"))
        return refs


def _ref_from_value(value: CredentialValue, *, source: str) -> CredentialRef:
    return CredentialRef(
        ref_id=value.ref_id,
        kind=value.kind,
        source=source,
        domain=value.domain,
        masked_preview=_masked_preview(value.value),
        expires_at=value.expires_at,
    )


def build_credential_store(
    config: object,
    *,
    env_prefix: str = "WUWA_CREDENTIAL_",
) -> CredentialStore:
    """按配置构造凭据存储。

    配置了 ``wuwa_credentials_file`` 时优先文件存储，否则回退到
    环境变量存储（两者都存在时文件优先，便于本地调试）。
    """
    file_path = str(getattr(config, "wuwa_credentials_file", "")).strip()
    if file_path:
        return FileCredentialStore(file_path)
    return EnvCredentialStore(prefix=env_prefix)


def resolve_credential(
    store: CredentialStore,
    ref_id: str,
) -> CredentialValue:
    """解析凭据；不存在时抛出 ``CredentialMissingError``。"""
    value = store.resolve(ref_id)
    if value is None:
        raise CredentialMissingError(
            f"credential ref not found: {ref_id!r}"
        )
    return value


def build_credential_headers(
    store: CredentialStore,
    ref_id: str,
    *,
    header_name: str = "",
) -> dict[str, str]:
    """把凭据引用转成 HTTP 头（仅在 fetch 边界调用）。

    默认映射：cookie -> ``Cookie``，api_key/oauth -> ``Authorization:
    Bearer ...``。需要其他头名时用 ``header_name`` 覆盖。
    """
    value = resolve_credential(store, ref_id)
    if header_name:
        return {header_name: value.value}
    if value.kind == KIND_COOKIE:
        return {"Cookie": value.value}
    return {"Authorization": f"Bearer {value.value}"}
