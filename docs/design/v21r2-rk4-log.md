# v21r2 · RK4 重跑席日志（§1 风险 4 收口）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 2026-09-18。前任静默死亡零落盘，本席从零做。纪律：禁 git 写、禁派代理、不碰 Runtime、.env 不读、personas 只读。
> 解释器：`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`；
> env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r2-rk4b -p no:cacheprovider`；禁 dev.ps1。
> 占域声明：control_plane/_app.py + factory.py + api/platform.py 注入面 + tests/test_v21_risk_red_cp_app.py。
> 避让在飞：RWOC（domains/core+ops 迁移+decision/alerts/error_report/contracts 垫片）、S14b（domains/ops 三子包新建）、WIREb（chat_reply/capabilities/chat.py+persona_service）——涉及只读。

## 风险 4 原始条目（v21-risk-red-report.md）

四项缺陷：
1. `_app.py` 局部 `from .factory import _path` 只在 events 分支 → actions/platform 块无条件使用 → 未配 events_db 默认装配 UnboundLocalError，独立启动入口死亡。
2. （与风险 1 叠加）`include_router(build_platform_router(...))` 触发 FastAPIError → 任何配置装配必炸。
3. config 注入缺口：`build_platform_router` 未传 `config`/`log_level_setter` → `/api/v1/media/analyze` 恒 503 media_config_unavailable。
4. RuntimePorts/queue 注入缺口：`getattr(app.state, "send_queue", None)` 全仓无人装配；工厂无 queue/ports 形参；"RuntimePorts" 全包零命中 → queue.pause/resume/drain 生产恒 degraded。
5. runtime_attached 冻结：`napcat.status` 返回 `connected=bool(runtime_attached)` 装配期标量不探测真实连接；同款冻结值喂 ProcessLogCollector 与 ResourceMetricsService。

对应 RED 测试（tests/test_v21_risk_red_cp_app.py，xfail strict）：
- test_risk4_default_app_creation_survives_without_events_db
- test_risk4_app_creation_survives_with_events_db
- test_risk4_queue_runtime_ports_injectable
- test_risk4_napcat_status_reflects_live_runtime

## 坐标重定位（2026-09-18 rg 实测，迁移波后）

| 项 | 原坐标（报告） | 现坐标（rg 实测） | 初步状态 |
|---|---|---|---|
| _path 局部 import | _app.py:324 events 分支局部 | `_app.py:27` 已模块级 `from .factory import _path, build_feature_service`；消费点 :325/:424/:464 | 疑似已被并行席修复，待复现裁决 |
| platform 路由注册崩（风险1叠加） | _app.py:469-478 → control_plane/platform.py | 路由已迁 `control_plane/api/platform.py`（A12 假成功修复席批，cp_platform 9 条转正）；_app.py:466-469 换装 | 待复现裁决（属风险 1 面，本席只验不抢修） |
| config/log_level_setter 缺口 | _app.py:469-478 未传 | _app.py:469 build_platform_router(...) 实参待读 | 待复现裁决 |
| send_queue/RuntimePorts | _app.py:393 getattr(app.state,"send_queue")；工厂无形参 | _app.py:392 同款仍在；工厂签名待读 | 待复现裁决 |
| runtime_attached 冻结 | _app.py:409-416 + :334-340 + :357 | _app.py:208 形参/:412 connected=bool(runtime_attached)/:504 传 ResourceMetricsService | 待复现裁决 |

## 计划（systematic-debugging 四阶段逐项）

1. 基线实跑 `tests/test_v21_risk_red_cp_app.py`（-rxX 看每条 xfail/xpass 真实态）→ 逐项复现或证伪。
2. 逐项裁决→最小修复：注入面补齐（禁全局单例直连新增）；runtime_attached 改真实状态查询（注入探针，不直连）。
3. 误报/已被他席修复→如实记录证据，不硬修、不越域。
4. 每项完成即落盘本日志；测试转正/补回归；涉线域存量回归不红。
5. 结束前 COORDINATION.md 追加一行。

## 四列状态（implementation / production_wiring / offline_validation / live_validation）

| 项 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| A _path 装配地雷+平台注册崩 | done(high)（他席 A12/S9 批，本席取证结案） | done（他席） | done(high)（2 装配测试转正常驻+本席复跑） | unknown（真机装配随下次重启观察） |
| B config/log_level_setter 注入 | done(high)（_app.py 传 config+_apply_platform_log_level） | done(high)（工厂内，无独立装配位） | done(high)（media/analyze 200 fake-text+setter 双向断言） | unknown |
| C send_queue 注入 | done(high)（工厂增形参+app.state 装配） | done(high)（__init__.py make_control_plane_app 传 ：3451 实例） | done(high)（签名断言+注入可达 handler+无注入诚实 degraded） | unknown（生产 queue.* 动作真效待重启后 WebUI 实测） |
| D runtime_state_probe 真实态 | done(high)（napcat.status 只信探针现查，三态：not_configured/probe_error/runtime_probe） | done(high)（生产传 `_select_credential_bot(_all_online_bots()) is not None`） | done(high)（attached+无探针=False 不谎报/probe True/False/抛异常三例） | unknown（真机 NapCat 连接/断开翻转待重启后观察） |
| 相邻缺陷（消毒层阻断动作明细） | not_wired（本席不越权，xfail(strict) 台账在案） | not_wired | done（xfail 实跑确认失败原因=白名单丢布尔/未知键） | unknown |

## §2 实跑证据汇总（2026-09-18）

1. 基线（修前）：`pytest tests/test_v21_risk_red_cp_app.py -rxX` → **2 passed, 2 xfailed**
   （A 项两条已被他席转正；C/D 两条 xfail 在案）。
2. D 项真实失败点复现（--runxfail）：execute succeeded 但 `result.details == {}`
   → 暴露消毒层第二层缺陷（详见 §1「D 项复现补充发现」）。
3. 修后本文件：**10 passed, 1 xfailed**（1 xfail=相邻缺陷台账位，strict 钉死）。
   覆盖：装配生存×2（转正）、queue 签名+注入可达+无注入诚实 degraded×3、
   napcat 探针三态（无探针不谎报/True/False/抛异常 fail-open）×3、
   media/analyze config 注入 200+setter 双向×2、消毒层 xfail×1。
4. 控制面族存量回归 15 文件：**197 passed, 1 xfailed**（m1/actions/v1/services/
   resources/host_guard/log_collectors/workspaces/runtime_feature_gate/
   risk_red_cp_platform/risk_red_cp_app/s9_llm/s9_workspace/persona_service_v21/
   creation_skeleton）。Duplicate Operation ID 告警=S9 席台账在案存量。
5. 静态门：ruff 三触达文件 All checks passed（--fix 自收 1×I001）；mypy
   `_app.py` 0 新增（api/platform.py:79/:254 两错=A12 既有台账 #36 基线，本席未触该文件）。
6. 插件导入冒烟：nonebot.init + `import plugins.bot_unified_runtime` OK；
   `inspect.signature(create_control_plane_app)` 实证 15 参含 `send_queue`/
   `runtime_state_probe`。
7. 树卫生：control_plane/ 与测试文件零 pycache/.pytest_cache；源码树无 data/ 残留。

## §3 改动清单（本席全部改动，未 commit）

| 文件 | 改动 |
|---|---|
| `plugins/bot_unified_runtime/control_plane/_app.py` | ① `Callable` 导入；② 工厂签名增 `send_queue`/`runtime_state_probe` 两 keyword-only 形参+docstring 注入面说明；③ `app.state.send_queue = send_queue`；④ napcat.status 改探针三态（None→False+probe_not_configured；异常→degraded+probe_error；正常→bool(probe())+runtime_probe）；⑤ build_platform_router 增传 `config`/`log_level_setter`；⑥ 模块级 `_PLATFORM_LOG_LEVELS`+`_apply_platform_log_level` |
| `plugins/bot_unified_runtime/__init__.py` | make_control_plane_app（:3586 区）增两实参：`send_queue=send_queue`、`runtime_state_probe=lambda: _select_credential_bot(_all_online_bots()) is not None`（参数注入，零全局单例直连新增） |
| `tests/test_v21_risk_red_cp_app.py` | 重写：2 条装配测试保留转正态；C 项签名测试转正；新增 queue 注入可达/无注入诚实 degraded、napcat 探针三态×3、media config 注入、log_level_setter 双向共 8 例；原 D 项栈级断言改钉 handler 层（原断言被消毒层阻断不可达，见 §1 裁决）+新增消毒层 xfail(strict) 台账位 |
| `docs/design/v21r2-rk4-log.md` | 本日志（新建） |

## §4 遗留与移交

1. **相邻缺陷（建议立项 P2）**：动作结果明细被 `_safe_details` 事件白名单消毒阻断
   （布尔值一律丢弃+未知键整体摈弃）→ WebUI 永远看不到 queue.*/napcat.status/
   diagnostics.snapshot 的结果细节。修法候选：动作域专用消毒（动作注册表键面固定
   可枚举）或 DETAIL_KEYS 扩面+布尔标量支持；属控制面事件面安全设计变更，
   本席不越权，xfail(strict) 已钉死 `tests/test_v21_risk_red_cp_app.py::test_risk4_action_details_survive_to_client`。
2. RuntimePorts 束概念未引入（最小改动裁决，见 §1 C 项）；未来动作面扩到
   5+ 注入对象时再议束化。
3. live_validation 全列 unknown：生产接线（send_queue 实例+探针）重启后生效；
   真机验收建议=重启 bot → NapCat 连接态翻转时经控制面查 napcat.status
   （配合遗留 1 修复后明细才可见，当前仅 state ok/degraded 可辨）。
4. `serve()` 独立入口（`python -m ...control_plane`）：A 项地雷拆除后已可默认装配
   生存（test_risk4_default_app_creation_survives_without_events_db 常驻回归锁）。

---

## §1 逐项记录

### 基线实跑（2026-09-18）

```
pytest tests/test_v21_risk_red_cp_app.py -rxX
→ 2 passed, 2 xfailed
```
- test_risk4_default_app_creation_survives_without_events_db **passed**（已转正，无 xfail 标记）
- test_risk4_app_creation_survives_with_events_db **passed**（同上）
- test_risk4_queue_runtime_ports_injectable **xfail**（在案）
- test_risk4_napcat_status_reflects_live_runtime **xfail**（在案）

### A 项（_path 局部 import + platform 注册崩）——已修复结案（他席，非本席改动）

证据：
- `_app.py:27` `from .factory import _path, build_feature_service` 模块级导入；消费点 :325/:424/:464 全在导入作用域内，UnboundLocalError 不可能再发生。
- platform 路由已迁 `control_plane/api/platform.py`（A12 假成功修复席批）：处理器闭包捕获 kind/action、principal 一律 `Depends`（api/platform.py:46-48 注释、:87/:99/:105），风险 1 的 FastAPIError 注册崩已消。
- 两条装配测试已被并行席转正且实跑通过（上基线）。
裁决：**误报结案（已被他席修复）**，本席零改动。

### D 项复现补充发现（2026-09-18，--runxfail 实跑）

test_risk4_napcat_status_reflects_live_runtime 真实失败点 ≠ 报告所述：execute 成功
（state=succeeded, status=ok）但 `result.details == {}`——`connected` 键**根本没透出**。
根因链第二层：`actions.py:238-239` 把动作结果 details 塞进 `RuntimeLogEvent` →
`events.py:_safe_details`（:111-156）白名单 `DETAIL_KEYS = _ID_KEYS|_NUMBER_KEYS|{"summary"}`
只放行已知键，且标量分支（:134-152）**布尔值一律丢弃**（bool 既非 int/float 也非 str）。
→ 全部默认动作（napcat.status/queue.*/diagnostics.snapshot/runtime.reload/logging.level）
的细节到不了客户端。测试附加注 `runtime_attached=True` 还经 `_build(**extra)` 误入
config 而非工厂形参（原 RED 测试自身路由缺陷），工厂恒 False——即原测试当前连
「冻结标量谎报」路径都没走到，失败纯因 details 被消毒。

**裁决（相邻缺陷不擅改）**：`_safe_details` 是安全设计的消毒白名单（「任意 URL/路径/
凭证/异常正文永不持久化」），扩面=控制面事件面设计变更，超出本席「注入面+冻结标量」
授权 → **如实报告不移项**，建议立项（P2）：动作结果明细需动作域专用消毒或白名单扩面
（connected/queue/state/execution 等 + 布尔标量支持）。本席测试改钉 handler 层语义。

### B 项（config/log_level_setter 注入缺口）——确认在案，修复

证据：`_app.py:468-477` build_platform_router 实参仅 store/两 dependency/prefix；
api/platform.py:387-388 `config is None → 503 media_config_unavailable`。
app 层有完整 config（:219 settings 即从 config 构建）→ 缺口属实。
修法：传入 `config=config` + `log_level_setter=_apply_platform_log_level`
（模块级新函数：根 logger setLevel，非五标准级返回 False=平台路由诚实 applied:false，
对齐 :152-168 契约与 _default_action logging.level 既有语义）。

### C 项（send_queue/RuntimePorts 注入缺口）——确认在案，修复

证据：工厂签名（_app.py:196-211）13 参无 queue/ports；`app.state.send_queue` 仅
:392 getattr 读取、全仓无人赋值 → queue.pause/resume/drain 恒 degraded
（:404-407 send_queue_not_connected）。生产装配点 `__init__.py:3586-3591`
make_control_plane_app 未传任何队列。
修法：工厂增 `send_queue: Any | None = None` 形参 + `app.state.send_queue = send_queue`；
生产装配传 `send_queue=send_queue`（:3451 已构造实例，闭包引用在 on_startup 调用时
已赋值——lifecycle.py:215 证实 app_factory 挂 driver.on_startup）。**参数注入，
无新增全局单例直连**。RuntimePorts 束概念不引入（最小改动；测试只要求可注入形参，
束属过度设计，登记备查）。

### D 项（runtime_attached 冻结）——确认在案，修复（handler 层）

证据：_app.py:408-415 `connected=bool(runtime_attached)` 装配期标量；
生产 :3590 硬编码 runtime_attached=True → 恒谎报已连接（哪怕 NapCat 离线）。
修法：工厂增 `runtime_state_probe: Callable[[], bool] | None = None`；
napcat.status 改真探测：probe None → connected=False source=probe_not_configured
（诚实不装）；probe 异常 → degraded connected=False source=probe_error（fail-open）；
probe 正常 → connected=bool(probe()) source=runtime_probe。生产传
`lambda: _select_credential_bot(_all_online_bots()) is not None`（在线 OneBot 账号真查询）。
**同款冻结值另两消费点裁决为非谎报、不修**：
- resources.py:54 `runtime_attached → process_role=bot_host/control_plane_host`——进程角色
  标签=装配期事实（app 是否装配在 bot 宿主进程内），非连接声明；
- api/v1.py:65 `runtime_binding: live/storage_only`——同上，绑定形态非连接态；
- _app.py:333 `if runtime_attached:` 进程日志采集器装配门——结构性装配决定，非状态谎报。

