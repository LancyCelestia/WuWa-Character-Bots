# v21r5 → 前端/TTS 会话交接包（2026-09-21，主会话代 FRONTEND-PACK 席拟）

> 用途：并行前端/TTS 会话收口时所需的外部失败证据与动作清单。v21r5 波对其域文件零触碰（render/**、echo.py、render_hashes.json 等全按域所有权未动）。

## 1. mermaid_card.html 哈希漂移（verify_hashes 1 DRIFT）

- 现象：`python tests/verify_hashes.py --check` EXIT=1，`DRIFT plugins/bot_unified_runtime/domains/render/card_render/templates/mermaid_card.html（字节变更未记录）`。
- 归属：前端会话在飞改动未重录（v21r5 波全程未碰 render/**，mtime 实证早于本波开席后仍被外部更新）。
- 收口动作：确认改动属预期后 `python tests/verify_hashes.py --write` 重录。
- 连带：`tests/test_verify_hashes_coverage.py::test_builder_drift_gate_red_then_green` 的还原段因此环境性失败（红绿演练被未记录漂移污染），重录后自愈；`tests/test_mermaid_reply_render.py::test_render_mermaid_html_mica_and_escapes` 同窗失败，同属该面。

## 2. echo.py 功能管理 help 漂移（test_runtime_help_entries_match_static_merge）

- 现象：runtime merge 与 static merge 对 topic=功能管理 的 `detail` 不一致——echo.py:463-465 的【指令与参数】段（/bot feature list|get|enable|disable|reset|preview）与运行时拼装源存在段落差异。
- 归属：echo.py 09-20 05:09 被外部编辑（TTS/前端域所有权文件），v21r5 波零触碰。
- 收口动作：对齐 echo.py 静态段与运行时 features help 源（或按其机制重录），自跑该测试确认。

## 3. test_webui_http 时间炸弹（已由 v21r5 修复，前端无需动作）

- 种子行硬编码 2026-09-18T01:00Z 撞 now-24h 相对窗口；已改动态近期时间戳（6/6 绿）。知会即可。

## 4. TTS contract 29 errors 中间态

- 全量第二轮（9287P）目击 `tests/test_tts_contract_layer.py` 29 errors+散点失败——TTS 席在飞中途态。第五轮收集期另见 `tests/test_kb_metadata_probe_window.py`（09-20 06:12 新建）ImportError：`probe_corpus_time_fields` 尚未在 kb_wiki.py 落地（测试先行）。TTS/kb 收口时自验。

## 5. ruff 残余归属表（以终态轮现值为准）

- v21r5 波域+campus 已清零；残余按 VERIF/CLEANUP 轮归属：webui test×7、chat_reply×4（前端/在飞面），随各自收口收敛。

## 6. 交叉影响说明

- v21r5 波动了 root `__init__.py` campus 段（U17 收编）与 outbound_registry.py（campus/file_gateway 坐标+note）——前端如依赖 root 行号，注意 campus 段 5027 起的结构已变（matcher 注册行未动）。
- 全量套件在两会话并发编辑期数字不可复现（第二/五轮收集期被打断为实证）；建议前端收口后双方协调窗口再跑终轮。

（FRONTPACK 完）
