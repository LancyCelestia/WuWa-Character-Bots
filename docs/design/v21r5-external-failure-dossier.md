# v21r5 外部失败归因档案（2026-09-21，主会话代 DOSSIER 席拟）

> 全量第五轮：**9953 passed / 5 failed / 13 skipped / 11 xfailed / 494.64s**（完整日志 $TEMP/fifth2-round-full.log）。
> **v21r5 波域零失败**佐证：波域定向 255P+广域 371P+第五轮无一波内域失败。五例全部外部归属：

| # | 测试 | 根因 | 归属 | 收口动作 |
|---|---|---|---|---|
| 1 | test_chat_and_sources_regressions::test_cookie_recovery | 本机 DNS 把 youtube.com 解析到保留网段→SSRF 护栏拒绝（环境性，非代码） | 环境 | 无需动作；网络恢复后自愈 |
| 2 | test_documentation_consistency::test_tone3_config_lines_carry_four_facets | 另一会话 05:07-06:47 在飞编辑 config/echo/测试（TTS/kb/模型面中途态） | 前端/TTS 会话 | 其收口时补齐四要素文案 |
| 3 | test_mermaid_reply_render::test_render_mermaid_html_mica_and_escapes | 前端 mermaid 渲染面在飞 | 前端会话 | 其收口自验 |
| 4 | test_model_admin_and_schedule::test_model_help_is_unique_and_covers_runtime_controls | echo.py 05:17 编辑后 /bot model help 缺 `vision mode` 条目（在飞中途态） | 前端/TTS 会话 | 其收口补条目 |
| 5 | test_runtime_config_loader::test_parity_with_nonebot_dotenv_source | config.py 05:07 新键与 .env 源 parity 在飞中途态 | 前端/TTS 会话 | 其收口对齐 |

## 渲染契约独立核验（主会话 2026-09-21 凌晨）

- `test_rendering_contract.py + test_mica_builders_contract.py` = **197 passed**——前端改动未破坏契约门。
- `verify_hashes --check` = 1 DRIFT：`domains/render/card_render/theme_tokens.py`（前端在飞未重录；早前 mermaid_card.html 漂移已被其 --write 吸收）。收口动作=前端确认后 `--write`。

## 轮次对照

| 轮 | 数字 | 说明 |
|---|---|---|
| 首轮 | 8708P/14F | campus 14F=U17 未实施规约（后证伪"重组债"初判） |
| 第二轮 | 9257P/6F | campus 摘牌前；含 webui 时间炸弹（已修） |
| 第三轮 | 9662P/5F | U17 摘牌后；2 例被 tail 截断未识别 |
| 第四轮 | 9662P/7F（完整） | 含 outbound_gate T6 旧前提（已随 U17 裁定更新）+catalog/s0（已修） |
| **第五轮（终态基线）** | **9953P/5F 全外部** | 另一会话 kb 实现落地（探测 9 passed）；两会话并发下此为最稳定一轮 |

## 交叉影响注记

- 另一会话 09-20 夜间活跃编辑：echo.py 05:09/05:17、config.py 05:07、root __init__.py 02:50（campus 坐标 5012→5027，我方已刷新）、kb_wiki 实现（06:19 前后落地）、mermaid_card.html/theme_tokens.py（哈希漂移源）。
- 全量套件在两会话并发编辑期数字不可复现（第二/五轮收集期被打断为实证）；第五轮为窗口内最完整一轮。
- v21r5 波全部改动未 commit、未重启；离线 passed ≠ 生产生效。

（DOSSIER 完）
