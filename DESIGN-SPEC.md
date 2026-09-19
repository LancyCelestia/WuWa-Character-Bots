# 设计规范 · 执行规范 · 验证规范（根部钉死版 v2 · vis4 层次化升级）

> **身份**：本文件是全项目视觉与质量规范的**唯一根部入口**，被 `tests/verify_hashes.py`
> 纳入 SHA-256 清单——任何修改都必须有意识地重新记录（`--write`），"改了 A 忘了 B"在门禁处现形。
> **牵一发自动全改的机制**：所有视觉值钉在
> `plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py`（token 单一事实源；
> v21r2 重组真身路径，`output/card_render/` 为一一对应兼容垫片），
> 模板只允许 `var()`/注入引用，禁止出现表外值——改 token 一处，全部模板自动生效；
> 机器清单类事实由 `scripts/doc_sync.py --write` 从代码整册重生成（`docs/auto-facts.md`）；
> 命令与触发词变更由 `python scripts/command_catalog.py --write` 联动目录与文档。

## 一、设计规范（视觉铁律 v2，全 HTML 模板遵守）

1. **釉瑚云母基底（VIS1 2026-09-20 多色交织版）**：外壳=雾底打底 + **wash-1/2/3 与 `--wash-blob-1` 平台混入色四相回绕交织的 145deg 七色标渐变**（单源 `theme_tokens.SHELL_WASH_GRADIENT`，混入比 55–72% 档=06 基准上浮，全 11 面经 `--mica-shell-wash` 注入跟随）+ **不透明近白托底层**（禁止半透明壳直接叠深色聊天窗）；平台色 `--accent` 只作 accent（徽章/高亮/图标），不作大面积底色（blob-1 通道等效 accent 覆盖 ≤35% 数值锁不动）。
2. **双色交融**：圆角色块以 `color-mix` 混入 accent/wash 成"粉里透蓝、蓝里透粉"质感、禁止纯色死块，**常用档 7–10%**——混入比当前为构图目验项、**无机器门**（面上已存在 12%/28% 等功能性变体，如 echo 标题带 `color-mix(... 12% ...)`、universal `.footer-colored`；如需收紧先建门再收面，禁以「一律 7–10%」作拦截宣称，2026-09-20 F24/DOC1b 订正）。
3. **层次化阴影（vis4 升级）**：阴影 token 为**三级分级族**，全模板只能 `var()` 引用、禁止自造一次性阴影——
   - L3 `var(--mica-shadow)`：外壳（深投影 + wash 染色）；
   - L2 `var(--mica-shadow-panel)`：面板级大件（摘要块/页脚胶囊/热评卡容器）；
   - L1 `var(--mica-shadow-soft)`：瓦片级小件（指标卡/评论条/头像）。
   相邻层级必须可辨：外壳 > 面板 > 瓦片，一眼看出"谁浮在谁上面"。
   **两级/三级不对称现状（2026-09-19 登记，2026-09-20 复核仍在位）**：4 张 f-string 直拼卡的公共段只注入 `--mica-shadow`/`--mica-shadow-soft` 两级（`tests/test_mica_builders_contract.py::test_exactly_two_shadow_token_definitions` 钉死），L2 panel 档现仅 7 张 Jinja 模板经 bridge 上下文消费；「全模板三级族」宣称对直拼卡不成立，升三级或显式登记两级豁免待裁（豁免册=契约 §八 E-12）。
