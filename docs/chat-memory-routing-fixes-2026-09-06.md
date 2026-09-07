# 聊天完整度与记忆路由修复（2026-09-06）

## 本轮交付边界

用户已经确认 QQ 实机纯文本、图片接收后回复可用。本轮不再重复付费 smoke、不推送 Git、不修改人格和世界观源文件，不把本地测试等同于真实供应商验收。

### 已实现

- 记忆抽取复用主聊天 ModelRouter 的注册表、凭据引用和路由策略，读取运行时模型覆盖；独立调用状态不污染聊天的诊断记录。这里是复用路由配置，并非保证每次抽取恰好使用上一条回复的同一个供应商。
- 修复动态注册表 env:KEY 从 Config 解析的缺口；优先级归一化保留简称和多枚备用凭据。同一模型可尝试显式配置的备用 key，未开放认证失败后任意跨模型降级。
- 自动抽取采用独立超时、输出上限、单任务并发限制和失败冷却。忙碌时跳过可选抽取；失败不阻塞正常聊天，日志不回显原始鉴权异常内容。
- 详细回答策略要求说明结论、身份、组织与人物关系、关键事件和资料缺口，移除“一两句定性”的冲突规则。不要求凑字数，不允许用虚构事实补齐资料。
- 修复 reply_detail 配置未传入能力构造的问题，以及关闭正文抓取时搜索结果未进入回答上下文的问题。
- 模型 priority 采用 1..N 连续唯一槽位；移动/新增/修改后其他项顺移，越界位置收敛到首尾。路由优先级为手动指定 > 生效时段组顺序 > 基础 priority。
- 文本帮助和帮助卡片共用说明已同步，涵盖详细模式、模型候选与实际调用的区别、抽取参数和安全凭据配置。未修改卡片样式，未做截图视觉验收。

## 重启与低成本验收

只重启当前运行的机器人，不要另启第二个同账号进程。管理员私聊执行：

```text
/bot reply 详细
/bot runtime get BOT_REPLY_DETAIL
/bot runtime get BOT_CHAT_MAX_TOKENS
/bot runtime set BOT_CHAT_FAST_MODE false
/bot help 回复
/bot help 设置
/bot help 模型
/bot model list
```

本轮本地 .env 配置为详细模式、关闭快速模式，普通及快速输出上限均为 8192。8192 是预算上限而非目标字数；实际输出越多费用可能越高。运行时覆盖优先于 .env，请以上述 get 结果为准。完成知识验收后可按需调回 4096。

```text
/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15
/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200
/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300
/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false
/bot model priority <注册ID> 1
```

最后两条分别用于暂停自动抽取、省去额外模型调用，以及移动模型到基础首位；按需执行。暂停不删除已有记忆。启动时已启用抽取的实例可用 true 恢复；若启动配置就关闭了抽取，当前 writer 不会构建，必须先在本地启用并重启，不能仅靠热设置创建 writer。记忆总开关、数据库路径和真实 provider 也必须满足构建条件。

`model list` 查看候选模型及配置，不证明上一条回答实际由该供应商完成。`/bot llm` 会新发一次诊断请求，可能收费，本轮未执行。不要把真实 key 发到聊天里。

建议只选一个人物测试：“请说明其身份、所属组织、与相关人物的关系和关键事件；区分有依据的事实与资料不足。”核对本地知识来源，而不是以篇幅判定检索正确。自动抽取开启后，在一次有可记忆信息的正常聊天后观察日志：无 401 不等于必然写入，抽取也可能返回空。所有配置 key 都失效时仍可能鉴权失败，这不是路由修复能替代的凭据修复。

## 验证证据

- `scripts/dev.ps1 -Task test`：309 passed，1 条上游 Mail/Pydantic 弃用警告。包含路由复用、备用凭据、冷却、详细策略、搜索上下文、优先级、视觉链路和帮助说明回归。
- `git diff --check`：退出码 0；有行尾转换提示，没有空白错误。
- `scripts/dev.ps1 -Task lint`：最新已通过。pricing.py / usage_monitor.py 的 6 项静态问题已做机械修复。
- `scripts/dev.ps1 -Task runtime-layout`：未通过。源码 data 目录含运行产物，检测到 156 个 Python 缓存路径。未删除数据库或其他活动数据；清理迁移另做。
- `scripts/dev.ps1 verify`：docs/plugin/test/lint 均通过，但 mypy 仍因项目既有跨文件类型问题失败（25 errors / 13 files）；本轮新增 mediawiki 类型问题已修复。
- 本轮没有调用真实付费 LLM、没有重新执行 NapCat 实机测试、没有 Git push，也没有制作新的完整归档备份。

## 尚未完成 / 后续 TODO

- [ ] 用户重启后验证真实记忆抽取鉴权、持久化及人物关系回答质量。
- [ ] 记忆抽取从启动关闭状态完全热启用，以及更细的同模型/跨模型故障转移策略。
- [ ] 上一条回答实际模型、供应商、知识命中证据的稳定可观测展示。
- [ ] 视觉模型简称、默认思考强度等全部参数在实际生成链路生效，完成与文本模型命令和 help 的全面对齐。
- [ ] Mail 实际账号连接和 TimeoutError 排查；当前单元测试不能证明真实邮箱服务可达。
- [ ] 人格 Prompt 重构与审批、结构化世界观/关系检索、长期记忆安全写入、群聊公共状态；不得擅自改人格源文件。
- [ ] PromptExecutionGate 接入真实调用链及完整发模前审批；已有预览/审计不等于已强制拦截。
- [ ] 长文档生成等专用 LLM、文件 API 副作用与所有边缘能力的统一边界复核；不得把主聊天通过等同于全部能力验收。
- [ ] lint 遗留、源码缓存与 data 运行产物的安全清理迁移。
- [ ] 干净可发布版本的依赖整理、复制校验与归档备份。历史局部提交不代表完整发行包；继续禁止 Git 推送，除非用户另行授权。


## 2026-09-06 群聊、维基与视频解析补丁

- [complete] 聊天输出仅在整条回复被同一对话引号包住时去除外层引号；回复内部引用保持不变，OneBot 群聊出站仍为纯文本段。
- [complete] MediaWiki 查询先做精确标题 API 查询，再对 opensearch 结果做标题相似度门槛；无关候选不再直接返回。
- [complete] 梗搜索要求结果文本确实包含查询词，去重 URL，标题与摘要合并，减少热门但无关页面进入上下文。
- [complete] Downloader 在交给 yt-dlp 前验证 Netscape Cookie 行；发现非法文件时跳过整个 Cookie 文件且只记录文件名，不改写、不输出 Cookie 内容。
- [complete] `backend-smoke` 是离线 static provider 测试；其返回 `ok=true`、`receipt_state=sent`，现在回复明确标注“未调用外部模型”。
- [complete] lint 从原有 6 项问题修复为通过。

本补丁仍不能替代真实 Wikipedia/梗来源可达性、有效 Cookie、NapCat 实机或真实模型验收。

## 后续修正优先级
2026-09-06 22:40 后的实测续修请以 `docs/live-chat-followup-2026-09-06.md` 为准：本页之前关于只去整条引号、无效 Cookie 整份跳过、Wiki 标题相似度和 mypy 未修完的描述为历史状态。
