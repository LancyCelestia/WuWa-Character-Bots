# V2.1 好感度修复席（A4）执行日志

- 席位：A4 好感度修复（backend V2.1）；工作区 `ChatBot\ChatBot`；日期 2026-09-17。
- 规格依据：`docs/design/backend-v2-product-extensions.md` §2.1-§2.3；风险事实源 `findings.md`。
- 硬约束遵守：禁 git 写、禁子代理、不读 `.env` 明文、不触碰生产库/Runtime；全部测试 tmp_path 离线。
- 解释器：`../ChatBot_Runtime/venv/Scripts/python.exe`，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，`--basetemp=%TEMP%\v21-affinity* -p no:cacheprovider`。

## 0. 接手现状（工作树在途工作盘点）

接手时工作树已有前一轮在途改动（未提交、无本席日志）：

| 项 | 状态 | 证据 |
|---|---|---|
| ① refuse→insult 解耦（新行为 `refusal`，delta=0） | 已在树 | `character/affinity.py::classify_behavior` L383-388 |
| 多因素乘积钳制 [0.5,1.25]（§2.3 factor_product） | 已在树 | `affinity.py` `_FACTOR_PRODUCT_MIN/MAX` + `effective_delta` L301 |
| 基础滚动预算（单事件1分/6h2分/24h4分/增益3分，时间窗聚合、重启跨午夜不重置） | 已在树 | `affinity.py` `_clamp_delta_to_rolling_budget` + `affinity_delta_log` 表 |
| `observe_points` 分值适配器（÷100）+ poke 来源专项 24h 预算 | 已在树 | `affinity.py` L600-629 |
| poke 接线走 points 口径（调用点在 `__init__.py::_record_poke_affinity`，非 poke.py） | 已在树 | `__init__.py` L4645-4677（observe_points + source_cap_24h_points=daily_max） |
| `tests/test_affinity_v21.py`（①②③④⑤ 已锁） | 已在树 | 77 passed 基线 |

**本轮补齐缺口（规格 §2.2/§2.3 剩余条款）**：⑥source_event_id 事务内幂等、⑦interaction_cooldown 60s、⑧预算按 (principal_id, bot_id) 汇总、⑨passive_decay 默认 false（政策门）、⑩poke 增益默认 0.1 分/24h≤0.5 分、⑪6h≤24h 常量校验、⑫normalize_legacy_points 具名唯一适配器 + points 边界钳制。

## 1. RED（检查点 1，先失败后实现）

新增 `tests/test_affinity_v21_budget.py`（17 例，全部 tmp_path+注入时钟，零网络零生产库）。

