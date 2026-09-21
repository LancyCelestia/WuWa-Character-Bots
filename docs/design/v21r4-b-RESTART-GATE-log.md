# RESTART-GATE 日志（重启就绪快照席位，2026-09-19）

- [13:44:43] 席位登记：v21r4-b-coordination.md 已追加 RESTART-GATE 行（tests/ 只读 + 门禁四件 + pre_restart_check）。
- [13:46:30] 门禁四件（--check 全只读）：
  - ruff check . = FAIL，29 错（11 条在源码树生成物 `.tmp-test/full/*` 内【F821×1/F841×3/invalid-syntax×2/I001×5】；18 条源码 I001 导入序：control_plane/dispatcher.py:157、domains/chat_reply/{capabilities/chat.py,pipeline/backend_unit.py,policy/quiet_hours.py,policy/rate_limit.py,security/injection.py}、domains/link_parse/capabilities/content_parser.py:7、domains/music/capabilities/music.py:262、sources/__init__.py、tests/ 下 9 文件；23 条可 --fix，未代修）。`.tmp-test/` 为疑似 basetemp 违规入树的 pytest 生成物，本席只读未清。
  - verify_hashes --check = FAIL，1 项 DRIFT：plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py（字节变更未记录）→ 归属 TTS 席占域（echo.py 语音条目在飞），未代录。
  - doc_sync --check = PASS（exit 0）。
  - command_catalog --check = PASS（current 77 topics）。
- [13:45:45] 插件导入冒烟：`import bot; import plugins.bot_unified_runtime` = import ok，耗时 3.39s（venv Python 3.12.10）。
- [13:46:00] 全量回归基线 pytest 已后台启动（basetemp=C:/Users/.../Temp/v21r4-restart-gate，PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 -p no:cacheprovider），日志=/tmp/v21r4-restart-gate-pytest.log，预计约 8 分钟。

## 主代理席吸收收口（2026-09-20 14:1x）
- 席位在预检步骤前阵亡（验证码超时），但其后台全量 pytest 子进程存活至完成：日志 /tmp/v21r4-restart-gate-pytest.log → **8561 passed / 4 failed**（4 失败全在飞面：echo.py 哈希×2=TTS、feature_gate=TTS 根文件编辑窗、webui=前端）。
- 主代理席补跑 pre_restart_check.py：PASS 5 / SKIP 1 / FAIL 3（hash=echo 在飞、kb_drift=已知存量、ruff=在飞文件）——无阻断级。
- 快照落盘 docs/design/v21r4-b-restart-gate-snapshot.md；判定=能起。本席关账。
