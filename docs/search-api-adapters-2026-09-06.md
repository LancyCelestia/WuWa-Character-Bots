# 搜索 API 适配与本地配置

> 日期：2026-09-06
> 运行目标：Tavily 主搜索，You.com 与 LangSearch 顺序回退，TinyFish 用于正文抓取；Bing 不进入新的 API 链。

## 安全边界

- API key 仅放在本地 `.env` 或 `.env.prod`，不进入 Git、日志、聊天文本或知识库。
- `BOT_WEB_SEARCH_ENABLED=false` 时不会创建任何 API 请求。
- 未配置对应 key 的 provider 会从链中跳过；全部未配置时联网搜索返回空结果，聊天仍可继续。
- 外部搜索结果是不可信上下文；聊天能力继续使用现有注入检查、来源 URL 和审计标签。

## 基础配置

```env
BOT_WEB_SEARCH_ENABLED=true
BOT_WEB_SEARCH_PROVIDER=tavily
BOT_WEB_SEARCH_FALLBACK_PROVIDERS=["you","langsearch"]
BOT_WEB_SEARCH_TIMEOUT_SECONDS=6
BOT_WEB_SEARCH_MAX_RESULTS=5
BOT_WEB_SEARCH_FETCH_TIMEOUT_SECONDS=15
BOT_WEB_SEARCH_FETCH_MAX_CHARS=3000

BOT_SEARCH_TAVILY_API_KEY=<local secret>
BOT_SEARCH_YOU_API_KEY=<local secret>
BOT_SEARCH_TINYFISH_API_KEY=<local secret>
BOT_SEARCH_LANGSEARCH_API_KEY=<local secret>

BOT_WEB_SEARCH_TAVILY_API_KEY=env:BOT_SEARCH_TAVILY_API_KEY
BOT_WEB_SEARCH_YOU_API_KEY=env:BOT_SEARCH_YOU_API_KEY
BOT_WEB_SEARCH_TINYFISH_API_KEY=env:BOT_SEARCH_TINYFISH_API_KEY
BOT_WEB_SEARCH_LANGSEARCH_API_KEY=env:BOT_SEARCH_LANGSEARCH_API_KEY
```

## Endpoint 与请求覆盖

所有 endpoint 都可以按供应商账户、地区或版本自行覆盖：

```env
BOT_WEB_SEARCH_TAVILY_ENDPOINT=https://api.tavily.com/search
BOT_WEB_SEARCH_YOU_ENDPOINT=https://api.you.com/v1/search
BOT_WEB_SEARCH_LANGSEARCH_ENDPOINT=https://api.langsearch.com/v1/web-search
BOT_WEB_SEARCH_TINYFISH_ENDPOINT=
BOT_WEB_SEARCH_TINYFISH_FETCH_ENDPOINT=
```

TinyFish 的搜索和正文抓取 endpoint 不在程序中强制推断。填写供应商控制台当前提供的 endpoint 后才会启用；正文抓取失败时会回退项目已有的普通页面正文提取。

`BOT_WEB_SEARCH_PROVIDER_OPTIONS` 是 JSON 对象，可对每个 provider 传入非敏感 `headers`、`params`、`body` 或供应商原生选项：

```env
BOT_WEB_SEARCH_PROVIDER_OPTIONS={"tavily":{"topic":"news","search_depth":"advanced","include_answer":false},"you":{"freshness":"week"},"langsearch":{"freshness":"oneWeek","summary":true},"tinyfish_fetch":{"body":{"render":true}}}
```

传入规则：

- `headers`：附加非敏感请求头。
- `params`：附加 URL 查询参数。
- `body`：覆盖或补充 JSON 请求体字段。
- 其他顶层字段：直接合并到该 provider 的 JSON 请求体。

不要把密钥放在 `headers`、`params`、`body` 中；使用 `BOT_SEARCH_*_API_KEY` 与 `env:` 引用。

## 验证顺序

```powershell
# 配置、人格和知识文件路径
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task config-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task context-smoke"

# 离线主链路，不连接 NapCat 或搜索 API
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task backend-smoke -Message '测试后端主链路'"

# NoneBot handler 注册，不连接 NapCat
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task startup-smoke"
```

接入真实 key 后，用一个明确时效问题在测试群验证，并检查审计标签：

```text
web_search:used
web_search_hits:<数量>
web_search_provider:tavily|you|langsearch|tinyfish
```

主 provider 失败时，回退顺序由 `BOT_WEB_SEARCH_FALLBACK_PROVIDERS` 决定。调整该字段需要重启 NoneBot；`BOT_WEB_SEARCH_ENABLED` 可使用既有 runtime settings 开关控制。