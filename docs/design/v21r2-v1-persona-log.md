# v21r2 V1 席（S7 人格/世界观/世界书版本管理 + Persona 假成功修复）过程日志

> 席位：V1（S7）。开工 2026-09-17 晚。前任零落盘阵亡，本席从零开始，过程即写本页。
> 文件域：`control_plane/platform.py` persona 段、新建 `character/persona_service.py`、
> 新建 `character/worldbook_service.py`、新建 `tests/test_persona_service_v21.py`、
> `docs/db-owners.md` 追加段。personas/ 只读；chat.py 禁触（RP 席在飞）。

## 0. 现状取证（开工即跑，实跑证据）

- `tests/test_v21_risk_red_cp_platform.py` 实跑：**9 passed in 2.25s**（BOT_AUTOSYNC=0，
  `--basetemp=%TEMP%/v21r2-v1b -p no:cacheprovider`）。
- 结论：briefing 所述「风险 3 的 2 条 strict xfail」**已不存在**——A12 假成功修复席已将
  风险 1/2/3 共 9 条全部转正（测试文件 docstring 第 4-5 行有记录），当前全绿。
  V21-UPDATE-LOG.md §四「风险 3 未修复」的口径已被 A12 的在飞改动超前（该日志页未同步）。
- 对照本席任务验收逐条复核 A12 遗留缺口：
  1. publish 真实落版本：`apply_lifecycle` 已落 active/published_at + `store.put` 真实版本号 ✅；
     **哈希快照缺失**（platform.py 全文无 sha256）→ 本席补。
  2. rebuild 幽灵 job：`register_job` 已落可查登记（status=unavailable/reason=executor_not_wired），
     `/jobs/{id}` 可查，非幽灵 ✅（test_risk3_rebuild_job_is_queryable 覆盖）。
  3. setter 假 applied：未装配 setter 时已如实报 `applied=False + reason` ✅；
     但 setter 抛 TypeError/ValueError 才失败——setter 返回 False（明确自报失败）时仍假 applied
     → 本席补「setter 自报失败必须如实上报」。
- S7 地基（persona_service 等价实现）：`rg -l "persona_service|PersonaService|PersonaVersion"`
  在 plugins/ tests/ **零命中** → 无等价实现，可新建。`character/persona_set.py` 是备选人格
  选择器（PersonaSelector，无生命周期），不冲突不复用其存储。

## 1. 设计决定（S7 地基）

- 合同来源：guide §9「draft→validated→published→active 指针；正式版本不可变；rollback 创建
  新版本；仅超管发布人格；hash 损坏隔离并回到已验证版本，不能抹证据」+ 验收矩阵
  V21-PERSONA-001 / V21-WORLD-001。
- 存储：新库 `data/persona_versions.sqlite3` + `data/worldbook_versions.sqlite3`
  （无独立配置键，经 `scripts/runtime_paths.runtime_path` 解析——memory_v21.sqlite3 先例），
  表前缀 persona_* / worldbook_*；**不可变触发器**（BEFORE UPDATE/DELETE RAISE ABORT）
  结构性锁死正式版本；quarantine 表留损坏证据（不抹证据）。
- 权限：draft=admin+，publish/activate/rollback=super_admin（只读 import policy/roles 常量）。
- 注入防护：核心人格内容只从 persona_versions（已发布+哈希复核）经 `build_core_injection`
  出口读出，带 (resource_id, version, sha256 前缀) 溯源；服务无任何「直接写 active 内容」的 API。

## 2. 交付清单（随做随记）

- [x] 现状取证 + 缺口定性（本页 §0）
- [x] platform.py publish 哈希快照 + setter 自报失败如实上报
  - `PlatformService.content_digest/verify_resource`（快照取版本史最新哈希——旁路篡改连当前数据一起改也检得出）；`apply_lifecycle` publish/activate 落 `content_sha256`
  - `api/platform.py` log_level：setter 返回 False → `applied=False + reason=setter_reported_failure`（向后兼容：不返回值仍视为成功；该文件属 A12 修复面，改动最小化并在此声明）
- [x] `character/persona_service.py`：PersonaService（draft/publish/activate/rollback/load_active/build_core_injection）+ VersionedResourceStore（prefix 参数化，persona/worldbook 共用）
  - 不可变触发器（UPDATE/DELETE RAISE ABORT）、CAS expected_version（BEGIN IMMEDIATE 内比对+插入，竞态 IntegrityError→显式 version_conflict）、损坏隔离（拒载+quarantine 留证+告警+回退最近完好版本，全损→PersonaStoreUnavailable 拒注入）、权限门（draft=admin+；publish/activate/rollback=super_admin，`_publish_role` 可覆写供 worldbook 放宽）、注入唯一出口（channel=persona_core，带 version+sha256 溯源）
- [x] `character/worldbook_service.py`：WorldbookService 复用同一内核（WorldbookLifecycle 子类，publish_role=admin），发布前校验：结构 shape/悬空引用（own published ∪ external_ids 注入）/循环引用（worldbook→worldbook DFS 含自引用）/Token 预算（CJK≈1/字+其他/4 粗估，默认 8192）；失败不产生版本；build_injection 出站带 untrusted 标注与来源
- [x] tests/test_persona_service_v21.py（19 例：生命周期/回滚/CAS×2/损坏隔离×3/权限门/触发器/worldbook×5/platform 补口×4）
- [x] docs/db-owners.md 二节追加 persona_versions.sqlite3 + worldbook_versions.sqlite3 两行
- [x] 独立冒烟（%TEMP%/v21_v1_smoke.py，绕过包 __init__ 直载模块）：**SMOKE OK**——冒烟抓出并修复两处真缺陷：①activate/rollback 硬编码 super_admin 与 worldbook admin 生命周期不一致（改 `_publish_role`）；②损坏模拟须先摘不可变触发器（等价越 SQL 层真损坏），顺带证明触发器对 raw 连接同样 ABORT

