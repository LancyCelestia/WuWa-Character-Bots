# 测试与机器门体系 · 棘轮与地板门

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.test-gates · 棘轮与地板门

- 层级：一级 B10 → 二级 test-gates → 三级 `ratchet-gates`
- 实现落点：`tests`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

管存量脏账。**清零**在真实仓库里往往等于「删门」或「把断言改成永远真」，所以本仓的多数结构门不要求今天归零，而是要求**只准变好**：棘轮基线只许下调，地板基线只许上调，硬零项一律不放行。

三档语义，全部有实现点：

- **棘轮（只降不升）**：`tests/test_doc_link_integrity.py` 的 `_BASELINE_*` 常量族——死坐标、旧路径写法、被指到垫片的坐标、markdown 死链、协议枚举副本、载体列误导面等各自一条基线；`tests/test_trigger_matcher_ratchet.py` 的触发词缺口棘轮。
- **地板（只升不降）**：同文件的 `_BASELINE_CARRIER_TRUTH`——「字面命中真身」的条数不得低于开工实测，整体失真必须长回来。棘轮管债只减，地板管真只增，两个方向合起来才堵死「把分母也改了」这条路。
- **硬零（不适用棘轮）**：协议枚举的非等值副本、载体列彻底不存在的路径等，命中即红，没有基线可谈。

另有**在飞档**：未入库草稿的缺陷条目单列一档，不计硬门但同样走棘轮，一旦入库自动落进棘轮/硬零——波次件不能把脏账带进史实。

## 怎么调用

随全量 pytest 跑；单独定位：

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_doc_link_integrity.py -q -p no:cacheprovider --basetemp=$TEMP/rg
```

排障开关：环境变量 `DOC_LINK_GATE_DUMP=1` 让该门把全量命中清单 dump 出来（每条红带真身与修法），不然只看计数无从下手。

改基线的唯一正当姿势：确属还账（数值变小）才动 `_BASELINE_*`，并且**同步在台账/审计件记一笔**——门自身的注释就写着「防止基线被悄悄抬高」。放宽（数值变大）不是改基线能解决的，要么修代码，要么把它当 P1 立项。

## 开关与参数

无配置键，基线是测试文件里的模块常量（刻意如此：基线改动必然进 diff，评审看得见）。同族的性能地板在 `tests/test_perf_regression.py`，规矩是「只许新增/收紧，禁放宽任何阈值」，阈值取实测数量级的三到十倍以躲开抖动。

归属规则要背下来：**棘轮基线由该门 owner 在生成物收敛后重录**。别的波次跑出来的红不构成本波降基线的理由，也不构成本波升基线的理由。

## 失败时看到什么

红消息形如「实测 N > 基线 M（只许降不许升）」或「低于地板」。三种典型：

1. **真还了账**：数值变小，门会提示「基线可下调」——这是唯一该改常量的情形。
2. **他波在飞**：例如并行波改了文档面路径写法导致计数上跳，本波只登记、不代改基线（先例：紧急域波次遇到 `test_doc_link_integrity` 旧路径棘轮上跳，处置是「本波所辖那一行改写为真身路径」，不代他波降基线）。
3. **门瞎了**：如果 dump 出来是零命中但代码里明显有旧写法，说明提取器失配——这条最危险，因为它让所有脏账一次性「消失」。`test_gate_is_seeing_the_tree` 就是专防这一手。

## 测试与验收

`tests/test_doc_link_integrity.py` 自带元用例族：`test_gate_is_seeing_the_tree`（门必须真在看树）、`test_exemptions_are_all_still_needed`（豁免不许过期赖着）、`test_negative_sample_coord_detection` / `test_negative_sample_carrier_detection`（注毒必抓）、`test_dump_mode`。`tests/test_ratchet_fix.py` 管棘轮修复动作本身的一致性。

判据一句话：**基线数字变小，必须能指出是哪条债还了；说不出就不许改。**
