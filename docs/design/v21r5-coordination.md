# v21r5 波次协同登记（2026-09-20）

用户指令三件：①修复回复超时 ②群聊亲密模式双开关+四名单 ③R-18 政策再放宽（五条硬线保留）+成人内容裁定清单。

## 席位与文件域（互斥，越界即事故）

| 席 | 任务 | 独占文件域 | log |
|---|---|---|---|
| A-TIMEOUT | 链级 fail-fast + config_missing 重复冷却 | `plugins/bot_unified_runtime/llm/**`、`tests/test_llm_failfast.py`、`tests/test_model_router*` | docs/design/v21r5-TIMEOUT-log.md |
| B-INTIMACY | 亲密模式 v3：双开关+TTL 60min+四名单 | `runtime/content_route.py`、`capabilities/chat.py`（仅亲密注入缝）、`config.py`、`docs/config-catalog-full.md`、`.env.example`、`tests/test_content_route*` | docs/design/v21r5-INTIMACY-log.md |
| C-POLICY | 政策放宽（触手/轻SM 放开；五硬线钉死） | `domains/chat_reply/policy/content_safety.py`、`domains/chat_reply/security/**`（memory_sanitize）、`character/affinity.py`、`personas/**`+Runtime 人格副本、`tests/test_content_safety*` | docs/design/v21r5-POLICY-log.md |
| 主会话 | 成人内容裁定清单 memo、测试分诊（test_outdomain_fixes collection error 等）、合流全量 | `docs/design/r18-taxonomy-20260920.md`、`tests/test_outdomain_fixes_20260911.py` | 本文件追加 |

## 关键缝（跨席接口，主会话裁）

- `content_safety.explicit_allowed_for_session`（C 独占函数体）= 会话级许可（私聊/白名单群），签名不变；**用户级 opt-in（B）在其上游做 AND 合成**：最终许可 = 会话级许可 ∧ 用户级状态。B 禁改 C 的文件。
- config.py 归 B；A 如需新键只在 log 提案，不落码。
- personas 一致性门（源-副本）归 C，按 #36 先例 sync --adopt。

## 纪律（全体）

禁 git 写操作；禁再派子代理；禁真实 LLM 调用/对外发送/生产重启；.env 只许键名存在性检查；离线 passed ≠ 生产生效；全部不 commit；撞 1302 → 落盘 + 固定 5 分钟退避续跑；测试纪律 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + `--basetemp=$TEMP/<seat>-tmp -p no:cacheprovider`。

## 状态

