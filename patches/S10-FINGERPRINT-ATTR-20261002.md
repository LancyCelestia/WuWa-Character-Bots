# S10 工单 · F1 册外 10 枚指纹归属定性（2026-10-02，只读验证席）

复跑（工作树轴，实跑）：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_secret_scan_tracked.py::test_f1_findings_are_exactly_known_debt_roster -q -p no:cacheprovider --basetemp=<仓库外>` ⇒ `1 failed in 21.04s`，断言列 10 枚册外 (件,指纹)，与本单①一致。全程零 git 写、零进程动作。

## ① 10 枚清单（件 | git 态 | 指纹前8×次数 | 家族）

| 件 | git 态 | 指纹 | 家族 |
|---|---|---|---|
| tests/test_atk_llm3_channel_health.py | CLEAN＋IN_HEAD | 43920999×2 | prefixed-key+bearer |
| tests/test_atkfix_tgmail_failure_reasons.py | CLEAN＋IN_HEAD | 3a10fc18×1 | prefixed-key |
| tests/test_connect_phase_retry.py | CLEAN＋IN_HEAD | 7152ffc9×1 | assignment-literal |
| tests/test_credential_health_probe_throat.py | CLEAN＋IN_HEAD | b3384e85×1 | assignment-literal |
| tests/test_file_send_receive_parity.py | CLEAN＋IN_HEAD | 210fd515×1 | assignment-literal |
| tests/test_meme_vlm_observability.py | CLEAN＋IN_HEAD | b788e22f×1 | prefixed-key+assignment |
| tests/test_person_profile_memory.py | CLEAN＋IN_HEAD | 1584ab5c×1 | prefixed-key |
| tests/test_policy_gate_reason_observability.py | CLEAN＋IN_HEAD | 3e71794c×1 | assignment-literal |
| tests/test_seat_fix_persona_r2.py | CLEAN＋IN_HEAD | 1584ab5c×3 | prefixed-key+assignment |
| tests/test_telegram_document_ingress.py | CLEAN＋IN_HEAD | 210fd515×1 | assignment-literal |

性质：10/10＝HEAD 已提交测试件（部分末笔 1a92fda），patches 工单 0、生产件 0、未跟踪件 0。1584ab5c 与在册枚（test_event_service_v21.py）同指纹、210fd515 两件同值——多件同值指向夹具形；值未开验＝unknown（沿 SST ⑤.1）。

## ② HEAD 侧对照（红集原件实证）

- BASE-2 红集 `%TEMP%/qoder-BASE/b2/head-axis-reds-B2.txt`（184 枚 FAILED）：grep `secret_scan`＝零命中（rc=1）。WT 轴红集 `%TEMP%/qoder-FULL/wt-axis-reds.txt` 第 104 行在册。
- HEAD 轴原始输出末行：`184 failed, 21188 passed, …, 3 errors`。BASE-HEADAXIS-BUCKET §38：3 枚 ERROR 全落本测试件 setup 腿＝archive 副本无 .git ⇒ 尺 `_run_git_ls_files` RuntimeError ⇒ `full_scan` fixture error ⇒ error 不进 `-rf` FAILED 红集。
- 内容轴（本席实跑 `git show HEAD:件` 重扫同尺）：10 枚指纹 HEAD 侧命中数与 WT 逐件一致（2,1,1,1,1,1,1,1,3,1）。

## ③ 矛盾裁决

两席量的不是同一根轴，各按己轴皆对：
- SST「HEAD 既存红」＝**债务轴**：10 枚 (件,指纹) 全在 HEAD 已提交且 WT 零改的件里，HEAD 内容重扫逐枚复现 ⇒ 债务 100% 既存。SST 判对。
- 分桶「NEW」＝**红集轴**：HEAD 轴 archive 副本无 .git ⇒ 该门 fixture error（3 errors 之属）⇒ 不进 FAILED 红集 ⇒ WT 独有 ⇒ NEW。NEW 的真实语义＝「HEAD 轴不可判（方法伪影）」，**不是**「新债」。
- 使命案①（未跟踪在飞件带入）**证伪**；案②成立，根因＝HEAD 轴量具对 git-ls-files 依赖型门系统性失明。

## ④ 闭法素材（不代裁）

- **记账路线**（前提＝逐一验值证实合成夹具假值，SST ⑤.1 仍未做）：补登 `tests/test_secret_scan_tracked.py` 的 `F1_DEBT_ROSTER`（先例 b50195 裸 QQ 号点名）⚠ `ROSTER_CEILING=32` 现值顶格，补 13 次必顶穿＝须用户裁抬上限；或走 `FIXTURE_FAKE_EXEMPTIONS`（不占上限，但须逐枚写明属哪条断言、限 tests/）。动一件＝该测试文件。
- **还债路线**（若验出真值）：摘密＋轮替同批；此路 HEAD 轴红亦真红。
- **「入库后自愈」不成立**：10 件早已入库，入库动作不改变任何一轴判定。
- **方法面（BKT 域素材，与 SPC 空格 bug 并列）**：archive 副本无 .git ⇒ git-ls-files 依赖型门 HEAD 轴必 error ⇒「HEAD error＋WT FAIL」默认落 NEW＝分桶器盲区；修向＝单列「HEAD 轴不可判」桶。

## ⑤ 一句话结论

10 枚册外命中全为 HEAD 既存测试件里的既存指纹（债务轴既存）；分桶 NEW 系 HEAD 轴 archive 副本无 .git 致该门 error 出局的方法伪影——非新债、非未跟踪件带入，闭法在验值后二选一（补册记账 vs 摘密还债），裁权在用户。
