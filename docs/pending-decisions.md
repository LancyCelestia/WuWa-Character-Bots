# 待用户裁决清单（pending-decisions）

- 生成：2026-09-14（聚合代理，逐份过九源：billing-report / issue-ledger-p2-p3 / visual-report / persona-sync-report / persona-distill-draft / error-card-async-design / reactions-tone-audit / vector-audit / HANDOFF-NEXT，全部在 `.superpowers/sdd/2026-09-13-six-domain-batch/` 与 `docs/`）
- 口径：**AI 只提醒不代决**（HANDOFF-NEXT §6 同口径）；已闭环项一律不列（见文末排除注记）。每条含：出处 / 建议时机（立即=重启前拍板 / 重启后 / 下批次）。

## A 组：功能与内容

| 编号 | 事项 | 背景一句话 | 选项 | 建议倾向 | 不裁决的后果 | 出处 | 建议时机 |
|---|---|---|---|---|---|---|---|
| A1 | 人格副本蒸馏方向（09-13 三段规则上车） | 生产人格正文唯一来自运行时副本（9,807B），源 identity.md 已领先两提交（称谓边界/超管创造者身份/黄腔回应柔化），副本全缺；蒸馏拟稿已备好 | A=按拟稿 A/B/C 三段套入副本＋`sync_persona_source.py --adopt` 复绿；B=裁定副本即终态，仅 `--adopt` 认可现状 | A（副本是生产人格唯一来源，缺规则=生产缺这些约束） | 源-副本继续分叉：生产人格无称谓边界文本层、无创造者身份、无黄腔柔化 | persona-sync-report.md §四.1；persona-distill-draft.md（拟稿全文）；HANDOFF-NEXT.md §2.5 | **立即**（改副本须重启生效，宜与本次提权重启同车） |
| A2 | 拟稿配套冲突①：括号动作 | 源 §4.6 要求动作用（）＋颜文字多样，副本第 3 行明令「不写括号动作」，真冲突 | A=维持副本口径，不同步 §4.6；B=反转成源口径（须另改副本第 3 行＋语感节，影响面大） | A（生产 QQ 卡片口径以副本为准） | 有人按源侧全量同步时引入自相矛盾 | persona-distill-draft.md §三.1 | 随 A1 一并表态 |
| A3 | 拟稿配套冲突②：「难过」愧疚话术口径 | 副本底线第 83 行示例「这句话让我有些难过。」与源 §1.2-4「不用让对方背愧疚的话」措辞接近 | A=第 83 行示例改「……我先安静一会儿。」向源对齐；B=维持现状（字面主体不同，可并存） | A | 两种口径并存，黄腔场景话术可能自相矛盾 | persona-distill-draft.md §三.2 | 随 A1 一并表态 |
| A4 | 人格同步锚定文件位置 | 实施时因 personas/ 只读纪律把锚定放 `scripts/persona_sync_anchor.json`（任务原文要求 `personas/shorekeeper/SYNC.md`），白名单偏差待追认 | A=维持 scripts/ 现状；B=迁 personas/shorekeeper/SYNC.md（改 `ANCHOR_PATH` 一行＋挪文件，须解除只读纪律） | A（零改动；工程元数据不进人格资产目录） | 无阻塞，默认维持现状 | persona-sync-report.md §二（偏差声明）/§四.2 | 下批次 |
| A5 | reactions 表情回应：C1 修复前生产是否启用 | tone-audit 判 C1 红线级（悲伤消息可被贴笑脸），`bot_reactions_enabled` 缺省 True | A=生产 .env 显式关，C1 修复后再开；B=接受现状先开；C=先修 C1 再随重启开启 | A 或 C（不在 C1 修复前在线上开） | 缺省 True 随重启生效=带红线级观感缺陷上线 | reactions-tone-audit.md §Critical C1＋§真机验收补充清单.2；reactions-report.md §六.3 | **立即**（重启前定 .env 开关） |
| A6 | 表情映射 I4：9 个表情 id 真机目检 | id→实际贴脸无实机证据（名表已现疑点：id6/id42 同名「害羞」，社区口径 42 常为「亲亲」） | A=重启验收逐 id 目检 9 个主动贴脸（41/13/19/6/14/20/5/29/27）＋修正名表，并入 acceptance-manual §6.6 系；B=跳过目检直接使用 | A | 「赞同」可能长期贴跑偏的脸（观感事故） | reactions-tone-audit.md §Important I4＋§真机验收补充清单.1 | 重启后（随 §6.6 系验收） |

