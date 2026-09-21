# V21-AFFINITY-002 历史误扣重放与具名补偿（AFF 席）执行日志

- 席位：AFF（backend V2.1 验收矩阵 V21-AFFINITY-002）；日期 2026-09-18。
- 合同：旧新 policy 差额证据；无证据不猜，补偿不重复；补偿只出提案绝不自动落库；不得无证据恢复 40 分（用户原始裁定）。
- 硬约束遵守：零 git 写、零子代理、ChatBot_Runtime 生产好感度库全程只读（SQLite `mode=ro` + 实跑前后 SHA-256 一致实证）、不读 .env 明文、personas/ 未触碰、affinity.py 本体零改动（重放引擎独立成件）。
- 解释器直跑：`ChatBot_Runtime/venv/Scripts/python.exe`，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=$TEMP/v21r2-aff -p no:cacheprovider`；禁 dev.ps1。

## 一、接手探明（事实基础，全部实跑取证）

1. **坐标**：计分本体= `plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py`（RWC3 后 canonical；`character/affinity.py` 为 PEP 562 垫片）。新 policy 判定层=`score_relationship_signal`（七类非关系 reason_code 零计分 + refusal 行为语义）；`_BEHAVIOR_DELTA` 数值 v21.1 未改，改的是判定。
2. **逐事件账只有一张**：`affinity_delta_log`（sender_id/bot_id/applied_at/delta/source/source_event_id），V2.1 §2.3 滚动预算落地时随建，>48h prune，**不存行为分类/安全评估输入**。旧路径 `runtime/event_store.py`、`domains/ops/monitor/event_service.py` 与好感度无关（rg 实证）。
3. **生产库实况（只读查询，2026-09-18 06:18）**：195 用户；delta_log 27 行，窗口 `2026-09-17T05:56:37Z→17:39:04Z`（预算时代首日）；负向 14 行（最小 -0.01 内部值 = 预算钳后 -1 分）；source 分布 26×`''`+1×`poke`。**误扣事故时代（≤09-17 白天）的逐事件记录物理缺失**——账本表本身就诞生于预算批次。
4. **聚合计数是事故唯一残迹**（只读实证）：sender 3865067623 insult_count=10、last_insult_at=`2026-09-16T14:53:25Z`（grok 路由测试夜窗口吻合）、当前 -31.6 分、「口无遮拦」标打标同刻；另有 33 户零星 insult/negative 计数。聚合计数≠逐事件证据 → 按合同只能作审查指针，不得换算补偿。
5. **误扣机制量化**：旧 policy（pre-v21.1）refuse→insult = -10 分/条且无预算钳制；新 policy refusal→0。一晚 40+ 分 = 4 条 refuse × 10 分的机制复现（政策差额层已可精确重算）。

## 二、交付物（全部新文件，零触碰他席文件域）

| 文件 | 内容 |
|---|---|
| `plugins/bot_unified_runtime/domains/chat_reply/affinity_replay.py` | 重放引擎（只读）：①政策差额层——`old_policy_behavior`（refuse→insult 历史重建，余支委托现行实现）+`event_policy_diff`（差额=新−旧，正=多扣）；②账本重放层——`open_readonly_connection`（mode=ro 唯一入库方式）+`load_ledger_events`+`replay_ledger`（已验证 source 族→逐事件旧判/新判/差额；source 空→unknown 三字段全 None 不猜）+`load_counter_evidence`（具名聚合指针，标注不构成补偿依据）；③补偿提案层——`build_compensation_proposals`（只聚合已证 over_deducted，unknown/零差额结构性排除）+`compensation_fingerprint`（SHA-256 事件集指纹）+known_fingerprints 幂等去重；④`build_text_report`（人读报告：逐事件清单/聚合指针/提案/手工规程）。 |
| `scripts/affinity_replay_report.py` | 脚本化入口：`--dry` 显式声明（唯一模式）；`--stdout` 只打印；默认读生产库（runtime_paths 解析 data/user_affinity.sqlite3）出报告到 `docs/design/v21r2-aff-replay-report.md`+维护指纹登记表 `docs/design/v21r2-aff-compensation-registry.json`（原子写，只写 docs/ 登记表）。**不存在 --apply**（argparse 天然拒未知开关；报告 §四 写明管理员手工步骤）。 |
| `tests/test_v21_affinity_replay.py` | 20 例全离线 tmp_path：refuse 旧扣新零差额 10 分/条、非关系 reason_code 同理（provider_error 旧 +2 新 0 → 差额 -2 绝不倒扣）、allow 零差额、分口径换算漂移锁、poke 族零差额、source 空 unknown、只读连接写必拒（OperationalError 实证）、全流程跑完库字节哈希不变、缺表明确报错、提案聚合/指纹稳定/重复不重计/unknown 结构性排除、真实 DynamicAffinityStore 落库形态兼容、报告诚实口径断言。 |

## 三、实跑证据（全部本席直跑）

```
$ pytest tests/test_v21_affinity_replay.py --basetemp=$TEMP/v21r2-aff -p no:cacheprovider -q
20 passed in 1.87s                                   （首跑即绿）

