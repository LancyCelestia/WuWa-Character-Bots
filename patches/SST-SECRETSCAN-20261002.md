# SST 工单 · test_secret_scan_tracked 工作树实证（2026-10-02，只读验证席）

## ① 命令
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 pytest tests/test_secret_scan_tracked.py -q -p no:cacheprovider --basetemp="$TEMP/qoder-SST/bt"
```
（工作树根；basetemp 实落 `/tmp/qoder-SST/bt`＝仓库外，合规）

## ② 末行原样
```
1 failed, 15 passed in 23.04s
```
error＝0。

## ③ 定性（唯一红）
- node ID：`tests/test_secret_scan_tracked.py::test_f1_findings_are_exactly_known_debt_roster`（锁①回潮腿，201 行）
- 断言首行：`AssertionError: git 已跟踪源出现册外/超次的 F1 硬编码凭据命中（(件,指纹) -> 多出的出现次数，全掩码）：` 后列 10 枚册外 (件,指纹)：atk_llm3_channel_health(4392…×2)、atkfix_tgmail_failure_reasons(3a10…)、connect_phase_retry(7152…)、credential_health_probe_throat(b338…)、file_send_receive_parity(210f…)、meme_vlm_observability(b788…)、person_profile_memory(1584ab5c…)、policy_gate_reason_observability(3e71…)、seat_fix_persona_r2(1584ab5c…×3)、telegram_document_ingress(210f…)。
- 归属定性：**HEAD 既存红，非伪影、非在飞 WIP**。证据三件：㈠ 测试件自身与 HEAD 逐位相同（`git show HEAD:…` 与工作树 sha256 同＝c6331644…；`git diff --quiet HEAD` 亦静默）；㈡ 10 枚册外命中件全部在 `git ls-files` 索引内且 `git status --porcelain`（按件路径）零输出＝已提交于 HEAD、工作树无改；㈢ 故同尺同树在 HEAD 轴同样成立。性质指向＝夹具形态假凭据复用到新件而未进 F1_DEBT_ROSTER/豁免面（1584ab5c… 与 test_event_service_v21.py 在册枚同指纹、210f… 两件同指纹），像记账缺口而非新真密钥——但未逐一开件验值（见⑤）。**不修**。

## ④ 与 BASE 判词互证
- BASE：「3 errors＝git archive 副本无 .git 的 `git ls-files` RuntimeError 伪影，工作树侧不应有」⇒ **实证成立**：工作树实跑 error=0。
- 但「无 error」≠「全绿」：工作树另有 1 枚 HEAD 既存红（③），与伪影无关；BASE 判词只覆盖 error 面，未涵盖此红，两判不冲突、互为补集。

## ⑤ 未尽
1. 10 枚册外 (件,指纹) 未逐一开件验值——是否全为合成夹具假值＝unknown，待裁席现算。
2. 处置（补点名册/豁免面 vs 还债摘密）＝用户裁决事项，本席只读未动。
3. `missing` 腿因 extra 先红被断言短路未评估；HEAD 轴全量复核未做（本席无 archive 复跑授权）。