4. **辉光与深色遮罩**：以 `var(--glow-accent)`（radial 光晕，alpha≥0.05）作**背景层**叠加在关键容器上（页脚胶囊/标题引言），不占用阴影 token 通道。深色遮罩**应**消费 **OVERLAY 四员登记值**（`scrim_badge`/`scrim_banner`/`scrim_code`/`scrim_media`，v21r3 C5 入册，逐值以 `theme_tokens.py` 为准）；四员值册与注入面有锁、**面扫零断言**——「表外深色遮罩禁止」现为规范承诺，新增暗 rgba 不触任何门（债项 D-2 与补门设计见 `docs/rendering-contract.md` §八，2026-09-20 F24/DOC1b 订正）。
5. **区分线**：分隔一律 `var(--divider-line)`（平台色 22% 清晰细线），替代一切淡到看不见的 14% 线。
6. **高区分度色块**：相邻色块/胶囊/矩阵瓦片底色必须取**三档表面 zebra 交替**（`--surface-a` 淡蓝 wash-1 派生 / `--surface-b` 星空紫 wash-2 派生 / `--surface-neutral` 中性白）——**只用守岸人本命色系（淡蓝/星空蓝/星空紫），不用平台 accent**；zebra 表面仍是液态玻璃（内高光描边保留、漂移色斑透出），云母质感不丢。**vis5 数值门**：三档表面叠本命洗后相邻可辨——ΔE(a,b)≥3.0、对 neutral ≥2.5（旧值 ΔE(a,b)=0.81 不可辨，2026-09-13 调参为对称合成 alpha≈0.83 的高混色档），机器门 `test_template_visual_audit.py::test_zebra_surfaces_distinct`。**玻璃两档（v21r3 C3）**：白玻璃只允许 GLASS_MAIN（0.66→0.44）与 GLASS_FOOT（0.66→0.46）两档 + 边缘描边 0.95/0.35/0.72，散值（0.68/0.55/0.60/0.50/0.52 等）按 `docs/design/v21r3-render-closing-spec.md` 归一映射收敛；**语义色五色单源（C4）**：DANGER=#d54941 / SUCCESS=#2e9e6b / WARNING=#b07d1a / SCORE_HOT=#157347 / SCORE_COLD=#b42334，finance/market `--up/--down`、usage/debug `good/bad`、affinity `--score-*` 一律消费语义 token，禁止卡私红绿黄。
7. **全卡统一字体/对齐/尺寸**：**字号下限 12px**（机器门 gate04+builders 锁 ≥12px 全 11 面；v21r3 C8 收口已在 7 张 Jinja 模板面落地（11/11.5/12.5px→12px、13.5/14.5px→14px，market/finance 脚注同批）；**echo 直拼卡现势仍存 12.5px/14.5px**（`echo.py` `_help_mica_html` 区段，改值或改口径待裁——下限门 ≥12px 不咬故不红，契约 §八 D-5）；echo letter-spacing .14em→.06em、gap 9px→8px 已核实在位）；`TYPE_SCALE_PX` 阶梯为新增/改版模板的选用基准，六张既有卡经实弹验收的展示级字号（26/23/22/17px 等）不受追溯；**次级文字统一 `TEXT_SECONDARY`（#576272），对三档表面 ≥4.5:1**（旧散值 #7a828c/#8a919b/#66727f/#7a8699 最低 2.5:1 不达 AA，已收编；v21r3 C6：legacy 灰 #555/#444/#999 一并收编进 `--text-main`/`--text-secondary`，黑名单门加这三值）；**R 角三层（v21r3 C1）**：外壳只允许 `var(--r-shell)`=30px、面板/瓦片走 `--r-panel`=18/`--r-tile`=14、内径合法集 {4,6,8,12,16}、pill=999px 与圆=50% 为登记特例（迁移映射 28→30、20/24→18、11→12；universal 私设 `--radius-lg/md/sm` 已废除；**VIS1 2026-09-20 统一收口**：7 模板 border-radius 字面量 55 处全量改 `var(--r-*)` 消费、像素等值，唯二改值=universal 标签族 12px 与画像标签 18px 收编为 `var(--r-pill)`（标签=胶囊角色，跨面对齐），mermaid 节点圆角消费 `--r-inner-lg` 不新造档）；**mono 字体单源（C9）**：`MONO_FONT_STACK`（Cascadia Mono/Consolas/JetBrains Mono/Courier New/monospace）唯一，卡内 mono 一律消费公共注入键 `var(--font-mono)`（error_card 内另有局部别名 `--mono-family: var(--font-mono)`，新模板勿再自造别名）；gap 只允许 3/4/6/7/8/10/12/14/16px；**宽度按内容族登记 `CARD_SHELL_WIDTHS`**（v21r3 C10 增补 help:940/usage:900/debug:880/media:640）——**进表真、消费表假**：四处直拼卡调用现以字面量传 `width_px=`（echo 940/debug 880/usage 900/media 640，**改表不跟随**，F14-5），`mica_shell._DEFAULT_SHELL_WIDTH_PX=880` 为未登记第 12 缺省档；收口=调用点改 `CARD_SHELL_WIDTHS[...]` 查表+缺省并表（契约 §八 D-6））；行高只在 {1.0,1.1,1.15,1.2,1.4,1.5,1.6}（v21r3 C7：1.55→1.5、1.65→1.6 收敛，直拼卡纳入门禁）；同类元素高度/宽度/对齐同一模板内必须一致（契约+目验双闸）。
8. **胶囊页脚**：信息全部进胶囊（平台 Logo[全卡同色 var(--accent)] + 媒体 ID[优先 AV 号] + Bot 头像[本地缓存 file URI，白边 2px] + 名字·功能标签[间隔符"·"左右各一空格]）。**全卡覆盖**：usage/账单卡 vis5 起也带 bot 页脚胶囊（此前是唯一无署名卡）；页脚第二槽位口径=功能名优先（feature_label），无功能名回英文品牌词 Shorekeeper（universal/旧媒体卡既有行为）。页脚胶囊/脚带玻璃一律走 **GLASS_FOOT 脚档**（0.66→0.46，v21r3 C3），与主档面板形成层次。
9. **动画**：漂移渐变色斑三枚交错（46/52/58s；v21r3 C2：**全部 11 面恒 3 枚、时长集合恰 {46,52,58}s（a/b/c）**，finance/market/error 补齐第三枚、echo 补齐整层；error 卡 wash_blob_mix=24 既有豁免保持），必须在 `.card` 内；`prefers-reduced-motion` 全部静止（v21r3 C13：关停规则由 `mica_shell._MICA_DECOR_CSS` 单一产出、选择器与动画声明同构——手写关停规则废除，治 finance/market 特异性缺陷）；相位按 payload digest 确定性钉帧（同 payload 同截图字节；v21r3 E1：确定性门覆盖扩至 error/usage/echo/debug 四入口，全 11 面）。
10. **截图契约**：无 `<meta viewport>`；body 透明；元素截图 bbox=卡本体零留白；**兜底 full_page 截图同样带 `omit_background=True`**（v21r3 C12，与元素截图分支对齐，防圆角白角）；失败→纯文本兜底零破坏。
11. **值册-投影-机器门三层（v21r3 立法）**：①**值册唯一**——一切视觉值的唯一登记处是 `theme_tokens.py`（真身 `domains/render/card_render/`），7 张 Jinja 模板、4 张 f-string 直拼卡、WebUI 只准经 `var()`/生成器注入**引用**，不准私设；②**改值只改值册**——任何视觉调整先改 `theme_tokens.py`/`mica_shell.py` 登记值：色斑/装饰层/玻璃规则已经 `mica_shell` 生成器单源通水（模板自动生效）；**壳层 wash 渐变（145deg）与壳级 150deg 描边已于 VIS1（2026-09-20）收口**——值册 `SHELL_WASH_GRADIENT` 单源，7 模板改 `var(--mica-shell-wash)`+`var(--mica-glass-edge)` 消费、`shell_base_css` 内插登记常量，模板侧壳级手抄=0（原 11 份对象收口；残余手抄=瓦片白玻璃双背景字面量六处，被 `test_list_tiles_keep_glass_surface` 字面取相锁阻挡，收口方案=契约 §八 D-9 待裁；affinity 内联 zebra 描边 7 处已改 var() 消费=E-7 失效收编）；③**值册变更必须重录哈希**——`theme_tokens.py`、模板、`DESIGN-SPEC.md`、`docs/rendering-contract.md` 在 `verify_hashes.py` 清单内，值册或模板改动后跑 `--write` 重录（由收尾席统一执行，改文件的席位不得自行 `--write`）；④**任何新视觉先入册后引用**——新色/新圆角/新遮罩/新字体栈一律先进值册登记（含豁免项显式登记，如 error `wash_blob_mix=24`），再在模板消费；表外值由机器门一票否决。四环缺一即「漂移回潮」。

