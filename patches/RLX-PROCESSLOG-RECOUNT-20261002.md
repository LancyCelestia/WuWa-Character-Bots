# RLX 工单 — 过程件卫生复点（2026-10-02 下午窗）

席 RLX · 只读复点 · 全程零 git 写 / 零进程动作 / 零配置改 · 置信度＝verified（实跑）

## ① 三计数对照（现算 vs HB-C 当时值）

| 计数 | HB-C 当时值 | 现算 | 判定 |
|---|---|---|---|
| `ls docs/design \| wc -l` | 242 | **242** | 一致，零漂移 |
| `ls docs/design/*-log.md \| wc -l` | 126 | **126** | 一致，零漂移 |
| `ls docs/*.md \| wc -l` | 36 | **35** | −1，见下取证 |

docs 根 −1 取证：`git ls-files ':(glob)docs/*.md'`（tracked）＝35，与工作区 diff 零差异、`git status docs/` 无 unstaged 删除 ⇒ **HEAD 本身就是 35**。HB-C 的 36 属当时值口径差（历史读数含一件此后移走的件），非本窗丢失，非违例。

## ② 今日新增扫描（2026-10-02 15:00 后 docs 下 *.md）

命中 2 件，均**非过程件**、属工具链刷新现行册（预期行为，非违例）：
- `docs/auto-facts.md` mtime 2026-10-02 17:24:03 —— 规则 10 指定机器册（生成器写）
- `docs/command-catalog.md` mtime 2026-10-02 17:28:25 —— echo.py 生成目录（生成物）

其余 docs 下（含 docs/design/、docs/boards/）15:00 后零新增 *.md ⇒ 本窗工单确全在 patches/，无误写进 docs/。

## ③ 死账复核

`find docs -name "*-log.md" -newermt "2026-10-01"` ＝ **零命中**。HB-C 判"死账"的 126 枚 *-log.md 自 2026-10-01 起无人再写，死账判定维持。

## ④ 违例点名

**零。** 无过程件误写进 docs/；②的 2 件为机器册/生成物自动刷新，不属过程件违例，不删不移。

## ⑤ 结论

过程件纪律干净：design 242/126 与 HB-C 完全一致，死账 126 枚维持，本窗违例 0；docs 根 36→35 为 HB-C 当时值口径差（HEAD 实为 35），建议后续读数以 35 为新基线。