命令与实跑输出：

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_affinity_v21_budget.py --basetemp=%TEMP%\v21-affinity-red -p no:cacheprovider -q
E   ImportError: cannot import name '_INTERACTION_COOLDOWN_SECONDS' from 'plugins.bot_unified_runtime.character.affinity'
1 error in 1.81s
```

RED 形态说明：收集期 ImportError 即契约缺口实锤（`_INTERACTION_COOLDOWN_SECONDS`/`_PASSIVE_DECAY_ENABLED`/`normalize_legacy_points` 均不存在；幂等/bot_id/points 钳制/校验器行为无处挂靠）。基线（改动前存量回归）：

```
$ python -m pytest tests/test_affinity.py tests/test_affinity_numerical.py tests/test_affinity_query.py tests/test_affinity_tag_fade.py tests/test_affinity_v21.py tests/test_poke_v2.py --basetemp=%TEMP%\v21-affinity-baseline -p no:cacheprovider -q
77 passed in 8.01s
```

（检查点 1 落盘，继续实现。）

## 2. 续跑席接手判定（2026-09-17，A4 续跑）

接手实态：检查点 1（RED）已落盘；检查点 3/4 实现已在树且首跑即 GREEN（`test_affinity_v21_budget.py + test_affinity_v21.py` 34 passed，`$TEMP\v21-affinity-green0`）；检查点 2 只完成 `refuse→refusal` 解耦，规格 §2.2 的 reason_code 族承接面缺失。poke.py 复核零好感度引用（接线在 `__init__._record_poke_affinity` L4640-4684，observe_points + source_cap_24h_points=daily_max，config `bot_poke_affinity_delta=0.1/daily_max=0.5` 已注册 config.py:600-602，catalog 门禁 4 passed 无漂移）；`bot_affinity_db_path` 走 `build_runtime_data_path` 重映射，delta 日志同库继承。**不重做已完成部分**。

## 3. 检查点 2 收口：score_relationship_signal 服务边界（RED→GREEN）

新增 `tests/test_affinity_v21_signal.py`（16 例：7 非关系 reason_code 注册面锁定、reason_code 优先于正文启发式、引用辱骂/产品批评/授权测试保 neutral、未知 reason_code→uncertain_reason_code、无码时委托 classify_behavior 语义原样、落库分毫不动+计数不增）。

RED 实跑：

```
$ ... python.exe -m pytest tests/test_affinity_v21_signal.py --basetemp=%TEMP%\v21-affinity-red2 -p no:cacheprovider -q
E   ImportError: cannot import name '_NON_RELATIONSHIP_REASON_CODES' from 'plugins.bot_unified_runtime.character.affinity'
1 error in 1.37s
```

实现（`character/affinity.py`）：`_NON_RELATIONSHIP_REASON_CODES`（refusal/provider_error/format_error/medical_question/quoted_abuse/product_criticism/authorized_test 七族）+ `_UNCERTAIN_REASON_CODE` + `_ABUSE_SAFETY_CATEGORIES` + `score_relationship_signal(text, *, safety_category, safety_action, reason_code) -> (behavior, reason_code)`——非关系码零计分且优先于正文启发式；未知码=不确定一律 neutral；对人直接类别证据是负事件唯一准入（direct_abuse_evidence）；正文自述不取得 authorized_test（防伪造测试身份）。另在 `_BEHAVIOR_DELTA` 补 policy_revision=v21.1 注记（§2.3 score_signal 表值 0.2/0/-0.3/-1.0 分 vs v5 冲突 → 本席合同裁定 v5 语义保留、量级由单事件 1 分/24h 增益 3 分预算兜底同量级）。

GREEN 实跑（三波合并）：

```
$ ... -m pytest tests/test_affinity_v21_signal.py tests/test_affinity_v21_budget.py tests/test_affinity_v21.py --basetemp=%TEMP%\v21-affinity-green1 -p no:cacheprovider -q
50 passed in 5.19s
```

## 4. 静态门与全量回归（最终实跑）

- ruff（改动 4 文件直跑）：修上一实例遗留 3 处（test_affinity_v21_budget.py I001 导入序/F401 未用 time/F841 未用 db——测试卫生修正，无断言语义变化）后 **All checks passed**。
- mypy（项目同参 `--explicit-package-bases --ignore-missing-imports plugins`，314 文件）：80 errors 集中于 control_plane/api/platform.py、runtime/schedule_*×4、supervisor/*_windows×3 共 8 文件（并行批在途域）；**character/affinity.py 及本席全部文件零命中**，非本席回归。
- 全量 affinity/poke 回归（8 文件，`$TEMP\v21-affinity-final2`）：**110 passed in 8.08s**（= 接手基线 77 + 预算波 17 + 信号波 16）。

## 5. 遗留项（列明不隐匿）

1. **§2.4 smoothstep 档位插值+防抖**（阈值 ±2 分插值、进出高档 ±2 分滞回）：未做，属本席合同明列遗留。
2. **补偿重放**（S12：propose/apply_compensation、replay_affinity_events、AffinityEvent 全表、preview_affinity_event/remaining_budget/build_affinity_style）：未做；历史误扣 40+ 分的补偿等管理员授权重放，本席不读生产库不擅自恢复。
3. **生产接线一行迁移**：`__init__.py::_passive_affinity_perception`（L6776）现直调 classify_behavior；score_relationship_signal 上线需把该调用换成新边界（__init__.py 不在本席文件域，未动）；provider_error/format_error 等码的生产产出口在上游 LLM 链路，尚未发出——本席交付的是分类承接面+测试锁。
4. mypy 全树 80 errors（8 文件）待各在途域自行收口；poke.py 无需改动（零好感度引用）。
