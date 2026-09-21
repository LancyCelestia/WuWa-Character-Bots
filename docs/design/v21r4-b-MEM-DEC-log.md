# v21r4-B MEM-DEC 席位工作日志

## 2026-09-18 开工

- 开工行已追加 `v21r4-b-coordination.md`：「MEM-DEC | L41 裁决材料 | docs/design/v21r4-L41-decision-memo.md（只读+文档）」。

## 取证记录（全部只读）

- 冲突原文三源定位：`v21r2-v2-memory-log.md:87-89`（§5 正文，主源）；`v21r2-matrix-backfill-draft.md:55/:105`（引用，注：该草案无 §5 章节）；`HANDOFF-V21R4-B-20260918.md:158/:196/:262/:292`。
- v21 实现真身：`domains/chat_reply/character/memory_store_v21.py`（:25 schema/:91 __init__ path 必填/WAL+busy_timeout）+ `memory_service.py`（:55 词表/:204 类/:286 propose_teaching）；顶层两文件为 PEP 562 垫片。
- 诚实修正：`build_memory_service_v21` 函数全树 rg 零命中——就绪物为模块对可直构（tests/test_memory_service_v21.py:60-63）；矩阵草案/db-owners 该名称失真已记入 memo 附注。
- 旧栈：memory_facts 建表无 version/status/tombstone/expires（memory.py:205-216）；生产 .env:97-100 wuwa_memory.sqlite3+enabled（只读抽查仅此三键）；消费点 __init__.py:361-382/:6240、debug.py:1175、smoke/diagnostics。
- DatabaseBroker：白名单五查询指向 send_queue/affinity/ledger/audit/subscriptions，不涵盖记忆表（database_broker.py:344 起）→ 两案与收口零耦合。
- 装配框架：主门 config.py:174 缺省关；V21_SERVICE_WIRING_IDS 四 id 无 memory（service_wiring.py:53-58）；teaching 分支 memory_service 刻意不传（:158）；teaching 先例=config 键+path_fields+runtime_path（config.py:166/:1110、service_wiring.py:141-156）。
- git 只读核查：v21 记忆五文件均 `??` 未跟踪（未 commit）。
- 测试数实数：`grep -c "def test_" tests/test_memory_service_v21.py` = 41（未重跑套件，转述基线已标注）。

## 交付清单（本席完成）

- **docs/design/v21r4-L41-decision-memo.md**（唯一交付物）：文首「裁决材料，不构成实施」；①冲突原文照录+三源引用链；②现状取证全 file:line（v21 存储/服务/构造方式/垫片/git 态、旧栈三库格局与生产实态、Broker 覆盖面=不涵盖、装配框架与 teaching 先例）；③A 独立新库 vs B1 同文件并存 vs B2 改造 memory_facts 三案对比（工作量级/回归面/可逆性）；④推荐 A+六条理由+B1 备选+不建议 B2；⑤可勾选裁决清单（主裁定单选+A/B 附加项+后续归属）。
- 状态口径守住：未裁决、未接线、not_wired、未 commit、未重启未部署；41 例全绿与基线证据均标注为转述非本席实跑。
- 零代码改动、零 git 写操作、零子代理、零 LLM 调用、backend-v2-acceptance-matrix.md 零触碰。
