# WebUI 仪表盘规格 v1（对照 AstrBot）+ 架构对照结论

> 依据：用户 2026-09-15 需求（调用统计/Token 四项/延迟/配置在线改/好感度面板）+ AstrBot 实装
> （对照 AstrBot 桌面壳，技术栈与截图清单以该项目文档与本次调研原始件为准）。
> **许可证裁决**：AstrBot 为 AGPL-3.0——交互思路可学，**代码/样式一行不搬**（含其 webui dist 产物）。

---

## 一、AstrBot 对照：我们做得不好的（诚实清单）

| # | 差距 | AstrBot 做法 | 我们现状 | 结论 |
|---|---|---|---|---|
| 1 | **观测面弱** | WebUI 一屏看调用/日志/图表 | 只有聊天命令（/bot status/model/logs）+日志文件 | WebUI v2 主目标 |
| 2 | **配置全靠手编 .env** | 表单化配置+保存即生效/提示重启 | 同上；热改面已诚实化（SETTABLE 41/RESTART 31）但无界面 | v2 Phase B |
| 3 | **统计无聚合面** | 数据与日志页有图表 | audit.sqlite3/ledger/channel_health 数据都在，无聚合查询与展示 | 数据已有，缺的是壳 |
| 4 | 插件市场/热插拔 | 插件市场+MCP+开关 | 单体内聚（能力注册表 C-06 声明源），无三方插件体系 | **有意取舍不追**——单人自用 bot，插件市场收益为负 |
| 5 | 多提供商注册器网格 | 29 提供商卡片化新增 | axonhub 统一网关 17 渠道（.env 配置） | v2 Phase B 只读展示+片段生成即可 |

**我们不追它追不动/它没有的**（一句话备查）：人格纵深（四层注入/称谓/怪癖）、好感度 v5、记忆反思、门禁与 SSRRF 护栏、渲染契约与机器门、发送队列幂等——这批是守岸人的本体竞争力，照旧。

## 二、数据可用性盘点（规格的诚实前提）

| 需求 | 数据源 | 现状 |
|---|---|---|
| 调用次数（群/私聊/群内用户） | audit.sqlite3 `audit_records`（含 session_id/sender_id/capability） | ✅ 已有，缺聚合 API |
| Token 四项（输入/缓存建/缓存命中/输出） | llm/providers.py response.usage；ledger 计价已支持缓存两类（483f852） | ⚠️ ledger 默认关；需开「记录面」（不计费只记账）或轻量 usage sink |
| 响应延迟 | channel_health.sqlite3 EWMA（model_router 择优在用） | ✅ 已有 |
| 好感度排行榜（**WebUI 显数值，用户已裁定**；聊天内仍定性不显数值） | user_affinity.sqlite3 snapshot | ✅ 已有 |
| 配置在线改 | runtime settings（SETTABLE 键集 set_override+审计；RESTART_REQUIRED 诚实拒绝） | ✅ 机制已有，缺界面 |

## 三、规格

### Phase A：只读仪表盘（先做）
- **壳**：control_plane（8742，Bearer/Host 白名单不变）挂构建产物单文件化 SPA（vite-plugin-singlefile）：Vite 构建输出单个自包含 index.html，挂 control_plane 静态目录；离线可开、零外部 CDN 不变。设计系统打底改用 AxonHub 前端抽取（Apache-2.0，路线 B，见 docs/design/webui-axonhub-adoption.md）+ 守岸人主题 token（brand/wash/mica 同源配色，浅色）。
- **页面五块**：
  1. 总览：bot 在线/版本/运行时长/发送队列深度/告警数（/health+/status 已有）
  2. 调用统计：时间窗（24h/7d/30d）×维度切换——按会话（群/私聊分列）、群内用户 TopN、能力 TopN；趋势折线
  3. Token 面板：四项堆叠图（输入/缓存创建/缓存命中/输出）×时间窗×模型族
  4. 延迟面板：渠道 EWMA 当前值+历史曲线
  5. 好感度：排行榜卡（昵称+数值+档位色阶，截图样式；负值红阶）
- **新后端 API**（control_plane 内，Bearer 后）：`GET /api/stats/calls`、`/api/stats/tokens`、`/api/stats/latency`、`/api/affinity/board`——全部只读 SQL 聚合，参数=time window+limit。
- **前置数据工作**：ledger 开「记录面」（`BOT_LLM_BILLING_ENABLED` 或新增只记账开关），providers.py 把 usage 四项写入 ledger 行（缓存两类 provider 给多少记多少，没有记 0）。

### Phase B：配置在线改（后做）
- SETTABLE 键表单化（键数以 `config.py` 的 `SETTABLE_KEYS` 现算为准）：读 `/api/config`（键+当前值+类型+说明），写 `POST /api/config/{key}` **走 set_override 同一函数路径**（门禁/审计/拒绝语义与聊天侧完全一致）。
- RESTART_REQUIRED 键：只读展示+「生成 .env 片段」复制按钮（诚实：改了要重启）。
- 模型/渠道（.env 类）：Phase B 只读展示+片段生成；表单化编辑留 Phase C。

### Phase C（排队）
- 会话浏览器（history/notes 只读）、日志尾流（logs API）、提醒/订阅管理。

## 四、好感度数值展示边界（记录裁定）

**WebUI 面板直接显示数值**（用户 2026-09-15 裁定）；聊天内侧不变——算法说明定性、好感卡不展示固定加减数值（2026-09-12 实弹裁定④继续有效）。两处口径不同源不冲突：面板是主人观测面，聊天是人格面。