## B 组：数据与账务

| 编号 | 事项 | 背景一句话 | 选项 | 建议倾向 | 不裁决的后果 | 出处 | 建议时机 |
|---|---|---|---|---|---|---|---|
| B1 | 价目表更新清单（52 条审计，约 25 条可疑/过时/unknown；6 项优先） | 官方直连 11 行=7 OK＋1 可疑＋2 过时＋1 unknown；中转 41 行含 4 可疑-高＋18 可疑-低 | A=按 6 项优先清单逐项核对后热改（`/bot model price` 或 `import_model_prices.py --apply`）；B=维持现价仅记账提示；C=可疑-高渠道确认实收或弃用 | A（至少落实 6 项：deepseek-v4-pro 输入价、v4-flash 族已下线、qianqianye 3~4.5×、gpt-5.6-luna 2.1× 倒挂、aiprc fable-5 两行互斥 6.7×、axonhub gemini 裸名上游归属） | 账单持续按错价记账（v4-pro 低估 33~67%、qianqianye 高挂 3~4.5×）；峰谷差价结构性低估留待扩 price 字段另议 | billing-report.md §3.3；docs/issue-ledger-p2-p3.md P2-10（方法学补充 P3-10） | **立即**（价格字段热生效，无需重启） |
| B2 | 账本历史行 cost 千倍虚大是否清洗 | 旧 `build_call_draft` 未除 1000，`pricing_source='channel_spec'` 历史行（若账本开过）cost 虚大 1000 倍；代码已修，生产库未动 | A=按 1/1000 批量 UPDATE 历史行；B=加标注字段不动数值；C=先确认 `BOT_LLM_BILLING_ENABLED` 开关史，从未开过则无需动作 | 若开过账本→A；先查开关史定性 | `/bot model usage` 历史账单失真千倍，与渠道对账永远对不上，历史行越积越多 | docs/issue-ledger-p2-p3.md P2-11；billing-report.md §四.1 | **立即** |
| B3 | 反注入护栏文案（威慑 vs 极简） | 触发护栏时文案向触发者明示「系统提示/密钥/本机文件」存在，威慑设计与攻击面提示之争 | A=保留威慑版；B=改极简版「我不能聊这些，换个话题吧」 | 台账未预设倾向：攻击面最小化看 B 略优，威慑路线看 A 可辩护 | 护栏文案继续向恶意用户提示防御焦点 | docs/issue-ledger-p2-p3.md P2-4 | 下批次（聚合时在台账发现的自选项，非简报九源） |

## C 组：视觉与文案

