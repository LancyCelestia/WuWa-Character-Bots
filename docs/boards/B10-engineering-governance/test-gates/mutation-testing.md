# 测试与机器门体系 · 变异注毒自证

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.test-gates · 变异注毒自证

- 层级：一级 B10 → 二级 test-gates → 三级 `mutation-testing`
- 实现落点：`tests`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

回答一个拷问：**你的门，真的能抓住坏事吗？** 一条断言如果写成了恒真（比较了自己、只查文件存在、阈值定在天上、提取器根本没在看目标），它会永远绿，比没有门更糟——它给出虚假的安全感。

做法是变异注毒自证：把真身故意改坏（或在树里种一条坏样本），断言门**必须当场红**；改回原样必须绿。每条「已执法」的规则至少配一发这样的自证，评审报告里叫「注毒 N 发全红，逐笔 sha 核对还原」。

## 怎么调用

三种成熟形态，新门照抄其中一种即可：

1. **改坏声明源复跑体检**：`tests/test_board_taxonomy_gate.py:_tamper` 把 `board_taxonomy.py` 的文本读出来、替换一处、写到 `tmp_path`、`monkeypatch` 掉模块常量 `TAXONOMY_PY`，再跑 `build_tree()` 看问题清单里是否出现预期报警。三发注毒分别对应「新增席位漏登板块树」「一个帮助主题被两处认领」「实现路径写成不存在的文件」。替换必须先证明命中（`assert tampered != src`），否则用例失去意义而静默通过。
2. **种坏样本进受检树**：`tests/test_documentation_consistency.py::test_volatile_count_gate_detects_planted_line` 与 `tests/test_doc_link_integrity.py::test_negative_sample_coord_detection` / `::test_negative_sample_carrier_detection` 在 `tmp_path` 造一份含违例文本的假文档，喂给检测器，断言抓到；同时配「带指针写法必须放行」的反向自证，防止门过严到把所有话都判违例。
3. **代码级变异回归**：新建能力/修 bug 时对关键分支逐点注毒（把谓词改成恒真、把常量改回旧值、把 `startswith` 换回来），记录「几发变异各杀哪条锁、还原后 sha 等值」，作为交付证据的一部分。先例：凭证咽喉门与投递门的变异清单、紧急域路由面的注毒精确打红对应锁。

## 开关与参数

无配置键，纯离线（`tmp_path` + monkeypatch，绝不改真身文件——源码树零缓存与零污染铁律同样适用于测试自身）。

判定「这发注毒算不算数」的两条：

- 它必须**只**打红它声称要管的那条锁。打红一片说明断言粘在一起（杀伤力不可归因）；一条都不红说明锁是空的。
- 还原后必须与改前**字节等值**（在册件用 sha 前若干位核对，见 `tests/verify_hashes.py`），否则等于顺手改了真身。

## 失败时看到什么

两类「失败」都是好消息：

- 注毒后**没有**报警 → 该门当前无杀伤力，属 P1（门禁假绿），修门而不是删用例。历史上正是这一类抓到了「静态可达性全绿而生产零投递」。
- 反向自证（合规样本）被判红 → 门过严，会把所有写法都判违例，同样要修。

真实事故的完整形状（本仓最贵的一课，值得逐字记住）：紧急信息域三把静态门（投递可达、注入可达、配置键皆有非测试读点）全部实跑绿，生产实际**零投递**。真因是采集侧把条目 id 拼成 `nmc:A1`，而幂等键的段字符集禁用 `:`（它就是段分隔符），于是每一条真实条目都在投递口抛 `ValueError`，被调度器的兜底 `except` 压成一行日志。三把门都在问「东西在不在」，没有一把问「一条真的条目走得完吗」。修法 = 连接符换 `-` 并锁「源名不含 `-`」，而抓到它的是新建的**端到端 job 用例**——它第一次真的把一条假条目从采集推到投递口。

## 测试与验收

- 现役带注毒自证的门：`tests/test_board_taxonomy_gate.py`、`tests/test_documentation_consistency.py`、`tests/test_doc_link_integrity.py`、`tests/test_credential_domain_binding_gate.py`、`tests/test_ssrf_throat_coverage.py`、`tests/test_outbound_gate.py`、`tests/test_emergency_info_push.py`、`tests/test_emergency_info_review_gate.py`、`tests/test_affinity_v7.py`、`tests/test_capability_result_unique.py`、`tests/test_sync_drift_activation.py`（清单以 `grep -l 注毒 tests/` 现查为准，本页不维护副本）。
- 写「已完成/已修复/测试通过」时的交接硬规矩（AGENTS 铁律第五、六条）：必须同时给提交哈希，或可复跑命令 + 实跑输出；否则按未完成记账。注毒清单就是这条规矩最常见的证据形态。
- 反例形态（评审必查）：只断言符号存在、只数 AST 节点个数、阈值写成 `infinity`、比较对象与被检对象是同一份缓存、用 `xfail` 把红永久按住而不写摘牌条件。