$ pytest tests/test_affinity.py … test_affinity_v21_signal.py tests/test_v21_affinity_replay.py tests/test_poke_v2.py … -q
130 passed in 11.33s                                 （affinity 存量回归 9 文件，零红）

$ python scripts/affinity_replay_report.py --dry --stdout     （×1 预览）
[replay] 事件 27 条：零差额 1 / 已证多扣 0 / 无证据 unknown 26；新提案 0 项、重复 0 项

$ python scripts/affinity_replay_report.py --dry              （×3 落盘，确定性复现）
[report] 已写入 …\docs\design\v21r2-aff-replay-report.md
[registry] 无新提案，登记表未变动

生产库 SHA-256：89f0c7b9547dc7b3…（脚本实跑前后逐一比对，不变——只读保证实证）

$ ruff check <三文件>        → All checks passed!
$ mypy --explicit-package-bases --ignore-missing-imports <三文件>
→ 仅 control_plane/api/platform.py 既有 2 错（他席域，AGENTS.md 台账已记）；本席 3 文件零命中
```

生产实跑结论（写入报告 `docs/design/v21r2-aff-replay-report.md`）：当前账本内**零已证误扣**（26 条 source 空全部如实 unknown，1 条 poke 已证零差额）→ **零提案**；40+ 分事故逐事件证据物理缺失，报告以 sender 3865067623（insult_count=10、末次 2026-09-16T14:53:25Z、现 -31.6 分）等聚合指针供管理员人工核查，未恢复一分（合同红线遵守）。

## 四、验收矩阵 V21-AFFINITY-002 四列状态（本席口径）

| 行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-AFFINITY-002 | unknown→**implemented**（重放引擎+提案器+脚本入口三件套，只读零落库路径，指纹幂等） | **not_applicable**（管理员手工工具，无运行时装配面；脚本已可直接对生产库执行） | unknown→**passed**（新 20 例+affinity 存量回归 130 passed 全离线） | **passed**（只读对生产库实跑×4、库哈希不变、报告落盘；补偿落库属管理员手工步骤=按设计不适用） |

## 五、遗留（列明不隐匿）

1. **补偿落库永远是手工**：引擎/脚本无 apply 路径是设计而非缺口；管理员按报告 §四 操作（停机窗口+内部值÷100+两法副作用已写明）。
2. **unknown 事件的人工转正**：管理员若从聊天记录独立确认某条 unknown 属 refuse 误判，可按报告规程处置并在登记表补人工条目；引擎不代猜。
3. **未来证据形态**：V2.1 事件服务（AffinityEvent 全表）上线后，把新事件族的旧/新判定核实后登记进 `SOURCE_FAMILIES`，逐事件重放即自动覆盖——白名单机制防「无证据不猜」被绕过。
4. 聚合计数不衰减：insult_count 永不自动清零（仅标签按半衰淡出），聚合指针表会长期列出历史计数，属库内既有语义，本席未改。
5. 报告中 poke 行差额显示 `+0.0`（零差额符号格式），纯展示瑕疵，不影响判定。

## 六、纪律声明

- 零 commit/零 push、零生产写入（mode=ro+哈希不变双实证）、零 .env 读取、零 personas 改动、零子代理；`affinity.py` 本体与 `__init__.py` 零触碰；工作树改动=本席三新文件+两份报告/登记文档（登记表因零提案未创建）。
- 树卫生：全跑 `PYTHONDONTWRITEBYTECODE=1`；过程中 mypy/ruff 在根目录产生 `.mypy_cache`/`.ruff_cache` 已删除复核（06:22:13 再现一次——本席 06:20 后未再调 ruff/mypy，命令集不含缓存写入方，判为并发席位工具产物，再次删除并登记；再入勿记本席账）；无 `data/`、`__pycache__` 残留；qx.json 未触碰。
