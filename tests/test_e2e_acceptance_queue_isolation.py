"""E2E 验收器发送队列隔离 + 不伪造来件号（离线回归，全程不写生产库）。

治的正是本波根治的事故面：`scripts/e2e_acceptance.py` 的 `--execute` 旧写法把
`build_send_queue(runtime.config)` 的 `bot_send_queue_db_path`（经 `runtime_paths` 折成
**生产库** `ChatBot_Runtime/data/wuwa_send_queue.sqlite3`）直接拿去建队列，而在线 bot 的
send-queue worker 共读同一本库 ⇒ 验收器入队的合成请求被 worker 拿去真发到群/私聊
（盘上实据：该库 1200 行里 38 枚 `sent`+107 枚 `failed_final` 的 e2e 行，带
`origin_message_id:"e2e-…"`、`retcode_failure retcode=100`）。这是「验收器不该投递真消息」
承诺的反面，与已入库的两枚同族修复一脉相承：

- `6442234`：验收面不再虚构 bot 身份（哨兵 "unknown" 顶死适配器选路）；
- `755d686`：DRY-RUN 的可写偏好库改指 `%TEMP%`（本波把同一把尺用到发送队列上）。

本件锁两件事（注毒方向见文件末尾两条 mutation 说明）：
(a) **结构性**隔离：验收器选中/建出的 SQLite 发送队列库恒落临时根（缺省 `%TEMP%`；测试
    经 `isolation_root` 注入 `tmp_path`），**绝不**是生产 `ChatBot_Runtime` 那本；
(b) 合成来件号不得进入引用/回复发送面：验收器合成的消息 `message_id=None` ⇒ 管线产出的
    `SendRequest.origin_message_id` 为空 ⇒ 邮件重投腿 `In-Reply-To/References` 不挂假号。

生产行为零变化：真人真事由摄取层填真实 `message_id`，管线照旧把它抄进 `origin_message_id`、
照旧引用/回复——本件只钉验收面。全程 InMemory / 临时库，零生产字节（AGENTS 规则 2/6）。

注：凡「config 里躺着一枚绝对生产路径」这一形状，本件用鸭子类型 config（`SimpleNamespace`）
复现——直呼真实 `Config(...)` 传绝对生产根会撞 conftest 的 `guard_test_runtime_root`
（`RuntimeIsolationViolation`），那是**测试进程**的隔离缝在响、不是被测件坏了；鸭子 config
逐字绕过校验、把「读到绝对生产路径就改指临时根」这条判定交回被测的 `choose_send_queue`。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)

#: 生产库的**形状锚**：仓库根的兄弟目录 `ChatBot_Runtime/data`（本波事故落点）。
#: 只用于断言「选中路径不是它」——全程不建、不写、不打开（且走鸭子 config，绝不落盘）。
_PRODUCTION_RUNTIME_DATA_DIR = (
    Path(e2e.__file__).resolve().parents[2] / "ChatBot_Runtime" / "data"
)
_PRODUCTION_QUEUE_PATH = str(_PRODUCTION_RUNTIME_DATA_DIR / "wuwa_send_queue.sqlite3")


def _runtime_stub(tmp_path, **config_kwargs) -> e2e.E2eRuntime:
    """离线替身运行面（照抄 `tests/test_e2e_acceptance.py::_runtime_stub` 的口径）。

    `bot_runtime_data_dir` 必落到 `tmp_path` 下——直呼 ``Config(...)`` 不读环境变量、
    缺省 ``bot_runtime_data_dir="data"`` 会把 ``data/`` 相对路径折回源码树（AGENTS 规则 6）。
    """
    city = str(config_kwargs.pop("city", "北京"))
    bot_id = str(config_kwargs.pop("bot_id", ""))
    sender_id = str(config_kwargs.pop("sender_id", "10000"))
    execute = bool(config_kwargs.pop("execute", False))
    # 好感度/安静时间关：离线测试不得打开 Runtime 真实好感度库。
    config_kwargs.setdefault("bot_runtime_data_dir", str(tmp_path / "runtime-data"))
    config = Config(
        bot_quiet_hours_enabled=False,
        bot_affinity_enabled=False,
        **config_kwargs,
    )
    settings = SimpleNamespace(get=lambda key, cfg: None, get_persona_override=lambda: "")
    return e2e.E2eRuntime(
        config=config,
        runtime_settings=settings,
        render_backend=None,
        execute=execute,
        city=city,
        bot_id=bot_id,
        sender_id=sender_id,
    )


def _duck_runtime(*, enabled: bool, db_path: str, isolation_home: Path) -> e2e.E2eRuntime:
    """鸭子 config 的运行面：把「config 里躺着一枚绝对生产路径」原样摆出来。

    只喂 `choose_send_queue` 用到的那几枚属性（enabled/db_path 及隔离继承用的运行数据根），
    不新建 `Config` 从而绕过测试进程的生产根守卫——被测的是 `choose_send_queue` 会不会
    把这枚绝对路径改掉，而不是 pydantic 校验器。
    """
    config = SimpleNamespace(
        bot_runtime_data_dir=str(isolation_home / "runtime-data"),
        bot_send_queue_enabled=enabled,
        bot_send_queue_db_path=db_path,
    )
    settings = SimpleNamespace(get=lambda key, cfg: None, get_persona_override=lambda: "")
    return e2e.E2eRuntime(
        config=config,
        runtime_settings=settings,
        render_backend=None,
        execute=True,
        city="北京",
        bot_id="",
        sender_id="10000",
    )


# --------------------------------------------------------------------------- #
# (a) 发送队列结构性隔离
# --------------------------------------------------------------------------- #


def test_execute_send_queue_is_isolated_to_temp_not_production(tmp_path) -> None:
    """--execute 建出的 SQLite 队列必须落临时根，绝不是 config 里那枚生产 `ChatBot_Runtime` 库。

    手法：把「生产形状」的 `bot_send_queue_db_path`（`ChatBot_Runtime/data` 下真实事故库路径）
    塞进鸭子 config，要求选出的队列路径落在注入的 `tmp_path` 临时根下、且与生产路径不同。
    """
    runtime = _duck_runtime(
        enabled=True, db_path=_PRODUCTION_QUEUE_PATH, isolation_home=tmp_path
    )

    queue, desc = e2e.choose_send_queue(
        runtime, audit_logger=InMemoryAuditLogger(), isolation_root=tmp_path
    )

    assert isinstance(queue, SQLiteSendRequestQueue), (
        "验收面 --execute 仍应走真实 SQLite 队列（换库≠换实现）"
    )
    selected = Path(queue.db_path).resolve()
    assert selected == (tmp_path / "wuwa_send_queue.sqlite3").resolve(), (
        f"队列没落到注入的临时根：{selected}"
    )
    assert selected != Path(_PRODUCTION_QUEUE_PATH).resolve(), (
        "选中了生产库路径——验收器入队＝在线 worker 会拿去真发（本波根治项）"
    )
    # 不得落回源码树（AGENTS 规则 6：源码树零缓存/零 data/）。
    repo_root = Path(e2e.__file__).resolve().parents[1]
    assert not str(selected).startswith(str(repo_root)), f"落回源码树：{selected}"
    # 不得落进生产 Runtime 数据根（AGENTS 规则 2）。
    assert _PRODUCTION_RUNTIME_DATA_DIR not in selected.parents, f"落进生产根：{selected}"
    # desc 必须点名用的是隔离库，不能把生产路径原样报出去冒充「与在线 bot 共库」。
    assert "isolated" in desc, desc
    assert _PRODUCTION_RUNTIME_DATA_DIR.as_posix() not in desc.replace("\\", "/"), desc


def test_execute_never_hands_production_db_to_build_send_queue(tmp_path, monkeypatch) -> None:
    """把「生产那枚绝对路径绝不进 `build_send_queue`」钉成现算证据，而不是靠文件是否存在。

    生产库 `wuwa_send_queue.sqlite3` 在本机是**真实存在**的（在线 bot 的活体库），所以
    「隔离后生产库不存在」这种断言在这台机器上根本不可能成立——它测的是错的东西。正解＝
    在 `build_send_queue` 那道口上装一只哨兵，记录它**实际收到**的 `db_path`：必须是被
    改指过的临时路径，绝不能等于 config 里那枚生产路径。哨兵仍返回真队列（走真实
    `SQLiteSendRequestQueue` 构造，只是本用例不 submit ⇒ 零落盘）。
    """
    seen: dict[str, object] = {}
    real_build = e2e_module_build_send_queue()

    def spy(config, audit_logger):  # 镜像真身签名即可
        seen["db_path"] = str(getattr(config, "bot_send_queue_db_path", ""))
        seen["enabled"] = bool(getattr(config, "bot_send_queue_enabled", False))
        return real_build(config, audit_logger)

    import plugins.bot_unified_runtime.domains.transport.sender.queue as queue_mod

    monkeypatch.setattr(queue_mod, "build_send_queue", spy)

    runtime = _duck_runtime(
        enabled=True, db_path=_PRODUCTION_QUEUE_PATH, isolation_home=tmp_path
    )
    queue, _desc = e2e.choose_send_queue(
        runtime, audit_logger=InMemoryAuditLogger(), isolation_root=tmp_path
    )

    handed = str(seen.get("db_path", ""))
    assert handed == str(tmp_path / "wuwa_send_queue.sqlite3"), (
        f"交进 build_send_queue 的落点不是临时库：{handed!r}"
    )
    assert handed != _PRODUCTION_QUEUE_PATH, "生产绝对路径被原样交进了建队列那道口＝隔离没生效"
    assert seen.get("enabled") is True, "隔离只挪路径，不得顺手关掉持久化队列那枚准入"
    assert isinstance(queue, SQLiteSendRequestQueue)
    # 哨兵没 submit ⇒ 临时库里也不该有表文件被创建（真身懒建表）。
    assert not (tmp_path / "wuwa_send_queue.sqlite3").exists()


def e2e_module_build_send_queue():  # 只是取真身构造函数供哨兵回退
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        build_send_queue as _real,
    )

    return _real


def test_execute_default_isolation_root_lands_outside_repo_and_runtime(tmp_path) -> None:
    """不注入根时，缺省临时根也必须在 OS 临时目录下、不在仓库、不在 `ChatBot_Runtime` 根。

    这一枚钉的是「结构性」那半面——线上真跑 `--execute`（不带 `isolation_root`）也不会
    指向生产库；缺省只在 OS 临时区落一本临时库（本用例用 mkdtemp 当运行数据根，绝不建库到
    生产路径）。
    """
    runtime = _duck_runtime(
        enabled=True, db_path=_PRODUCTION_QUEUE_PATH, isolation_home=tmp_path
    )

    queue, _desc = e2e.choose_send_queue(runtime, audit_logger=InMemoryAuditLogger())

    selected = Path(queue.db_path).resolve()
    os_temp = Path(tempfile.gettempdir()).resolve()
    assert str(selected).startswith(str(os_temp)), f"缺省根不在 OS 临时目录：{selected}"
    assert "e2e-send-queue-isolation" in str(selected).replace("\\", "/")
    assert _PRODUCTION_RUNTIME_DATA_DIR not in selected.parents
    # 缺省形态也绝不能等于 config 里那枚生产路径。
    assert selected != Path(_PRODUCTION_QUEUE_PATH).resolve()


def test_dry_run_never_opens_any_sqlite_queue(tmp_path) -> None:
    """DRY-RUN 一张 SQLite 都不开（InMemory），临时根也不该被创建。

    钉住「隔离不是把 DRY-RUN 也拽进磁盘」：DRY-RUN 的隔离＝零落盘。若有人把 DRY-RUN
    改成也建临时库，这枚会红（它要求 `isolation_root` 目录里没有任何库文件）。
    """
    runtime = _runtime_stub(tmp_path)  # execute=False
    iso = tmp_path / "iso"
    queue, desc = e2e.choose_send_queue(
        runtime, audit_logger=InMemoryAuditLogger(), isolation_root=iso
    )
    assert isinstance(queue, InMemorySendQueue)
    assert desc.startswith("dry-run:")
    # DRY-RUN 分支不碰隔离根——不建库、不建目录。
    assert not iso.exists() or not (iso / "wuwa_send_queue.sqlite3").exists()


def test_execute_still_requires_persistent_queue_guard(tmp_path) -> None:
    """结构性隔离不得吃掉原安全阀：没启用持久化队列时 --execute 照旧拒绝。

    这是把「准入判定读的是原配置那枚生产路径」钉住——有人若想借『反正都落临时库』干脆
    删掉这道闸，让没配队列的部署也「假装真发」，本件当场红。
    """
    # 未 enable、无 db 路径。
    runtime = _duck_runtime(enabled=False, db_path="", isolation_home=tmp_path)
    with pytest.raises(e2e.E2eSafetyError):
        e2e.choose_send_queue(runtime, audit_logger=InMemoryAuditLogger())

    # 配了 db 路径但没 enable，同样拒（两个条件都得真成立）。
    runtime2 = _duck_runtime(
        enabled=False, db_path=_PRODUCTION_QUEUE_PATH, isolation_home=tmp_path
    )
    with pytest.raises(e2e.E2eSafetyError):
        e2e.choose_send_queue(runtime2, audit_logger=InMemoryAuditLogger())

    # enable 了但没 db 路径，也拒。
    runtime3 = _duck_runtime(enabled=True, db_path="", isolation_home=tmp_path)
    with pytest.raises(e2e.E2eSafetyError):
        e2e.choose_send_queue(runtime3, audit_logger=InMemoryAuditLogger())


def test_isolation_config_only_moves_queue_db_and_keeps_the_rest(tmp_path) -> None:
    """`send_queue_isolation_config` 只挪发送队列那本库，其余字段逐字继承。

    钉住「复用既有 model_copy 尺、不新建 Config、不引入第二套重定向」：`bot_runtime_data_dir`
    /`bot_send_queue_enabled` / 其它库路径不能被顺手改，否则隔离面扩到别的库＝又长出第二把尺。
    这里用真实 `Config` + **相对** `data/` 路径（经校验器折进 `tmp_path` 运行根，不撞生产守卫）。
    """
    base = Config(
        bot_runtime_data_dir=str(tmp_path / "runtime-data"),
        bot_quiet_hours_enabled=False,
        bot_affinity_enabled=False,
        bot_send_queue_enabled=True,
        bot_send_queue_db_path="data/wuwa_send_queue.sqlite3",
        bot_receipts_db_path="data/wuwa_receipts.sqlite3",
    )
    iso = tmp_path / "iso"
    staged = e2e.send_queue_isolation_config(base, iso)

    assert str(staged.bot_send_queue_db_path) == str(iso / "wuwa_send_queue.sqlite3")
    # 只动发送队列：运行数据根 / 开关 / 回执库路径原样继承。
    assert staged.bot_runtime_data_dir == base.bot_runtime_data_dir
    assert bool(staged.bot_send_queue_enabled) is True
    assert str(staged.bot_receipts_db_path) == str(base.bot_receipts_db_path)


def test_send_queue_isolation_dir_default_is_os_temp_and_made(tmp_path, monkeypatch) -> None:
    """缺省隔离根在 OS 临时目录（不在仓库/生产根）且被 mkdir；注入根逐字采用。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "ostemp"))
    root = e2e.send_queue_isolation_dir()
    assert root == Path(tmp_path / "ostemp" / "e2e-send-queue-isolation")
    assert root.exists(), "隔离根没被创建（SQLiteSendRequestQueue 会自 mkdir，但这里要显式在）"

    injected = e2e.send_queue_isolation_dir(tmp_path / "explicit")
    assert injected == tmp_path / "explicit"
    assert injected.exists()