## 二、执行规范（改模板/改规范/改代码的标准动作）

1. 改任何模板/token 前先读本文件与 `docs/rendering-contract.md`；
2. 改完跑门禁（门族 ≥8 件，v21r3 后已扩面，2026-09-20 订正）：`tests/test_rendering_contract.py` + `test_mica_builders_contract.py` + `test_v21r3_visual_gates.py`（九门×11 面）+ `test_token_supply_chain.py`（供给链六门）+ `test_template_visual_audit.py` + `test_e03_typography.py` + `test_phase_determinism.py`/`test_phase_determinism_2.py` + `test_mica_shell.py`（另 `test_error_card_contract.py` 覆盖错误卡）；
3. **视觉交付物变了必须重录哈希**：`python tests/verify_hashes.py --write`（`--check` 模式已进 pytest 常驻门）；
4. 同类内容**必须走同一实现**：新卡不新写 CSS——优先复用 `--surface-*`/`--mica-shadow-*`/`--glow-accent`/`--divider-line` 与既有 class；确实要新样式，先在 theme_tokens.py 立 token 再引用；
5. 大改用 `scripts/measure_latency_chains.py` + 样本渲染截图目验；
6. 机器事实变了跑 `python scripts/doc_sync.py --write`；命令/触发词变了跑 `python scripts/command_catalog.py --write`。doc_sync `--check` 已进 pytest 常驻门（`test_cross_validation_gates.py`）；command_catalog 的 `--check` **尚无 pytest 常驻 subprocess 锁**（现靠帮助注册表一致性测试族+autosync 钩子+人肉执行——要宣称「常驻」先补锁再改词，F24 对账 H6/X4，2026-09-20 订正）。

