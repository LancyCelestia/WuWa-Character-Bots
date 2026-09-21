# v21r5 RESTART-PREP 席工作日志

- 席位：RESTART-PREP（重启验收清单）
- 开场：2026-09-19
- 交付物（唯一）：`docs/design/v21r5-restart-acceptance-checklist.md`
- 约束：零代码改动；禁 git 写操作；禁再派子代理；禁真实 LLM/发送/重启；.env 不读值；文档中文。

## 进度

- [x] 建本日志
- [x] 读素材：TIMEOUT-log / INTIMACY-log / POLICY-log / coordination / VERIF-log / v21r4-b-restart-acceptance-checklist / acceptance-manual §6.6.8 体例 / REVIEW-log（结构，只引用）
- [x] 起草 v21r5-restart-acceptance-checklist.md（⓪改动地图+①前置/②即验/③超时/④亲密/⑤政策/⑥回滚/⑦v21r4-B 衔接/⑧收尾门禁/⑨诚实声明）
- [x] 自查（结构完整性、无害话术合规、不写攻击样本原文）
- [x] 收尾标记

## 执行记录（RESTART-PREP-4 席，2026-09-19）

- 素材全读完成（三席 log + coordination + VERIF 预检 + v21r4-b 先例格式 + acceptance-manual §6.6.8/§6.6.9 体例 + REVIEW-log 结构）。
- 关键事实落码级核实（grep 实证，非转述）：failfast 告警原文=`llm failfast network abort consecutive=%d kind=%s elapsed_ms=%d remaining_candidates=%d`（model_router.py:2313-2318）+ attempts 记号 `failover:failfast_network`（:2313）；config_missing 冷却告警=`llm channel config_missing repeated cooldown model=%s count=%d …` + `kind=config_missing_repeated`（:666-679）；B 席观察面=`content_route: has_session=%s mode=%s tag=%s served_by=%s refusal_boilerplate=%s attempts=%s`（chat.py:2007-2014）；B 席四新键在 .env.example:517-523 拼写核实。
- 交付物已落盘：`docs/design/v21r5-restart-acceptance-checklist.md`（九节：改动地图/前置 P1-P6 含提权杀双进程与 netstat 现场重查口径/重启即验证 Q1-Q5/超时 A1-A5 条件性观察项标注/亲密 B1-B11 全无害探测/政策 C1-C6 攻击样本全部引用式 REVIEW-log 不转录/回滚面四项含 sync 锚定回滚点/v21r4-B 衔接九行含销项 mypy/收尾门禁 T-1/T+1 时点建议/诚实声明）。
- 无害话术合规自查：全清单探测=开关指令+served_by/mode/refusal_boilerplate 日志观察+普通闲聊；零涉性话术、零攻击样本原文（C1/C2/C4 均为「用 v21r5-REVIEW-log.md 对应攻击样本」引用式）。
- VERIF 5P/1S/3F 现值已写进 P1 与 §⑧（doc_sync/ruff 建议 T-1 收敛、kb_drift 用户裁决不阻塞）。
- 本席零代码改动、零 git 写操作、零子代理、未读 .env 值、未重启未发送。

## 断点与备注

（撞 1302/captcha 时在此落盘，固定 5 分钟后续跑。本轮未撞墙，一次通过。）

RESTART-SEAT DONE
