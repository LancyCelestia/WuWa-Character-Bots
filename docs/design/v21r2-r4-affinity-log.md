# v21r2 R4 席工作日志 — 好感度算法族 v6 平滑层（2026-09-17）

## 任务

用户反馈好感度「涨和跌太快了」，裁定换更智能的算法，**不能单调武断地直接加减
对应数值**。在保留全部既有约束（-100..+100、8 档温和过渡、定性展示绝不显数值、
任何档位不攻击、拒答≠辱骂、V2.1 滚动预算、source_event_id 幂等）的前提下，
设计并落地 v6 平滑层。

## 算法设计

v5 多因素线性步长在中段手感正确，问题在两端：步长与「距极端还有多远」无关，
一串同向信号能以恒定速率把印象直推到顶底。v6 在 v5 线性步长之后串联三道非线性
平滑机制（方向一致：都只让 |Δ| 变小，无互相反转；中段首次信号与 v5 字节级一致）：

1. **饱和响应曲线（空间维度）**——`saturation_factor(affinity, direction)`：
   取方向上距边界剩余空间 `remaining`（正向=1−a，负向=a+1），
   `t = clamp(remaining / 0.25, 0, 1)`，保留比例 = `t²(3−2t)`（smoothstep）。
   - 带宽 0.25（内部值）= §4 一个档宽（展示 25 分）：中段六档恒为 1（v4/v5
     线性语义原样）；两端最外档（|展示分|≥75）内单调收窄；边界处恰为 0
     （行为路径渐近逼近极端、永不击穿 [-1,+1]）；smoothstep C1 连续无折点，
     与 §4「绝不在门槛上生硬跳变」同构。
   - 方向性：只收窄「朝边界」的步长，「向中段回归」全额（纠偏不钝化）。
   - 选 smoothstep 而非全程 tanh 的理由：带宽外严格恒等，v5 中段校准与
     既有测试零漂移；tanh 会在友善档就开始压缩、改变全局手感且打破更多契约。
2. **边际递减（时间维度）**——`repeat_decay_factor(n) = max(0.2, 0.6^n)`，
   n = 同一自然日此前**同类型**行为事件次数（复用 `day_counters` 跨日清零）。
   正负对称：刷好感/刷负分都随重复迅速失味；下限 0.2 保证真实持续信号仍能
   缓慢表达，没有「第 N 次后完全免疫」的武断断点。
   - override（管理员/poke）为权威信号：不饱和、不递减，只过预算（既有语义）。
3. **日节奏硬帽（总量维度）**——不新增第二套预算，复用 V2.1 §2.3 滚动预算
   即「正负分开计帽」：单事件负 ≤1 分、6h 损失 ≤2 分、24h 损失 ≤4 分、
   24h 增益 ≤3 分；增益/损失独立聚合互不挤占；纯时间窗（重启/跨午夜/切群
   不重置）。可观测保证：单日净上行 ≤ 增益帽、净下行 ≤ 损失帽。
4. **平滑回归**——既有惰性回归原样（`_PASSIVE_DECAY_ENABLED` 政策门，缺省关），
   v6 不引入第二套回归；饱和带作用于事件步长、回归作用于闲置时间，路径不同。

## 参数表（单一事实源：character/affinity.py 顶部）

| 常量 | 值 | 含义 |
|---|---|---|
| `_SATURATION_BAND` | 0.25 | 饱和带宽（内部值）= §4 一个档宽（展示 25 分） |
| `_SAME_SIGNAL_DECAY` | 0.6 | 同日同类信号重复衰减底数（0.6^n） |
| `_SAME_SIGNAL_DECAY_FLOOR` | 0.2 | 递减下限（长尾保留最小表达） |

无新增 config 键：全部 affinity 数值历来以模块常量注册（docs/affinity-design.md
为唯一权威），与既有惯例一致，避免与并行席位争抢共享的 config.py。

## 改动清单

- `plugins/bot_unified_runtime/character/affinity.py`：
  - 新增 `saturation_factor` / `repeat_decay_factor` 纯函数 + 三常量（§v6 注释指向规范）；
  - `effective_delta` 增加 `repeat_index: int = 0` 形参，因子路径末尾乘
    饱和 × 递减（override 分支原样直返）；docstring 更新 v6 语义；
  - `_observe` 非 override 分支传 `repeat_index=used`（当日此前同类行为次数）；
  - 模块 docstring 补 v6 口径。