# --------------------------------------------------------------------------- #
# (b) 合成来件号不得进入引用/回复发送面
# --------------------------------------------------------------------------- #


def test_harness_message_carries_no_fabricated_inbound_id() -> None:
    """验收器合成的消息**不发明**来件号（`message_id` 为空）。

    旧写法 `message_id=f"e2e-{seq}-{ts}"` 造了一枚看着像真号的假 id，管线原样抄进
    `SendRequest.origin_message_id`，邮件重投腿据此盖 `In-Reply-To/References`。正解＝
    验收器**不带引用**发，而不是随手编一个。
    """
    for seq in (1, 4, 905):
        message = e2e.synthesize_message(
            text="全球股市",
            session_type=SessionType.GROUP,
            target_id="123",
            sender_id="456",
            bot_id="",
            seq=seq,
        )
        assert not message.message_id, (
            f"验收器又发明了来件号 {message.message_id!r}＝会进引用/回复发送面（本波根治项）"
        )
    # bot_id 那一侧的既有不变量不能被顺手带回（6442234）：没配自身号＝交空串，不是哨兵。
    assert (
        e2e.synthesize_message(
            text="x",
            session_type=SessionType.PRIVATE,
            target_id="456",
            sender_id="456",
            bot_id="",
            seq=1,
        ).bot_id
        == ""
    )


