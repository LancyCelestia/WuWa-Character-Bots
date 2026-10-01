"""HTTP 无关的配置控制服务；CAS 持久化不等同于资源已安全 reload。

公开读项保留 legacy value/source 等字段。只有 SETTABLE_KEYS 可变更；
RESTART_REQUIRED_KEYS 仅可读。本层拒绝越权/过期写，底层审计失败则整笔回滚。
写面（set/reset/reset_all）自 S-G2-THROAT（2026-09-26，用户裁定「K-1：修」）
起全部裹进 `domains/core/safety_exec/settings_gate.py::guarded_write` 这一
唯一裁决点：R1/R2 无书面同意不落库、R3 直接拒；门未装配或总闸关时与接线前
逐字节同形。
"""
from __future__ import annotations

import builtins
import json
import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)

from .auth import Principal
from .config_store import (
    ConfigSnapshot,
    ConfigVersionConflict,
    SQLiteConfigStateStore,
    normalize_key,
    public_value,
    redact_public_data,
    validate_version,
)
from .services import ControlServiceError


class ConfigControlService:
    def __init__(self, config: object, backend: SQLiteConfigStateStore, *,
                 runtime_settings: RuntimeSettingsStore | None = None) -> None:
        self.config = config
        if runtime_settings is not None:
            runtime_settings.attach_config_backend(backend)
            attached = runtime_settings.config_backend
            assert attached is not None
            backend = attached  # 同文件的另一个对象也统一到运行时监听绑定的对象。
        self.backend = backend
        # 同意门的句柄只能经 runtime_settings 拿（见 _consent_gate：裸
        # SQLiteConfigStateStore 对 RuntimeConfigBackend 的鸭子类型结构性不
        # 兼容）。生产两个装配口（_app.py / runtime_admin.py）都传 store。
        self._runtime_settings = runtime_settings
        self._gate_lock = threading.Lock()

    def _key(self, key: str, *, writable: bool = False) -> str:
        try:
            return normalize_key(key, writable=writable)
        except KeyError:
            raise ControlServiceError("config_not_found", "未找到对应配置键。", 404) from None
        except (ValueError, AttributeError, TypeError):
            raise ControlServiceError("config_not_hot_reloadable", "该配置尚无安全热更新路径，请修改 .env 并重启。", 409) from None

    def _snapshot(self) -> ConfigSnapshot:
        try:
            return self.backend.snapshot()
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置存储暂不可用。", 503) from None

    def _row(self, key: str, snapshot: ConfigSnapshot) -> dict[str, Any]:
        # 冻结键即便留有历史覆盖，也不能假称它已作用于当前资源。
        overridden = key in snapshot.overrides and key not in RESTART_REQUIRED_KEYS
        value = snapshot.overrides[key] if overridden else getattr(self.config, key.lower(), None)
        return {"key": key, **public_value(key, value),
                "source": "runtime_override" if overridden else "config",
                "state": "override" if overridden else "default", "version": snapshot.version,
                "hot_reload": key in SETTABLE_KEYS and key not in RESTART_REQUIRED_KEYS,
                "restart_required": key in RESTART_REQUIRED_KEYS,
                "description": redact_public_data(RESTART_REQUIRED_KEYS.get(key, "运行时白名单参数"))}

    def schema(self) -> builtins.list[dict[str, Any]]:
        return self.list()

    def list(self) -> builtins.list[dict[str, Any]]:
        snapshot = self._snapshot()
        return [self._row(key, snapshot) for key in sorted(set(SETTABLE_KEYS) | set(RESTART_REQUIRED_KEYS))]

    def get(self, key: str) -> dict[str, Any]:
        return self._row(self._key(key), self._snapshot())

    def _authorize(self, principal: Principal, expected_version: int, request_id: str) -> None:
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "此操作需要 super_admin 权限。", 403)
        try:
            validate_version(expected_version)
        except ValueError:
            raise ControlServiceError("invalid_version", "必须提供非负整数 expected_version。", 422) from None
        if not isinstance(request_id, str) or not isinstance(principal.subject, str) or not principal.subject.strip():
            raise ControlServiceError("config_invalid", "审计主体及请求标识无效。", 422)

    def _convert(self, key: str, value: Any) -> Any:
        try:
            if value is None:
                raise ValueError("清除覆盖请使用 reset")
            if isinstance(value, str):
                raw = value.strip()
            elif isinstance(value, list) and key in {
                "BOT_QUIET_HOURS_SESSION_TYPES", "BOT_QUIET_HOURS_BYPASS_ROLES",
            }:
                # 两个 legacy converter 接收分隔文本，而非 JSON 数组字符串。
                if not all(isinstance(item, str) for item in value):
                    raise ValueError("列表项必须为字符串")
                raw = ",".join(value)
            else:
                raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
            converted = SETTABLE_KEYS[key](raw)
            json.dumps(converted, allow_nan=False)
            return converted
        except (ValueError, TypeError, OverflowError):
            # converter 的异常可能包含原始 secret，不把 cause 暴露到 DTO。
            raise ControlServiceError("config_invalid", "配置值未通过校验。", 422) from None

    def preview(self, key: str, value: Any = None, *, principal: Principal,
                expected_version: int, reset: bool = False, request_id: str = "") -> dict[str, Any]:
        self._authorize(principal, expected_version, request_id)
        key = self._key(key, writable=True)
        if type(reset) is not bool:
            raise ControlServiceError("config_invalid", "reset 必须为布尔值。", 422)
        snapshot = self._snapshot()
        if snapshot.version != expected_version:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409)
        overrides = dict(snapshot.overrides)
        if reset:
            overrides.pop(key, None)
        else:
            overrides[key] = self._convert(key, value)
        return {**self._row(key, ConfigSnapshot(snapshot.version, overrides, snapshot.tombstones)), "preview": True}

    def _consent_gate(self) -> Any | None:
        """拿与咽喉**同一枚**书面同意门；返回 None＝无可装配的咽喉宿主（放行）。

        三条现算事实（本方法只消费，不新造第二种判定）：
        - 裁决体唯一住 `settings_gate.guarded_write`，构造点唯一走
          `build_gate_for_store(store, config)`；store 必须是挂着这本配置库的
          `RuntimeSettingsStore`——它的 `config_backend` 属性决定同意账落点与
          咽喉侧的 `SqliteSafetyLedger` 是**同一个库文件**，而一次性凭证 `_grants`
          是门对象上的进程内字典，两枚各造各的门则「会话里批过 → 控制面重试」
          永远接不上，所以经 `safety_gate` 属性读／`attach_safety_gate()` 复用同一枚。
        - 裸 `SQLiteConfigStateStore` 不满足 `RuntimeConfigBackend` 的鸭子类型
          （缺 `list_overrides()`，且它的 `reset_override` 把 `expected_version`
          做成必填）——硬接成门＝「看起来接了但一调就炸」，故无 store 形态返回
          None、保持接线前逐字节行为（该形态只出现在单测直接构造；生产装配口
          恒传 store）。
        - `bot.consent` 命令面的 gate_provider 现读 `store.safety_gate`，attach
          之后它与本服务看到的是同一枚门：卡可见、可批、重试可消费。
        """
        store = self._runtime_settings
        if store is None:
            return None
        gate = store.safety_gate  # property（不是方法）：与 bot.consent 的现读口径同一取法
        if gate is not None:
            return gate
        with self._gate_lock:
            gate = store.safety_gate  # 双检：别的线程（含咽喉自己）刚建好就领用
            if gate is not None:
                return gate
            from plugins.bot_unified_runtime.domains.core.safety_exec import (
                settings_gate as _gate_mod,
            )

            gate = _gate_mod.build_gate_for_store(store, self.config)
            store.attach_safety_gate(gate)  # 契约见 settings.py：传入即视为已装配
            return gate

    def _guarded_apply(self, *, target: str, value: Any, restore_default: bool,
                       principal: Principal, request_id: str,
                       session_key: str = "",
                       apply: Callable[[], Any]) -> Any:
        """把一次实际落库动作交给门；门缺席或总闸关 ⇒ 直接 `apply()`，与接线前
        逐字节同形（`settings.py::_throat_guard` 的三态口径，本层不自创第四态）。

        出票/拒绝的异常翻成本层既有 `ControlServiceError` 形态：不吞成 500、
        工单号/短码/批准指引原文原样带出去（HTTP 面由 `_app.py` 的
        exception_handler 装进 envelope 的 error.message）。

        session_key 由调用方申报（需求 18②，席位 S-FILESAFE 2026-09-28 那一票的
        实现半片）：控制面自身没有入站会话，但**发起这一笔的人可能知道它该绑到哪
        个会话**（例如替某个群里的诉求重放改动）。这一格以前硬写空串，等于把「调用
        方其实知道会话」那一格也钉死，R1「在原会话里确认」（consent.py：
        `and row.source_session_key`）因此在控制面渠道整体退化成 R2 式跨会话批。
        现在它透传到门：空串＝该判据对这笔不启用（旧形态逐字节保持，未表过态的
        调用方一寸行为都没变）；填了会话＝批准必须真出现在那个会话里。**只收紧
        不放宽**——填错只会批不下来，不会多批；R2 的超管私聊书面亲批不受影响。
        """
        from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
            DenyKind,
        )
        from plugins.bot_unified_runtime.domains.core.safety_exec.settings_gate import (
            RuntimeChangeNeedsConsent,
            RuntimeChangeRefused,
        )

        gate = self._consent_gate()
        if gate is None or not gate.enabled:
            return apply()
        try:
            return gate.guarded_write(
                key=target, value=value, restore_default=restore_default,
                actor=principal.subject, request_id=request_id,
                session_key=session_key, apply=apply,
            )
        except RuntimeChangeNeedsConsent as exc:
            # 409 有 actions.py `confirmation_required` 的同状态码先例；原文直传。
            raise ControlServiceError("consent_required", exc.plain_text, 409) from None
        except RuntimeChangeRefused as exc:
            if exc.kind is DenyKind.NEVER_AUTO:
                status = 403  # R3：连批都不给，改 .env 重启是人的事
            elif exc.kind is DenyKind.AUDIT_UNAVAILABLE:
                status = 503  # 账落不下去 ⇒ 这笔没做，且存储面确实不可用
            else:
                status = 409
            raise ControlServiceError("change_refused", exc.plain_text, status) from None

    def _write(self, key: str, value: Any, *, reset: bool, principal: Principal,
               expected_version: int, request_id: str,
               session_key: str = "") -> dict[str, Any]:
        self._authorize(principal, expected_version, request_id)
        key = self._key(key, writable=True)
        converted = None if reset else self._convert(key, value)
        try:
            # S-G2-THROAT（K-1：修）：裸写落进 `_guarded_apply` 的 `apply=` 闭包。
            # 用 lambda 而非嵌套 def 是两把锁之间的在册契约：
            # `test_safety_exec_session_throat.py` 的直写名册按「最内层 def」归属，
            # 嵌套 def 会把坐标从 ("config_service.py","_write") 顶成 "_apply"、
            # 撞崩它的冻结核账；本席的 AST 活性锁
            # （tests/test_control_plane_consent_throat.py）则要求这个调用点
            # 必须住在 apply= 实参的子树里。两判据同绿＝既在册又活性。
            snapshot = self._guarded_apply(
                target=key, value=converted, restore_default=reset,
                principal=principal, request_id=request_id, session_key=session_key,
                apply=lambda: (
                    self.backend.reset_override(
                        key, expected_version=expected_version,
                        actor=principal.subject, request_id=request_id,
                    ) if reset else self.backend.set_override(
                        key, converted, expected_version=expected_version,
                        actor=principal.subject, request_id=request_id,
                    )
                ),
            )
        except ConfigVersionConflict:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置未保存，存储暂不可用。", 503) from None
        return self._row(key, snapshot)

    def set(self, key: str, value: Any, *, principal: Principal, expected_version: int,
            request_id: str = "", session_key: str = "") -> dict[str, Any]:
        """写一笔覆盖；`session_key` 是调用方对来源会话的申报（见 `_guarded_apply`），
        省缺空串＝不申报＝旧形态。"""
        return self._write(key, value, reset=False, principal=principal,
                           expected_version=expected_version, request_id=request_id,
                           session_key=session_key)

    def reset(self, key: str, *, principal: Principal, expected_version: int,
              request_id: str = "", session_key: str = "") -> dict[str, Any]:
        """撤一笔覆盖；会话申报口径同 `set`。"""
        return self._write(key, None, reset=True, principal=principal,
                           expected_version=expected_version, request_id=request_id,
                           session_key=session_key)

    def reset_all(self, *, principal: Principal, expected_version: int,
                  request_id: str = "") -> dict[str, int]:
        """一次 CAS 清空覆盖；count 来自同一版本快照，不逐键提交。

        过门口径（S-G2-THROAT，与咽喉同形）：全撤没有单键可分级，走门侧聚合
        目标 `ALL_OVERRIDES_TARGET`（未登记目标按缺省档 ⇒ R2 书面同意）整批判
        一次，而**不是**逐键判 tier 再逐键落——本方法的原子性就来自「一次 CAS、
        一份快照计数」（docstring 原话），逐键出票等于把一键清空变成 N 张卡 +
        N 次批准 + 部分生效，语义直接走样；`RuntimeSettingsStore.reset_override
        (None)` 走 `_throat_guard(target=None)` 用的就是同一个聚合名，两本判据
        合一，不留第二套规则。

        会话面同口径：聚合目标没有「这一笔属于哪个会话」可言，故本方法**不吃**
        `session_key`（`_guarded_apply` 缺省空串＝同会话判据对整批不启用）。要它
        也能 R1 得另开一票，并同批改 `test_control_plane_consent_throat.py` 的名册。
        """
        self._authorize(principal, expected_version, request_id)
        before = self._snapshot()
        if before.version != expected_version:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409)
        for key in before.overrides:
            self._key(key, writable=True)  # 仅预校验；历史冻结键也不假称热改。
        from plugins.bot_unified_runtime.domains.core.safety_exec import (
            settings_gate as _gate_mod,
        )

        try:
            after = self._guarded_apply(
                target=_gate_mod.ALL_OVERRIDES_TARGET, value=None, restore_default=True,
                principal=principal, request_id=request_id,
                apply=lambda: self.backend.reset_override(
                    None, expected_version=expected_version,
                    actor=principal.subject, request_id=request_id,
                ),
            )
        except ConfigVersionConflict:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置未保存，存储暂不可用。", 503) from None
        return {"version": after.version, "reset_count": len(before.overrides)}

    def changes(self, *, since_version: int = 0, limit: int = 100) -> builtins.list[dict[str, Any]]:
        try:
            return self.backend.changes(since_version=since_version, limit=limit)
        except ValueError:
            raise ControlServiceError("config_invalid", "历史分页参数无效。", 422) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置历史暂不可用。", 503) from None
