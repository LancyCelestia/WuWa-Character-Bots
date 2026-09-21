# S0-ROOT 系日志（根 `__init__.py` 四处直连收编执行席）

> 席位接替链：S0-ROOT（存活 12s，零产出）→ S0-ROOT-b（存活 90s，仅协调表认领行，零产出）→ **S0-ROOT-c（现席）**。
> 方案依据：docs/design/v21r4-b2-direct-collect-plan.md（DIRECT-PLAN 席）。执行序=④②③①，TDD，配置门缺省关。
> 硬约束：禁 git 写操作；禁子代理；TTS 席占域（config.py bot_tts_* / echo.py 语音条目 / tts.py / tests/test_tts.py）与前端波次独占面不触；离线测试，禁真实发送。

## 开工（2026-09-19，S0-ROOT-c）

- 协调表 S0-ROOT 系认领行已更新为「S0-ROOT-c 接替执行中」（docs/design/v21r4-b-coordination.md）。
- 根 `__init__.py` 现无他席在写（RWC5-b 已 ✅，协调表 ：20）；SYNC-FINAL/RET2b-R2 与本席零冲突。
- 方案坐标为读时快照，已按符号 grep 重定位（现坐标，本席实读）：
  - ① cookie 到期提醒：`_cookie_expiry_reminder_job` @ `plugins/bot_unified_runtime/__init__.py:4299`，直连 `send_private_msg` @ :4321 区段，配置门 `bot_cookie_expiry_reminder_enabled` @ :4297。
  - ② 入群欢迎：`_handle_group_increase` @ :5169，直连 `send_group_msg` @ :5199 区段。
  - ③ 二维码图片：`_handle_admin_cookie` @ :5473，直连 `send_group_msg`/`send_private_msg` @ :5496/:5502 区段。
  - ④ 文档导出上传：`_handle_admin_file_export` @ :5280，直连 `upload_group_file`/`upload_private_file` @ :5318/:5325 区段。
- 管线辅助函数现坐标：`_deliver_due_reminders` @ :2860（形态B先例）；`_send_text_through_unified_pipeline` @ :4680、`_send_parts_through_unified_pipeline` @ :4711（形态A）。

## 进度

### RED 基线（TDD 先行，2026-09-19）

- 新建 `tests/test_v21_s0_root_collect.py`（27 例）：四处 handler 为 `_register_nonebot_handlers()`（:3438 起）内嵌套函数，采用 **AST 提取函数节点 + 剪除体内内嵌 import（防遮蔽受控接缝）+ 受控命名空间编译 exec** 做双态行为断言；① 的模块级新助手直测（`deliver_fn` 注入缝，零 monkeypatch）。
- 实测中修正提取基建三次：get_source_segment 段内嵌 import 遮蔽注入 fake（①cookie_expiry_report/④_DOCUMENT_PROMPT）→ 改 AST 编译+剪除；decorator_list 随 FunctionDef 节点编译（NameError: group_increase_notice）→ 显式剥离；④ 环境漏注入 asyncio（NameError 被旧失败语义吞掉，恰证失败语义工作）→ 补注入。
- **RED 实跑**（命令=`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_s0_root_collect.py --basetemp="$TEMP/s0root-red4" -p no:cacheprovider -q`）：
  - 输出尾行：`16 failed, 11 passed in 5.04s`。
  - 16 红=全部实现依赖项（④ helper 契约+门开×4 / ② 门开×3 / ③ 门开×2 / ① 助手×4+job 门开×1 / 四门缺省关×1）；11 绿=旧路径锁（④ 门关×3 / ② 门关×2 / ③ 门关×2+无png×1 / ① job 门关×2+静默×1），旧路径锁先行通过=「门关逐字节等价」断言在实现前即锚定。
  - `test_via_queue_gates_default_off` 红=`getattr(Config(), 'bot_file_export_via_queue', 'missing')=='missing'`（四键未登记）。

### 逐处 GREEN（实现按 ④→②→③→①）

统一命令模板：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <目标> --basetemp="$TEMP/<名>" -p no:cacheprovider -q`（下略）。

- **④ 文档导出上传→形态D**：`__init__.py` `_handle_admin_file_export` 加 `bot_file_export_via_queue` 门开分支（`_send_files_through_unified_pipeline` 新助手：`CapabilityResult(files=[{file,name}])` kind=mixed → `_run_capability_through_pipeline` → renderer files→media_parts → transport file 部件 → `FileTransferGateway.stage/deliver`）；成功/失败文案回执态驱动，异常吞掉只回报（旧语义保持）；门关分支原直连逐字节未动。实跑 `-k "file_export or send_files_helper"`（s0root-g4b）：`8 passed`。
- **② 入群欢迎→形态A**：`_handle_group_increase` 加 `bot_group_welcome_via_queue` 门开分支（`_send_text_through_unified_pipeline` capability=`bot.group_welcome`；SENT/REDIRECTED 才记 `group_welcome_sent`；异常静默 return）；昵称富集 get_group_member_info 读路径未动；门关直连逐字节未动。实跑 `-k "welcome"`（s0root-g2）：`5 passed`。
- **③ 二维码图片→形态A mixed**：`_handle_admin_cookie` login 分支加 `bot_cookie_qr_via_queue` 门开分支（`_send_parts_through_unified_pipeline` text=""+image=`file:///…`，同款在树先例=表情回应 meme 抽图 :4435；audit_tags=cookie_login_qr，capability=`bot.cookie_login`；失败回执/异常均 debug 静默，文本兜底先行不变）；`qr_file_ref` 变量提取（治 mypy index 错，行为等价）；门关直连逐字节未动。实跑 `-k "qr"`（s0root-g3）：`5 passed`。
- **① cookie 到期提醒→形态B**：模块级新助手 `_deliver_cookie_expiry_report_via_queue`（`_deliver_due_reminders` 范式：SendRequest→`send_queue.submit`→`_find_sent_request`→内联 deliver（默认 `_deliver_transport_send_request`，`deliver_fn` 可注入）→SENT/REDIRECTED 才算送达；`dedupe_key=f"cookie-expiry:{admin}:{本地日期}"`+request_id 带日期=**当日幂等**（回执仓已有当日 SENT 直接视为送达，治重复打扰面）；管理员换人重试与旧 break/continue 等价；全部失败静默 False）；job 加 `bot_cookie_expiry_reminder_via_queue` 门开分支（传参面=config/queue/audit/repo/bot/report/admins），门关直连循环逐字节未动。实跑 `-k "cookie_reminder or via_queue_gates"`（s0root-g1）：`8 passed, 1 failed`（唯一红=四键未登记）→ config.py 四键登记后全文件实跑（s0root-g-all）：**`27 passed`**。

