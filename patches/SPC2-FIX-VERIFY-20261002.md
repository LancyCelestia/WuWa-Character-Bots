# SPC2 工单：ab_red_bucket.py 修后版对 SPC 三失效形态耐性复核（2026-10-02 下午窗）

席 SPC2（复核席，只读＋本工单）。被测件＝主会话修后版（`_flush` 取 `FAILED` 与首个 ` - ` 之间整段＋裸清单输入形态＋回归腿 `test_space_inside_param_tail_is_not_truncated`）。全部实跑贴读数；scratch＝`/tmp/qoder-SPC2/`（run1/2/3.txt＋run1.json，未动 SPC 原证据盘）。

## ① SPC 原样本重放（sampleA vs sampleB；diff 核实恰差 1 行，源＝BASE-2 第 129 行）

- RUN1 A vs B：NEW_ONLY n=0（空）；GONE_ONLY n=1，点名全 ID `…passes[J9 gallery_empty \u4e71\u8d34]` 逐字完整；COMMON n=179；**rc=0**。
- RUN2 B vs A：NEW_ONLY n=1（同一全 ID 原貌），**rc=1**；RUN3 A vs A：rc=0。
- 失效形态「腰斩」：已灭，报告无残 ID；无假 NEW+假 GONE 对。

## ② 折行探针（SPC 假 NEW+GONE 对构造复跑）

- P1 折点恰在 ID 内空格（SPC 原构造）：两轴塌同函数级键（`[J9gallery_empty \u4e71\u8d34]` 仍括号平衡被整组剥掉）⇒ COMMON n=1、new=gone=0、镜像 new_only=0 ⇒ **假对已灭，rc 双向 0**。残留：折侧 params 原貌丢折点空格（`[J9gallery_empty …]`），只损点名观感、不动桶判；docstring 已标此折点病态不保证。
- P2 折点 token 中段：逐字还原，认同一条（COMMON）。
- P3 折点 ` - ` 分隔符前（续行 `- ` 开头）：全 ID 含空格逐字还原，COMMON 1 条。

## ③ 裸清单形态（head-axis-reds-B2.txt 184 行裸 ID 直接当 A 输入）

- extract 184↔184，**全表逐字等值 True**；抽第 1/129/184 三枚 equal=True（含第 129 行含空格枚）。无腰斩。
- 取证注：首轮手写对照串 False＝本席对照串被转义解码（`\u4e71`→乱）的取证工件；repr 复核证实文件行＝字面转义文本、提取保真。非工具缺陷，全表等值才是裁决。

## ④ 锁族＋lint（实跑）

- `pytest tests/test_ab_red_bucket.py -q`＝**10 passed in 3.23s**（`-p no:cacheprovider --basetemp=/tmp/qoder-SPC2/bt`，卫生前缀齐）。
- `ruff check scripts/ab_red_bucket.py tests/test_ab_red_bucket.py`＝**All checks passed!**

## ⑤ 病态合成样（只记录不定论）

- **nodeid 内含 ` - `**：参数尾巴 `test_x[a - b]` ⇒ 截成 `…test_x[a`——残键括号不平衡 ⇒ 函数级键本身被污染，两轴消息异形时可再造假对（比「原貌破」更重一级）；路径段含 ` - ` ⇒ 截成 `tests/d`。docstring 已声明同界；残键不平衡后果供后续权衡（真机参数值含 ` - ` 概率未测＝unknown）。
- **消息续行以 `FAILED ` 行首**：认成新条目 ⇒ 幻影 ID `means red` 入桶（`_flush` 无在册校验）；单轴在场即假 GONE/NEW（实跑 gone=[('means red',…)]）。真机 reprcrash 续行是否会出现该形态＝unknown。
- 对照：普通多行消息续行（非关键字开头）并回消息侧，ID 不受扰。

## 判定

三失效形态（腰斩／假 NEW+GONE 对／假 COMMON 吞红前体）修后全部耐过：重放双向、探针、裸清单四腿实跑全过，锁族 10 绿、ruff 绿。⑤两病态属 docstring 已声明边界的延伸后果，只登记不裁。