| 编号 | 事项 | 背景一句话 | 选项 | 建议倾向 | 不裁决的后果 | 出处 | 建议时机 |
|---|---|---|---|---|---|---|---|
| C1 | Apple Music×小红书 accent ΔE=2.7 是否拉开 | 17 平台互异最小 ΔE=2.7（近可辨阈 2.5），两者均官方品牌色，实际靠页脚展示名文字区分 | A=保留双官方色；B=Apple Music 改粉品红系拉开 | A（品牌忠实度优先，可辨性已有页脚文字兜底） | 维持现状（P3 纯观感，无阻塞） | visual-report.md §2 P3-1/§5.6/§7.3①；docs/issue-ledger-p2-p3.md P3-7 | 下批次 |
| C2 | 页脚第二槽 'Shorekeeper' 是否改「解析」 | universal/旧媒体卡页脚第二槽 feature_label 缺省回英文品牌词 Shorekeeper，clarify 已裁定「品牌词非错误文案」但留口待用户 | A=维持 'Shorekeeper'；B=改功能名「解析」 | A（DESIGN-SPEC 一.8 已补记此口径） | 维持现状 | visual-report.md §3 裁定行/§7.3②；docs/issue-ledger-p2-p3.md P3-8① | 下批次 |
| C3 | usage 卡 kicker 去留 | kicker「测试 · 模型用量」与标题信息部分重复（craft-floor 禁 kicker/eyebrow） | A=保留；B=删除 | A（admin 运维卡低收益；字距已收敛到刻度） | 维持现状 | visual-report.md §2 P3-2/§7.3③；docs/issue-ledger-p2-p3.md P3-8② | 下批次 |
| C4 | reactions 语气审计修复后复核安排 | tone-audit 总裁决「需修」（1 Critical/4 Important/4 Minor），修复在飞 | A=修复落库后由独立审计席按原分级清单复验（C1 负向情绪词族/I1 安慰映射/I2 触发面/I3 简繁缺口）＋真机三项观察；B=修复席自验即闭环 | A（审计与修复分席，防自查自漏） | 红线级 C1 可能修不彻底即上线 | reactions-tone-audit.md §分级清单＋§真机验收补充清单.3 | 修复落库后（下批次）；真机观察随重启后验收 |

## D 组：运维与环境

| 编号 | 事项 | 背景一句话 | 选项 | 建议倾向 | 不裁决的后果 | 出处 | 建议时机 |
|---|---|---|---|---|---|---|---|
| D1 | Runtime 向量栈 L3-1 治理立项（预期回收 ~3.5GiB） | 两库 vector_json 与 blob 双存同数据，3.5GiB 热路径几乎不读；L1/L2 实测无可回收（~2MB/~25MB） | A=立项 L3-1 废除 vector_json 双存（代码 8 处＋迁移 SQL＋VACUUM，停机窗口，半天级，检索零影响）；B=不做（维持 7.25GiB）；C=A＋FAISS int8 量化（再 −0.75GiB，需召回 A/B 评测） | A（唯一高收益项；C 仅当 A 后仍不够） | 3.5GiB 持续占地；注意**不能只改数据不改代码**——纯置 NULL 会触发 23.8 万行全量重嵌（约 3.5 小时） | vector-audit.md §二/§四 L3/§五 | 下批次（需 bot 停机窗口） |
| D2 | C 盘 pagefile.sys 82GB | 页面文件膨胀至 82GB（任务简报转述，无报告出处），重启通常回落 | A=重启观察是否回落；B=手动调小（虚拟内存设固定范围） | A 先行（重启本就是待办），不回落再 B | C 盘持续被占 82GB（挤占 VACUUM/临时空间） | HANDOFF-NEXT.md §6「等用户裁定」；handoff-refresh-report.md §6（已如实标注无报告出处） | 重启时顺带 |
| D3 | $TEMP oopz 安装包 ~458MB 是否删 | 临时目录残留安装包（任务简报转述，无报告出处） | A=删；B=留 | A（临时件，可随时重下） | 458MB 临时空间持续占用 | HANDOFF-NEXT.md §6；handoff-refresh-report.md §6 | 立即（随手） |

## 排除注记（已闭环，不列）

- **error-card-async-design.md 两案**：A-rec 两段式已实施入库（de6ba91 P0＋84b3915 补发加速 3-33s，1651544 全链）；B=b2 维持现状＋文档已带 → 双案闭环（出处：error-card-async-design.md §五；crossdoc-final-audit.md §三 C4 行）。
- **vector-audit §六.1** `BOT_KB_WIKI_ROOT` 失效 → 用户已修；**§六.2** knowledge-sync 三重漂移 → A45 已修（出处：handbook-backfill2-report.md 补记行）。
- **人格同步门本体**已入库生效（a1cf739），残余仅 A1/A4 两个决策。
