# v21r4-B RWC5-b 席日志——根 `__init__.py` 惰性导入续切收尾

- 席位：RWC5-b（2026-09-18 开工，断点续跑 v21r2 RWC5 挂账）；占域=根 `plugins/bot_unified_runtime/__init__.py`（独占写）。
- 前置取证：v21r2-reorg-wc5-log（前任已切 40 点=静态垫片惰性消费；保留 PEP562 活转发惰性点/真身未迁 14/模块级消费）；EP1 垫片退役清单 §3.1（108 张垫片退役前置=本席清账）；交接书 §6.1 RWC5 行。
- 协调表已认领；RET3（44 张仅测试消费垫片）与本席零交集；WIRE-SVC 服务装配段（:4124-4143）分毫不动。
- 纪律：固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp` 每次唯一 + `-p no:cacheprovider`；零 git 写操作；未 commit。

## 一、波前机核（AST 全量，%TEMP%/v21r4-rwc5b/ 五脚本）

1. 旧路径 import 点：**模块级 85 + 函数级 73**，涉 108 distinct 旧模块。
2. 目标形态：PEP562 活转发 62 + 静态 re-export 31 + RELAY 包 3（character/runtime/policy）+ TRUE_BODY 12（contracts/control_plane×4/policy.gate/security/config/audit 包/llm 包/loop_watchdog/service_wiring——旧路即唯一真路，保留）。
3. 使用面：123 个可切名中——**注解专用 6 名**（DiagnosticsStore/RuntimeDiagnostic/AdminTarget/RouteDecision/OneBotV11Bot/ReceiptRepository，mypy 词法约束不可函数内化）+ **零使用再导出 17 名**（_VIDEO_ACK_TEXT 等，测试经根属性读取：test_video_progress_ack.py:132 `runtime._VIDEO_ACK_TEXT` 实锤）→ 两类**模块级仅改路径**；其余 100 名 / 172 运行时使用点 / 35 函数可惰性化。
4. 耦合面（wc5 §3 红点法扩展）：根属性消费 46 名 ∩ 模块级旧路 import 名 = **空**；根模块对象式补丁 8 名全为根内定义符号；垫片对象式补丁 0；字符串式补丁 4（content_parser/http_util 不约束本席）。**结论：惰性化零测试耦合**。
5. 前置同一性：216 (canonical, name) 对运行时 import+getattr 全存在，与旧垫片 `is` 同一 **216/216 零分裂**。

## 二、切换方案（与 wc5 同构：函数内延迟 import / 纯路径切换；不发明新模式）

- 函数级旧路点 → canonical 路径原位替换（保惰性形态）。
- 模块级可惰性名 → 移除模块级绑定，各使用函数顶部插 canonical 函数内 import。
- 注解专用 + 零使用再导出 → 模块级仅改路径（保根属性面=零行为差）。
- TRUE_BODY（含 WIRE-SVC 的 service_wiring）→ 原样保留。

## 三、批次台账

（待填）

## 三、批次台账（实跑，全部 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1，pytest basetemp 每次唯一）

执行期间引擎三次取证迭代（幻影 B5 解析红=变换自检拦截未落盘；复因=清单混形态 occ 双计）。最终形态：**批内 claimed_now 防双编辑 + 新鲜扫描自然只列未切语句**，每批=语句重写（AST 定位+计数断言+批后 parse/模块级残留四重自检）+ 备份至 %TEMP%/v21r4-rwc5b/backup_bN.py。

| 批 | 内容 | 门 |
|---|---|---|
| B1（旧清单） | character.memory/memory_extract/chat/pricing/runtime 包/kb_wiki/ingress 惰性点 8 语句 | 冒烟 OK + 记忆族 75 passed |
| B2-B6（旧清单） | 惰性点续切 40 语句 | 每批冒烟 OK + 27/57/30/146 passed |
| 重建清单 R1-R6 | 模块级+惰性混合 48 语句 | 每批冒烟 OK + 31/26/124/120/27/64 passed |
| R7 | platform_credentials/runtime_admin/channel_health/model_schedule/usage_monitor/runtime_event_log/vision_describe 8 语句 | 冒烟 OK + 107 passed |
| R8 | affinity/campus/chat/content_parser/daily_assist/divination/download/eat 模块级 8 语句 | 冒烟 OK + 111 passed 1 skipped |
| R9 | 惰性点收尾 8 语句（echo/runtime_logs/affinity/emotion/content_route 等） | 冒烟 OK + 63 passed |

## 四、终态与终验（全部实跑）

1. **旧路径清账归零**：根 `__init__.py` 垫片形态（PEP562 62 + STATIC 31 + RELAY 中 character/runtime 包）消费边 **0 残余**；残留旧路径 import 22 点全为**真身未迁保留集**（contracts×8/control_plane×4/policy(+gate)×3/security/config/llm 包/audit 包/loop_watchdog/**runtime.service_wiring（WIRE-SVC 交付，分毫未动，:4149 实核完好）**）。EP1 退役清单 §3.1 的「子波 5 根 __init__ 清账先行」前置达成，108 张垫片退役解阻。
2. **惰性形态保持**：函数级惰性点全部 canonical 直连（与 wc5 40 点同构，纯路径变化零行为差）；模块级语句**保持模块级仅改路径**（见 §五裁定①）。
3. **导入冒烟**：`import bot; import plugins.bot_unified_runtime` OK（每批一次+终验复跑，累计 17 次绿）。
4. **test_v21 全族（38 文件）+ 提醒族 6 文件合跑：781 passed / 1 skipped / 0 failed**。
5. **源文本锚五件+关键耦合十件**（documentation_consistency/runtime_subfeatures/runtime_feature_gate/unified_delivery_routes/traditional_triggers_2 + production_wiring/cookie_hot_reload/video_seam/video_progress_ack/persona_injection_v21）：**154 passed / 0 failed**。
6. **ruff 本文件**：--fix 自愈 6 处 I001（块内排序，无语义变化，fix 后 parse+冒烟双复核）→ **All checks passed!**。
7. **mypy（scoped，--explicit-package-bases --ignore-missing-imports）**：根 `__init__.py` 本体 **0 error**（--follow-imports=silent 口径 Success）。
8. **command_catalog --check**：`command catalog is current (77 topics)` ✓。
9. **树卫生**：源码树无 __pycache__/*.pyc/.pytest_cache/.ruff_cache/data/ 新增；qx.json 未触碰。
10. 零 git 写操作；未 commit（提交裁决权在用户）；重启生效（装配文件，bot 进程须重启加载）。

## 五、设计裁定（如实登记，供波主复核）

1. **模块级语句保持模块级仅改路径（不做函数内惰性化）**：耦合面机核证明惰性化技术可行（100 名/172 点零测试耦合），但 ①注解专用 6 名（DiagnosticsStore/RuntimeDiagnostic/AdminTarget/RouteDecision/OneBotV11Bot/ReceiptRepository，mypy 词法作用域）与零使用再导出 17 名（test_video_progress_ack.py:132 经根属性读 `runtime._VIDEO_ACK_TEXT` 实锤）**必须**模块级，全惰性化必制造双态不一致；②模块级 canonical 直连与原模块级垫片导入**时序完全等价**（垫片 from-import 本就在导入期解析），零行为差；③EP1 退役前提只要求清除垫片消费边，与 eager/lazy 无关；④wc5 原范围即划走模块级（其 §5.2「归退役波」）。剩余 100 名的函数内化属启动时序优化非退役前提，连同已写好的插入机制（%TEMP%/v21r4-rwc5b/engine.py drop+insert 路径，未实弹）一并移交，需要时由波主裁决另立。
2. **RK5 移交项已完成**：原 ：1209/:1214（现 ：1213-1222 区域）两处 `"object" has no attribute ...` attr-defined——根因=参数 `settings_store` 类型 object 上直接调方法；修法=局部 `getattr` 绑定 + `callable()` 门内调用（语义等价，与函数内既有防御式风格同构）；scoped mypy 本文件 0 error。
3. **移交项（非本席域）**：`domains/chat_reply/llm_engine/model_router.py:439` `float(float|None)` arg-type——**既有潜伏错**（git diff 实证该文件工作树零改动=HEAD 已提交代码；此前被 `llm.model_router` 垫片 `__getattr__` 的 Any 不透明性遮蔽，本席改 canonical 直连后 mypy 跟入暴露）。归 chat_reply/llm_engine 属主，非本席可触文件。
4. 执行中 B7 曾两次被防双编辑护栏拦截（混形态清单遗留重复 op），护栏先于写盘生效，零损坏（backup_b 系列可证）。

## 六、剩余项清单

- 旧路径 import 残留：**0**（22 点真身保留集见 §四.1，属 v21r2 裁定「真身未迁=旧路即唯一真路」，非遗留）。
- 挂起：无（§五.1 为设计裁定非挂起；§五.3 为域外移交）。