## 三、验证规范（门禁矩阵与交叉验证方法）

| 层 | 门 | 位置 |
|---|---|---|
| 视觉结构 | 渲染契约（token 族/阴影分级/gap/行高/viewport/字重/字号下限） | tests/test_rendering_contract.py 等 8 族（清单见 §二.2） |
| 字节漂移 | 交付物 SHA-256 清单（项数见 `docs/auto-facts.md`「哈希清单范围」行，现 19） | tests/verify_hashes.py --check（pytest 常驻） |
| 热路径性能 | 路由吞吐/导入时长数量级 | tests/test_perf_regression.py（pytest 常驻；实名带 test_ 前缀，缺前缀则 pytest 不收集） |
| 文档事实 | 机器册与代码互证 | scripts/doc_sync.py --check（pytest 常驻） |
| 全量回归 | 用例数以最近一次 `dev.ps1 -Task test` 实跑为准，本文件不转录 | scripts/dev.ps1 -Task test |
| 交叉验证 | 双引擎各自全量、结果互证 | python tests/cross_validate.py |
| 自动同步 | `BOT_AUTOSYNC=1` 时 session 级钩子静默 `--write` 修漂移（人无感；失败仅 warning，由上两行门兜底报红） | tests/conftest.py `_autosync_session_gate` |

**交叉验证方法**：`python tests/cross_validate.py` 先后以「默认引擎」与「隔离引擎」（独立 basetemp、禁缓存、PYTHONDONTWRITEBYTECODE=1）各跑一遍，两组结果逐项比对——同一次提交在两种环境下必须同绿/同红，不一致即环境耦合缺陷。全量两遍约 5–6 分钟，用于提交前/大改后，不进单测门。

**诚实边界**：本文件的中文叙述是规范承诺，机器只锁三样——哈希清单内的文件字节、性能阈值的数量级、机器册里能从代码推导的清单类事实。叙述与实现冲突时，以测试门禁的实际断言为准并回来改本文件（改本文件=有意 --write 重录哈希）。