### 配置三件套 + doc_sync 协议

- `config.py` 四键（均缺省 False，避开 TTS 键块）：`bot_file_export_via_queue`（download_dir 后）/`bot_group_welcome_via_queue`（welcome 键后）/`bot_cookie_expiry_reminder_via_queue`+`bot_cookie_qr_via_queue`（cookies_file 后）。
- `docs/config-catalog-full.md` A26 增量区追加 4 行；`.env.example` BOT_COOKIES_FILE 后追加 4 行注释块。
- `docs/design/v21r2-COORDINATION.md` 先预告一行（协议）→ `python scripts/doc_sync.py --write` → `--check` 退出码 0（测试文件数+1、config 键数+4 已收敛）。

### 过程事故与修复（如实记）

- **`_deliver_due_reminders` else 分支缩进缺陷**：家族合跑暴露 `logger.warning` 处于 else 块外（UnboundLocalError，test_reminder_delivery 2 例红）。HEAD 同区与工作树多席在飞改动无法逐字节对认成因（前席交付残留或本席 Edit 事故），按正确语义恢复「warning 在 else 块内」缩进后重跑：提醒族 5 文件+本席 27 例 = **`94 passed`**（remfix）。以修复后实跑为准。
- **mypy :5712 index 错（本席引入）**：对 `image_segment` dict 字面量做 `["data"]["file"]` 索引 → 提取 `qr_file_ref` 变量修复，复跑根文件 mypy 零错。

### 验收清单终态

| 项 | 结果 |
|---|---|
| 四处收编清单 | ④②③① **全部收编**（零挂起；⑤登记表刷新不在本席四项任务内，登记表现状=BYPASS_SUSPECT×4 带 pending 注记，归登记表 owner/收尾波按本日志更新） |
| 存量族合跑 | `test_v21_s0_root_collect+test_v21_s0_collect+test_outbound_v21+test_phase0_3_features+test_v21_wiredirect_unified_path+test_v21r2_hotzone_notice_chain+test_group_notice_b05+提醒族5件+doc 门2件` = **195 passed / 1 failed**（唯一红=`test_verify_hashes_manifest_clean`，详见下行） |
| ruff | 本席三文件（根 `__init__.py`/config.py/新测试）`All checks passed`（2 处 RUF100 已修：noqa: BLE001 未用→摘码留注） |
| mypy（dev.ps1 口径 plugins 全树） | 4→3 错且**零归因本席**：tts.py×2（TTS 席在飞）+capability_protocols.py×1（RET2b web_search 垫片退役面）；根 `__init__.py` 本席零错 |
| command_catalog --check | 本席期间实跑=**current (77 topics)**；终验时点转 stale=TTS 席 echo.py 在飞改动（其占域，按其协议收工前统一 --write，本席不越域代写） |
| doc_sync | 预告→--write→--check **exit 0** |
| verify_hashes --check | 本席早段实跑 exit 0（未因本席变红）；终验时点 1 项 DRIFT=`domains/chat_reply/capabilities/echo.py`（**TTS 席占域在飞改动**，本席全程零触碰该文件、未 --write，归 TTS 窗口收敛） |
| 硬约束 | 零 git 写、零子代理、TTS/前端独占面零触碰、零真实 LLM/零真实发送、零重启；全程 basetemp=$TEMP + no:cacheprovider + PYTHONDONTWRITEBYTECODE（源码树 `.ruff_cache`/`.pytest_cache` 为他席既有产物，mtime 12:30/12:37 早于本席开工 ~13:0x，本席零新增缓存写入，留收尾波统一清理——他席在飞不宜动公共目录） |

### 诚实边界

- 以上全部为**离线测试证据**；四处新路径均在 `*_via_queue` 门后且**缺省 False**——生产现网行为=门关直连逐字节等价，**重启不拨门=零变更**；拨 True 且重启后才走统一路径（真机验收项：四处各触发一次+回执仓/审计/日志三面取证，留待用户重启窗口）。
- 当日幂等的队列层 dedupe 语义：InMemory 队列同 dedupe_key 二次 submit 出 skipped 回执（queue.py:192）；SQLite 队列 `ON CONFLICT(dedupe_key) DO NOTHING`——两态均已实证在库；内联投递面的同日防双发由回执仓 prior-SENT 短路承担（与 `_deliver_due_reminders` 同范式）。
- 登记表（outbound_registry.py）四处 BYPASS_SUSPECT 条目未由本席改状态（改之会破 S0-COLLECT 契约锁 4 例断言，且不在本席四项任务内）——**收编事实以本日志+协调表为准**，登记表状态刷新移交。

——S0-ROOT-c 席 收尾（2026-09-19）。根 `__init__.py` 独占写释放，TTS 席第二批可开工。

