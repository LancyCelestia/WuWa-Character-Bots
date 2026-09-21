# v21r5 CAMPUS-TESTHARD 席工作日志（按 U17-REVIEW-3 弱点清单强化 campus 测试）

> 席位：CAMPUS-TESTHARD。范围：**只改 `tests/test_campus_digest.py`（追加 ⑥ 节，既有 31 例断言零触碰）+ 本 log**，生产代码零改动。
> 依据：`docs/design/v21r5-U17REVIEW-log.md` 攻击面⑦逐例弱点（M2/M3/M4）+ 移交清单 #5 + 席位简报四条。
> 纪律：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`；pytest `--basetemp=$TEMP/campusth-* -p no:cacheprovider`；
> 禁 git 写/子代理/真实发送/重启/.env 读值；未 commit。全程无 1302/平台故障，零中断。

## 一、基线（强化前）

```
$ python -m pytest tests/test_campus_digest.py -q --basetemp=$TEMP/campusth-baseline -p no:cacheprovider
31 passed in 3.81s
```

弱点存在性 grep 实证（强化前测试文件自检）：
- `plain_text|platform|adapter|raw_segments` 仅出现于负锁例的 GROUP 哑元构造（:761-768）与告警例回执断言（:1053-1054）——**campus builder 产物对这四字段零断言**（M2 坐实）；
- `route_kind_hint` **零引用**（registry capability 提示未钉）；
- 除 `_NoSubmitQueue` 炸锁与 config 校验 `pytest.raises` 外，**零 raising 依赖注入**（M4 坐实）；
- dispatch 断言 `call["entry"] in {"handle","handle_async"}`（M3 坐实，:536）。

## 二、变异探针实录（全部测试空间，生产代码零触碰；探针脚本在 %TEMP 已清）

- **P1（M3 + registry）**：mutant entry='handle' → 旧谓词 `in {"handle","handle_async"}`=True（弱点真实）、新谓词 `=="handle_async"`=False（有牙）；
  registry 真值 `route_kind_hint='campus'`；mutant `route_kind_hint='chat'` → 既有四断言（location/matcher_type/priority/note）全绿=弱点真实，新断言 `=='campus'`=False（有牙）。
- **P2（M2）**：真 builder 产物（长文 3000 字）：`plain_text==body`(1501)、`plain_text!=text`、`platform='nonebot'`、`adapter='onebot.v11'`、`raw_segments==[{"type":"text","data":{"text":body}}]`；
  含密形态：secret 在 `payload.text`、不在 `plain_text`；变异体 `plain_text=payload.text` → 新断言 False（有牙）。
- **P4（I1 边界）**：五边界样本（教室门禁密码…/monkey=12345678/password 政策…/系统 token 明天轮换/keyboard…）全部 `identity=True + reviewer_clean=[]`；
  对照组：`password=abcd1234efgh → 'password=<已隐藏>'`（identity=False）、`token=abcd1234efgh → 打码且 reviewer 拦`——样本族非恒真。
- **P5（移交 #5①）**：token= 打码后真管线 → `state='blocked' transport='reviewer' queued=0`（真 reviewer 拦截面实锤）。
- **P6（M4）**：真吞异常在场（store.prune 炸）→ record() 仍出载荷（录库转发不丢）；
  变异体（吞异常移除）→ record() `RuntimeError(prune exploded)`（有牙）；未处理 raiser 经 `asyncio.run` 必外抛（handler 面 escape=测试失败即牙）。

## 三、逐条弱点 → 强化 → 锁定（tests/test_campus_digest.py ⑥ 节 :1067 起，11 新例）

| # | 弱点（U17REVIEW ⑦/移交） | 探针 | 强化（新增例） | 锁定证据 |
|---|---|---|---|---|
| 1 | M3：dispatch entry 弱断言；registry 条目 capability 提示未钉 | P1 | `test_handler_dispatch_entry_pinned_to_handle_async`（:1089，钉死 handle_async）+ `test_outbound_registry_campus_entry_capability_hint_pinned`（:1073，route_kind_hint=='campus'） | 42 全绿；mutant 双向有牙 |
| 2 | M2：builder plain_text/platform/adapter/raw_segments 零钉；SendRequest adapter/bot_id 零钉 | P2 | `test_forward_message_pins_platform_fields_and_verbatim_plain_text`（:1103，长文截断面+含密打码面双样本）+ `test_forward_request_carries_adapter_and_bot_semantics`（:1142，request.adapter=='onebot.v11'/bot_id==push_bot_id） | 42 全绿；plain_text==body 变异体被抓 |
| 3 | M4：handler/服务吞异常路径零测试 | P6 | `test_record_survives_prune_failure`（:1238，_PruneBrokenStore 注入）+ `test_handler_survives_get_plaintext_failure`（:1259）+ `test_handler_survives_pipeline_failure_and_keeps_recording`（:1270，录库仍成功）+ `test_handler_survives_alert_delivery_failure`（:1293，notify 炸不反噬监听） | 42 全绿；真吞异常在场=主流程不丢、变异体=当场炸 |
| 4 | I1 打码边界：敏感词「字样」非密钥「形态」的恒等样本缺失 | P4 | `test_forward_body_identity_for_secret_word_shapes_without_key_form`（:1345，3 边界样本恒等+reviewer 干净+对照组有牙） | 42 全绿；恒等/打码分界双向锁死 |
| 5 | 移交 #5①②：review-BLOCK 真管线版 / 暂停 BLOCK 永久丢失语义零测试 | P5 | `test_real_pipeline_blocks_stem_shaped_body_with_zero_enqueue`（:1170，真 reviewer BLOCK+零入队）+ `test_runtime_pause_blocks_forward_and_message_is_unrecoverable`（:1200，BLOCKED/policy/「统一运行时已暂停。」+零入队+同 id 重放 record()=None=不可恢复） | 42 全绿 |

### 简报与现场事实的两处偏差（诚实记录）

1. **简报第 1 条「registry 条目断言仅查坐标」**：现场既有坐标棘轮例 `test_outbound_registry_campus_coordinate_is_live` 已断言 note（U17-CAMPUS-WIRE/中央管线）与 priority=8——note/priority 非缺口；真缺口=capability 提示 `route_kind_hint`，已补钉（表 #1）。U17REVIEW ⑦ 的 M3 原文指 dispatch entry 弱断言，已同条钉死。
2. **简报第 4 条「无哨兵形态打码恒等」**：主锁已在既有 oracle 三方互证例 `test_forward_text_matches_legacy_bypass_verbatim`（record() 产物==纯格式化 oracle，含哨兵文本即不相等）——按简报**引用不重写**；本席只补「含敏感词字样但非密钥形态」边界样本（表 #4）。

## 四、终态门禁与卫生

```
$ python -m pytest tests/test_campus_digest.py -q --basetemp=$TEMP/campusth-final -p no:cacheprovider
42 passed in 3.61s        # 既有 31（断言零触碰）+ 新增 11
$ python -m ruff check tests/test_campus_digest.py
All checks passed!
```

- **mypy 说明**：canonical typecheck 门（dev.ps1 `-Task typecheck`）实读= `mypy --explicit-package-bases --ignore-missing-imports plugins`——**tests/ 在门外**（与历批「mypy Success」相容）。单文件 scoped mypy 对本文件共 51 条发现，全部为既有 `_source()`/`_payload()` SimpleNamespace 夹具的 arg-type 同款模式（既有行 :61/:82-94/:438/:510/:561/:641/:717-718/:773/:780-781/:816-817/:841-847/:886/:915 等早在席前）；本席新增 9 条（:1122/:1135/:1159-1160/:1191-1192/:1219-1220/:1245）**全部同款、零新错误类**，符合文件既有夹具约定，未越权改夹具。
- **树卫生**：`find plugins tests -name __pycache__ -o -name .pytest_cache -o -name *.pyc` 零命中；qx.json 完好（weather/assets 新家）；探针脚本只在 %TEMP 且已清。
- **写面核对**（git status 只读）：本席唯一写面=`tests/test_campus_digest.py`（波次内 untracked，追加 ⑥ 节）+ `docs/design/v21r5-CAMPUSTH-log.md`；`domains/assistant/campus/campus.py` 的 M 态与 capabilities/campus.py 等 untracked 均为 U17 波次既有在树状态（本席对生产文件只读）。
- **测试 harness 事实（非生产 bug，记档供后席）**：`_campus_handler_env` 默认不注入 `logging`，而 handler 管线失败 except 分支引用模块级 `logging`（生产恒可用；AST 提取命名空间须显式注入）——M4③ 例内已显式注入并注释。
- **真 bug 上报**：无。四条吞异常路径生产行为全部正确（吞而不丢主流程）。

**CAMPUSTH-SEAT DONE** — 2026-09-20，CAMPUS-TESTHARD（唯一写面=tests/test_campus_digest.py ⑥ 节 + 本 log；生产代码零改动；42/42 全绿实跑）。
