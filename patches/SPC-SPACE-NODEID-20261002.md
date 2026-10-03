# SPC 工单：ab_red_bucket.py 对含空格 node ID 的耐性实测（2026-10-02 下午窗）

席 SPC（工具实测席，只读；本工单为唯一写产物）。BKT 域真 bug，**未修**，交主会话裁。
复现样本与全部输出落盘：`/tmp/qoder-SPC/`（sampleA.txt / sampleB.txt / out.json / out_rev.json / out_same.json / nodeid-verbatim.txt）。

## ① 样本原文（转义可见）

源＝`%TEMP%/qoder-BASE/b2/head-axis-reds-B2.txt` 第 129 行（全文件 grep 空格仅此 1 枚）。实际逐字节（`cat -A` 验证，行尾仅 LF；`\u4e71\u8d34` 为字面反斜杠转义文本，非 UTF-8 字符；`J9` 后有一个空格 0x20）：

```
tests/test_randpic_mutation_teeth.py::test_poison_breaks_the_lock_and_the_real_body_passes[J9 gallery_empty \u4e71\u8d34]
```

- sampleA.txt＝BASE-2 全部 184 行转成工具期望的 `-rf` 摘要形态（`FAILED <nodeid> - AssertionError: assert not admitted`，含 `short test summary info` 横幅与计数行）＋该枚原样；
- sampleB.txt＝sampleA 仅去掉这一枚（`diff` 验证恰差 1 行）。

## ② 工具输出

RUN1 `ab_red_bucket.py sampleA sampleB --json out.json`（A vs B）三桶：

```
== NEW_ONLY（只在 B＝净新增红）n=0 ==
  （空）
== GONE_ONLY（只在 A＝转绿）n=1 ==
  tests/test_randpic_mutation_teeth.py::test_poison_breaks_the_lock_and_the_real_body_passes[J9
    - tests/test_randpic_mutation_teeth.py::test_poison_breaks_the_lock_and_the_real_body_passes[J9
== COMMON（两边共有＝既存红）n=179 ==
```

out.json `gone_only[0].function/params`＝`…passes[J9`——**在首个空格处腰斩**，`gallery_empty \u4e71\u8d34]` 静默丢失；残缺尾 `[J9` 非完整括号组，`function_level` 剥不掉，函数级键本身即被污染。

探针（直接调 `extract_failed_nodeids` / `bucket`，实跑）：

```
UNWRAPPED -> ['…passes[J9']
WRAPPED   -> ['…passes[J9gallery_empty']   # 折点在空格处，_merge 直接粘连
bucket(plain, wrapped) → new_only=[…passes[J9gallery_empty], gone_only=[…passes[J9], common=[]   ⇒ rc 1
bucket("FAILED tests/t.py::test_x[J9 gallery_empty a] - boom",
       "FAILED tests/t.py::test_x[J9 gallery_full b] - boom") → common=['tests/t.py::test_x[J9']  # 假 COMMON
```

## ③ rc

| 运行 | rc |
|---|---|
| RUN1 A vs B | 0 |
| RUN2 B vs A（镜像） | 1 |
| RUN3 A vs A | 0 |
| 探针 bucket(plain, wrapped)（同一测试仅折行差异） | **1（假阳）** |

## ④ 判定：真 bug（BKT 域，未修）

- **桶位正确性**：不折行形态下该枚恰落 GONE_ONLY 一处、无假 NEW+假 GONE 对——桶划分这一腿过关。
- **ID 原貌**：不及格。`_flush` 取第 2 个空白 token，而 docstring 自认前提「node ID 不含空白」对本枚不成立。三种已实跑证实的失效形态：
  1. **腰斩**：报告点名不存在的残 ID `…passes[J9`（RUN1/RUN2）；
  2. **假 NEW+假 GONE 对**：同一测试一轴折行一轴不折 ⇒ 两轴残键不同 ⇒ 互进 NEW/GONE、common 空、rc=1（假阳终门）；
  3. **假 COMMON 吞红**：不同参数共享空格前前缀 ⇒ 塌成同键 ⇒ 真新增红被吞（假阴）。
- 修向（供 BKT 参考，非本席执行）：node ID 提取改按最后一个 ` - ` 分隔符切（或 `^FAILED (\S.*?)(?: - |$)`），折行归并需以真 ID 终点为准，而非空白 token。
- 关联：`tests/test_ab_red_bucket.py` 全绿（见⑤）＝锁族对此形态零覆盖，修时须补三形态锁。

## ⑤ 未尽

- 未修代码（BKT 域所有权）。
- 真机 pytest 对该测试实际摘要行的折行/转义形态未实测（`\u4e71\u8d34` 是否 pytest 原样输出＝unknown；BASE-2 册子本身已存转义文本）。
- `pytest tests/test_ab_red_bucket.py -q`＝**9 passed**（2.16s，实跑，`--basetemp=/tmp/qoder-SPC/bt`）——锁族绿与 bug 并存不矛盾（无空格 ID 用例）。
- BASE-2 其余 183 枚转 FORM 后分桶无扰动（COMMON n=179，函数级归一合并参数变体属预期行为，未逐枚核对）。