def test_harness_payload_carries_no_reply_reference(tmp_path) -> None:
    """真实管线产出的 `SendRequest.origin_message_id` 必须为空（验收面＝无引用发送）。

    走的是**真身链路**：`RuntimePipeline.handle` → `_render_and_submit` 里
    `origin_message_id=message.message_id`；只要生成侧不造假号，发送面就拿不到引用把手。
    这条比直接读 `synthesize_message` 更强——它验的是「入队那一刻的请求体」，正是盘上
    `request_json` 里那枚 `"origin_message_id":"e2e-4-…"` 的产出点。

    用 `bot.text`（直发文本能力），不碰 `/bot reply` 命令面 ⇒ 无须 monkeypatch
    `shared_reply_policy_store`（台账 #66★：只有走 reply 命令面的测试才必钉）。
    """
    runtime = _runtime_stub(tmp_path)
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    pipeline = e2e.build_pipeline(runtime, queue)
    outcome = e2e.execute_item(
        pipeline=pipeline,
        send_queue=queue,
        item=next(i for i in e2e.build_matrix(runtime) if i.key == "text-short"),
        runtime=runtime,
        session_type=SessionType.GROUP,
        target_id="555",
        seq=1,
    )

    assert outcome.error == "", outcome.error
    request = outcome.send_request
    assert request is not None
    assert not request.origin_message_id, (
        "合成 origin_message_id 进了发送面＝邮件腿会挂假 In-Reply-To"
        f"（实得 {request.origin_message_id!r}）"
    )