- [2026-09-20] 首轮三席全灭于平台故障（并发上限/captcha），零改动落盘；按 5 分钟固定退避重派。
- [2026-09-20] A 席完成：链级 fail-fast（连续 5 跳网络类失败中止，300s→~100s）+ config_missing ≥3 次冷却（10×900s）；tests/test_llm_failfast.py 8/8 + failover 家族 204 + 相邻 89 passed，ruff/mypy 净；.env 实查 BOT_POTCCV_API_KEY 已配置（14:06 config_missing=生产进程早于 POTCCV 上车未重启所致，重启即消）。log=v21r5-TIMEOUT-log.md。
- [2026-09-20] 用户裁定全量回写 r18-taxonomy-20260920.md §六；硬线 5→6 条（+非人化牲口式对待）；C 席终版简报=v21r5-C-brief-final.md。
- [2026-09-20 18:3x] C-CONT 收口（`C-SEAT DONE`）：核验前任幸存件全保留（memory_sanitize 收窄/人格四处+Runtime 副本/sync 门 --adopt sha=f3de6189… 均已由前任完成，比 checkbox 先进）；本席实改=②窒息与⑤暴力SM 词面补完（补语间隔/英文宾语形/出疤族）+ `_SEXUAL_CONTEXT` re.compile 收编（copy_redline_gate 豁免面，pattern 逐字节不变）+ auditfix 零宽断言改 minors 对 + phase0_3 boundary 测试改群会话触发 + ruff 3 处；受影响 8 文件 109 passed、广义 31 文件 418 passed/1 红（test_affinity 旧文本锁，不归席）。
- [2026-09-21 凌晨] **波次收口**。全量终跑两轮：第一轮 9257P/6F（6F 全外部归属：3NMC=另一会话并发编辑扰动单跑全绿+2 前端域 mermaid/webui tsc+1 环境性 DNS）/14xf；第二轮 9287P/30F+29E——并发改树数字不可复现（29E 全=TTS contract 另一会话在飞中途态），改以波域定向终验收口：**255 passed/11 xfailed/0 failed**（content_safety v3+v4/memory_sanitize/content_route 两代/llm failfast/campus/outbound 棘轮/affinity/persona sync/doc_sync 门禁合跑）。REVERIFY 终稿：Critical 关闭核销通过（主会话代收⑤-⑨，REVERIFY-2 两度阵亡零进度）。campus 坐标二次漂移（另一会话 02:50 动 root __init__.py，5012→5027）主会话已刷新复验。
- [2026-09-21 凌晨·硬收口（用户电脑重启前）] 主会话串行代收全部完成：①外部失败档案 v21r5-external-failure-dossier.md（第五轮 9953P/5F 全外部+五轮对照）②帮助注册表快照 v21r5-help-registry-snapshot.md（77 topics/指纹 c64c485a，供另一会话对照）③渲染契约独立核验 197P（前端未破契约门；theme_tokens.py 1 DRIFT 待其 --write）④HANDBOOK 两处过期表述修（修复中/待裁决→终局注记）⑤.mypy_cache 37MB 清 ⑥广域家族回归 371P。**波次终态：三任务+U17 全链+评审核销链+档案全部交付；波域定向 255P/广域 371P/渲染契约 197P/全量第五轮 9953P（5F 全外部）。递延：U17 深度质量复审、另一会话收口后的全量补跑——均不阻塞重启。全部未 commit，重启后按 v21r5-restart-acceptance-checklist.md 验收。**
- [2026-09-20] 主会话合流记录：test_affinity.py:97 文本锁对齐 C 定稿措辞；首轮全量 dev.ps1 实跑 **8708 passed / 14 failed**（14 例全部=campus 域重组遗留测试债，非本波损伤，campus 生产链路完好）；三席域全绿。
- [2026-09-20] B 席完成：双开关+TTL 60min+四名单全落码（content_route.py 410→614、chat.py 亲密缝、config 四键、test_content_route_v3 28 例），相关 24 文件 298 passed 零回归，ruff/mypy 净。关键实核：`explicit_allowed_for_session` 真身在 content_route.py:501（非简报所称 security/），私聊名单门按最小偏差在彼实现，security/ 零接触。log=v21r5-INTIMACY-log.md。
- [2026-09-20] 主会话收口 B 席遗留：root __init__.py:7367 被动好感感知补传 sender_id（私聊名单门同源生效，群分支零改动）；content_route+affinity 家族 78 passed，1 失败=test_affinity.py 旧红线文本断言 vs C 席在飞新文本（预期态，C 收口后主会话对齐 test_affinity.py 文本锁——C 所有权不含该文件）。
- 主会话已修 test_webui_http 时间炸弹夹具（6/6 绿）；全量回归延后至三席合流统一实跑。
- [2026-09-21] **用户三裁决落账**（DECISIONS-LOG-2 席，log=v21r5-DECISIONS-log.md）：①**U17-CAMPUS-WIRE=实施**——audit §4 两裁定点按席位推荐接受：review 门 fail-closed（源群文本含密钥/路径形态被拦维持）、截断满额 1501 字边缘消息零改动（min_chars=1500 现值不动）；**U17-IMPL 实施席在飞，终态由实施完成后的回填席统一落账，本条不预填**（runbook=v21r5-u17-implementation-runbook.md）。②**kb_drift=不重建（终局裁定）**——ANN=35341 vs chunks=35477（已嵌入 4539，v21r4-B B5 同族）维持现状挂账，**此后台账/预检不再将其列为待决项**。③**`aged 130就` 望卫数字续位=执行**——FIX-N1b 席已收口落码：`aged` 形态尾卫收紧 `(?![A-Za-z])`→`(?![0-9A-Za-z])`（数字延续=非独立年龄，`aged 130` 不命中 signal），test_content_safety_v4.py 回归锁已立（v21r5-FIXN1B-log.md，FIXN1B-SEAT DONE）。→ 遗留用户项①②③就此出清（①转在飞实施），剩余④%TEMP% 空壳解锁手删⑤双 bot.py 进程清理+重启。