- `plugins/bot_unified_runtime/capabilities/affinity.py`：`ALGORITHM_TEXT` 动态
  规则句更新为定性口径（边际递减一次比一次轻 / 刻意讨好贬低刷不出名分 /
  走向尽头自然放缓渐渐钝住不猛冲顶底）；模块 docstring 补 v6。
- `docs/affinity-design.md`：append 附录 v6 章节（v6.0 动机/总原则、v6.1 曲线、
  v6.2 递减、v6.3 帽、v6.4 回归、v6.5 展示纪律、v6.6 常量表、v6.7 验收），
  未改写任何历史章节。
- `tests/test_affinity_v6_smoothing.py`（新建，24 例）：曲线单调/带外恒等/
  边界归零/半带宽中点/越界防御、方向不对称、递减日程与单调弱化、店级重复
  赞美步长非增、店级重复辱骂受帽约束、递减按日重置（滚动预算不重置对照）、
  单日净增益/净损失不破帽、正负帽互不挤占、行为路径不击穿边界、预算/幂等/
  冷却存活、override 权威、七类非关系 reason_code 零计分不回归、惰性回归
  不回归、算法文案定性无数字（含 "+2/-5/0.6/0.2/3 分/4 分/1 分/%" 黑名单）。
- `tests/test_affinity_numerical.py`：`test_linear_steps_stay_full_near_extremes`
  → `test_saturation_tapers_steps_near_extremes`（带外全额 + 带内收窄 + 边界归零）；
  `test_linear_observe_paths` u3 按 `saturation_factor` 给出期望、u4 硬钳制
  改由 override 路径验证（行为路径在边界已钝化为 0，这正是 v6 目标行为）；
  legacy 0.8 行步长按饱和口径更新；文件头口径更新。
- `tests/test_affinity.py`：`test_effective_delta_is_linear` →
  `test_effective_delta_linear_in_midband_saturated_at_extremes`（中段全额
  样本 + 带内收窄 + 边界归零 + override 直返）。

## 实跑证据

解释器 `ChatBot_Runtime/venv/Scripts/python.exe`，env `PYTHONDONTWRITEBYTECODE=1
PYTHONUTF8=1 BOT_AUTOSYNC=0`，`--basetemp=$TEMP/v21r2-r4 -p no:cacheprovider`：

1. 全 affinity 族 + poke + 间接消费方（perf_p3 / persona_prompt_and_memory）：
   `150 passed in 12.50s`。
2. 浸泡并发异常风暴（test_soak_growth::test_affinity_store_survives_concurrent_exception_storm）：
   `1 passed in 7.67s`。
3. ruff（5 个改动文件）：`All checks passed!`。
4. mypy `--explicit-package-bases`（character/affinity.py + capabilities/affinity.py）：
   本域 0 错；报告的其余 14 错全部位于 control_plane 在飞批文件，与本席零交集。

## 中途修正记录

- `test_store_same_day_repeated_insult_tapers_inside_loss_budget` 首版断言
  「前两步各顶帽」错误：steps[0] 本身就是第 2 击的落点（values[0] 才是第 1 击），
  第 2 击后 6h 预算耗尽、第 3 击起记 0——按真实轨迹修正断言（修正后全绿）。
- `test_decay_resets_next_day_while_budget_rolls` 首版断言比较的是好感**水位**
  （任何正步长都成立，无鉴别力）——改为比较相邻**步长**（次日首击步长 > 当日
  末次递减步长），并移除误入的 walrus 表达式。
- 首版惰性回归测试时钟起点（1_000_000）与 `_seed_row` 播种时间戳（1000）不对齐，
  闲置天数漂移——时钟起点改 1000.0 对齐。
- ruff：import 排序自动修复；`zip(values, values[1:])` → `itertools.pairwise`
  （RUF007）；删除未用变量（F841）。

## 遗留与边界声明

- 递减在店级可观测面常被预算先咬合（预算帽更紧）：0.6^n 的独立形态由纯函数
  锁定，店级锁「步长非增 + 帽不破」的组合性质——这是设计意图（纵深防御），
  非缺陷。
- 30 连骂全落在 6h 窗内时先触 6h 帽（2 分）而非 24h 帽（4 分）——更紧窗口先咬合，
  测试按真实口径断言，并另用跨 6.5h 时间线验证 24h 帽同样咬合。
- poke 通道走 `observe_points`（override 权威信号），不饱和不递减，由其专项
  24h 预算（默认 0.5 分）约束——v21.1 既有裁定，本席未改。
- 未 commit（共享工作树，提交裁决权在用户）；生产未重启，v6 生效待重启。
- 本席未触碰 config.py / docs/config-catalog-full.md（无新增配置键，见上）。
