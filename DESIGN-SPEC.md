# 设计规范 · 执行规范 · 验证规范（根部钉死版 v2 · vis4 层次化升级）

> **身份**：本文件是全项目视觉与质量规范的**唯一根部入口**，被 `tests/verify_hashes.py`
> 纳入 SHA-256 清单——任何修改都必须有意识地重新记录（`--write`），"改了 A 忘了 B"在门禁处现形。
> **牵一发自动全改的机制**：所有视觉值钉在
> `plugins/bot_unified_runtime/output/card_render/theme_tokens.py`（token 单一事实源），
> 模板只允许 `var()`/注入引用，禁止出现表外值——改 token 一处，全部模板自动生效；
> 机器清单类事实由 `scripts/doc_sync.py --write` 从代码整册重生成（`docs/auto-facts.md`）；
> 命令与触发词变更由 `python scripts/command_catalog.py --write` 联动目录与文档。

## 一、设计规范（视觉铁律 v2，全 HTML 模板遵守）

1. **釉瑚云母基底**：外壳=雾底打底 + wash-1/2/3 对角透色 + **不透明近白托底层**（禁止半透明壳直接叠深色聊天窗）；平台色 `--pc` 只作 accent（徽章/高亮/图标），不作大面积底色。
2. **双色交融**：所有圆角色块用 `color-mix` 把 `--pc` 与 wash 色各 7–10% 混入白底——"粉里透蓝、蓝里透粉"，禁止纯色死块。
3. **层次化阴影（vis4 升级）**：阴影 token 为**三级分级族**，全模板只能 `var()` 引用、禁止自造一次性阴影——
   - L3 `var(--mica-shadow)`：外壳（深投影 + wash 染色）；
   - L2 `var(--mica-shadow-panel)`：面板级大件（摘要块/页脚胶囊/热评卡容器）；
   - L1 `var(--mica-shadow-soft)`：瓦片级小件（指标卡/评论条/头像）。
   相邻层级必须可辨：外壳 > 面板 > 瓦片，一眼看出"谁浮在谁上面"。
4. **辉光**：以 `var(--glow-accent)`（radial 光晕，alpha≥0.05）作**背景层**叠加在关键容器上（页脚胶囊/标题引言），不占用阴影 token 通道。
5. **区分线**：分隔一律 `var(--divider-line)`（平台色 22% 清晰细线），替代一切淡到看不见的 14% 线。
6. **高区分度色块**：相邻色块/胶囊/矩阵瓦片底色必须取**三档表面 zebra 交替**（`--surface-a` 淡蓝 wash-1 派生 / `--surface-b` 星空紫 wash-2 派生 / `--surface-neutral` 中性白）——**只用守岸人本命色系（淡蓝/星空蓝/星空紫），不用平台 accent**；zebra 表面仍是液态玻璃（内高光描边保留、漂移色斑透出），云母质感不丢。
7. **全卡统一字体/对齐/尺寸**：字号只允许 `TYPE_SCALE_PX` 阶梯（display26/title20/body15/label13/caption12）；R 角 30-18-14；gap 只允许 3/4/6/7/8/10/12/14/16px；行高只在 {1.0,1.1,1.15,1.2,1.4,1.5,1.6}；同类元素高度/宽度/对齐同一模板内必须一致（契约+目验双闸）。
8. **胶囊页脚**：信息全部进胶囊（平台 Logo[全卡同色 var(--pc)] + 媒体 ID[优先 AV 号] + Bot 头像[本地缓存 file URI，白边 2px] + 名字·功能标签[间隔符"·"左右各一空格]）。
9. **动画**：漂移渐变色斑三枚交错（46/52/58s），必须在 `.card` 内；`prefers-reduced-motion` 全部静止；相位按 payload digest 确定性钉帧（同 payload 同截图字节）。
10. **截图契约**：无 `<meta viewport>`；body 透明；元素截图 bbox=卡本体零留白；失败→纯文本兜底零破坏。

## 二、执行规范（改模板/改规范/改代码的标准动作）

1. 改任何模板/token 前先读本文件与 `docs/rendering-contract.md`；
2. 改完跑门禁：`tests/test_rendering_contract.py + test_mica_builders_contract.py + test_template_visual_audit.py + test_e03_typography.py + test_phase_determinism.py`；
3. **视觉交付物变了必须重录哈希**：`python tests/verify_hashes.py --write`（`--check` 模式已进 pytest 常驻门）；
4. 同类内容**必须走同一实现**：新卡不新写 CSS——优先复用 `--surface-*`/`--mica-shadow-*`/`--glow-accent`/`--divider-line` 与既有 class；确实要新样式，先在 theme_tokens.py 立 token 再引用；
5. 大改用 `scripts/measure_latency_chains.py` + 样本渲染截图目验；
6. 机器事实变了跑 `python scripts/doc_sync.py --write`；命令/触发词变了跑 `python scripts/command_catalog.py --write`——两者 `--check` 均已进 pytest 常驻门。

## 三、验证规范（门禁矩阵与交叉验证方法）

| 层 | 门 | 位置 |
|---|---|---|
| 视觉结构 | 渲染契约（token 族/阴影分级/gap/行高/viewport/字重/字号下限） | tests/test_rendering_contract.py 等 5 族 |
| 字节漂移 | 交付物 SHA-256 清单（12 文件） | tests/verify_hashes.py --check（pytest 常驻） |
| 热路径性能 | 路由吞吐/导入时长数量级 | tests/perf_regression.py（pytest 常驻） |
| 文档事实 | 机器册与代码互证 | scripts/doc_sync.py --check（pytest 常驻） |
| 全量回归 | 4500+ 用例 | scripts/dev.ps1 -Task test |
| 交叉验证 | 双引擎各自全量、结果互证 | python tests/cross_validate.py |
| 自动同步 | `BOT_AUTOSYNC=1` 时 session 级钩子静默 `--write` 修漂移（人无感；失败仅 warning，由上两行门兜底报红） | tests/conftest.py `_autosync_session_gate` |

**交叉验证方法**：`python tests/cross_validate.py` 先后以「默认引擎」与「隔离引擎」（独立 basetemp、禁缓存、PYTHONDONTWRITEBYTECODE=1）各跑一遍，两组结果逐项比对——同一次提交在两种环境下必须同绿/同红，不一致即环境耦合缺陷。全量两遍约 5–6 分钟，用于提交前/大改后，不进单测门。

**诚实边界**：本文件的中文叙述是规范承诺，机器只锁三样——哈希清单内的文件字节、性能阈值的数量级、机器册里能从代码推导的清单类事实。叙述与实现冲突时，以测试门禁的实际断言为准并回来改本文件（改本文件=有意 --write 重录哈希）。