## 3. 实跑记录（只有真跑才填）

- 开工取证：`pytest tests/test_v21_risk_red_cp_platform.py` → **9 passed**（风险 1/2/3 已由 A12 转正，非本席 xfail 存量）
- 本席改动后回归：`pytest tests/test_v21_risk_red_cp_platform.py tests/test_v21_risk_red_cp_app.py` → **11 passed, 2 xfailed**（2 xfail=风险 5 Dispatcher 按设计保持 RED，非本域）
- 冒烟：`python %TEMP%/v21_v1_smoke.py` → **SMOKE OK**（persona 全链+CAS+权限+损坏隔离+触发器；worldbook 悬空/预算/环）
- **环境阻断（已自愈）**：W1b reorg 席迁 sources/→domains/ 期间 `cookies` 垫片星号导入丢 `_resolve_relative_cookie_path`（ImportError）→ 其后 `chat.py→sources.transcribe`（ModuleNotFoundError），包 `__init__` 执行必经此链，全树一度不可导入。所涉文件全在本席禁区，未动；退避轮询后 W1b 收敛，导入恢复。期间以独立冒烟（%TEMP%/v21_v1_smoke.py，绕包 `__init__` 直载模块）先行验证逻辑并抓出两处真缺陷提前修复（见 §2 冒烟条目）。

## 3.1 最终门禁实跑（全绿收官）

```
pytest tests/test_persona_service_v21.py
  → 19 passed in 4.78s
pytest tests/test_v21_risk_red_cp_platform.py tests/test_v21_risk_red_cp_app.py \
       tests/test_v21_risk_red_dispatch_and_telegram.py tests/test_v21_risk_red_tz_and_files.py \
       tests/test_control_plane_v1.py tests/test_control_plane_resources.py \
       tests/test_control_plane_m1.py tests/test_control_plane_services.py
  → 74 passed, 5 xfailed in 30.97s   （5 xfail=风险5 Dispatcher 按设计保持 RED，非本域）
pytest tests/test_persona_service_v21.py tests/test_v21_risk_red_cp_platform.py \
       tests/test_v21_risk_red_cp_app.py
  → 30 passed, 2 xfailed in 8.81s    （lint/typecheck 修复后复跑）
pytest tests/test_control_plane_{actions,actions_api,events,host_guard,lifecycle,
       log_collectors,metrics,sandbox,workspaces,workspaces_api}.py \
       tests/test_persona_{prompt_and_memory,source_sync}.py
  → 234 passed in 32.28s             （控制面存量回归+既有 persona 测试零破坏）
ruff check（本席 5 文件）           → All checks passed!
mypy --explicit-package-bases --ignore-missing-imports（本席 3 源文件）
  → 剩 2 错均 control_plane/api/platform.py:79/:254 既有（AGENTS 台账 #36 已登记，
    A12 的工厂注解面，非本席引入）；worldbook_service 本席 3 错已清零
```

## 4. 四列状态（记本席日志，共享矩阵禁改）

| 验收行 | 代码实现 | 测试 | 真机验收 |
| --- | --- | --- | --- |
| V21-PERSONA-001（人格草稿/发布/激活/回滚+CAS+快照hash+损坏回退） | **done（本席地基）**：character/persona_service.py 全链+不可变触发器+权限门+注入唯一出口；PromptBroker 装配与 chat 链注入接线属后续席位（chat.py 本席禁触） | done：19 例离线全绿（含 CAS 冲突/损坏隔离/权限门/触发器不可变/并发单赢家） | unknown（零生产接线，装配席落码后按 acceptance-manual 补真机项） |
| V21-WORLD-001（World/Worldbook/Reference 版本及预算引用） | **done（最小切片）**：character/worldbook_service.py 版本化+悬空/循环引用校验+Token 预算；跨库 external_ids 注入面已留；world/persona 资源同构复用同一内核（表前缀隔离） | done：5 例离线全绿（悬空/预算/环/结构/往返） | unknown（同上） |

## 5. 遗留与移交

1. **装配面（后续席位）**：build_persona_service/build_worldbook_service 零生产接线——
   需装配席把 personas/ 同步产物灌入 draft→publish（本模块绝不反向写 personas/），
   并把 chat 链人格注入切到 build_core_injection（chat.py 属 RP/SEARCH 域，本席禁触）。
2. **权限模型**：本服务角色以 list[str] 直传（draft=admin+/发布=super_admin），
   与控制面 Principal/RequestContext 的对接属 S2/S9 主体面，未做。
3. **跨库环检测边界**：worldbook→worldbook 环已拦；经 external_ids 的跨库环
   （如 worldbook↔reference 分库互指）本切片不可达，已在 docstring 声明。
4. **他席在飞残留（非本席）**：character/media_registry.py:2 RUF100（unused noqa，
   media 域 RW11 面）；api/platform.py:79/:254 mypy 2 错既有（A12 面，台账 #36）。
5. **平台哈希快照**：verify_resource 供控制面/装配席复核用；GET 路由未暴露
   verify 端点（避免与 A12 已转正测试面冲突），需要时在 api 层补一行只读路由。
