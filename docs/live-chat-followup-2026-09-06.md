# 22:40 实测问题续修（2026-09-06）

本记录覆盖上一轮“仅去掉整条引号、整份 Cookie 跳过、Wiki 只允许独立页”的不足。未改人格源文件、未重写原 Cookie、未启动第二个机器人、未推送 Git；未调用付费 LLM。

## 已修复及证据

### 回复引号
旧算法只检查首尾，因此 `“你好。” “欢迎。”` 会变为 `你好。” “欢迎。`。
现扫描整个序列的配对边界，只有全文由引号包裹的台词和空白构成时才移除每段外引号。保留段落空白、内层引用、书名号、混合叙述和不闭合文本。新增普通群成员真实聊天 capability 的离线回归，不只测辅助函数。审计标签 `llm_speech_quotes_normalized` 表明发生清理（不记录正文）。
这不是权限差异修复，也不是保证 LLM 永不输出引用；用户提供的是模型台词逐句包裹，未发现 OneBot 自动插入 reply 段。

### 维基独立页与列表条目
精确独立页优先，拒绝消歧义页以及把锚点重定向父页概述冒充角色资料。
独立页不存在时，先在配置的索引页中找精确标题/定义项/表格首列，再尝试全文搜索前三个候选；只输出匹配条目到下一条目之间的正文，不把其他角色/整部游戏介绍混入。

`BOT_WIKI_ENTRY_PAGES=["鳴潮角色列表"]` 为候选页默认值，可在本地 .env 改为其他列表，`[]` 禁用该优先路径，重启生效。不是硬编码人物答案。查询兼容“鸣潮守岸人”和末尾多余 `·`。简繁标题转换由 MediaWiki 参数辅助；本地少量标题归一化不是通用中文转换器。

真实公开 API 复验：守岸人、鸣潮守岸人、漂泊者、卡提希娅· 四项均命中角色列表中的正确命名条目。来源明确标注“非独立页面”。仅在 HTML 实际提供 id 时附加锚点，没有 id 时链接到父页，不伪造锚点。
曾发现全文搜索前三项漏掉漂泊者/卡提希娅所在列表，因此补了可配置的索引页优先，不以 mock 成功替代完整入口实测。

### 小红书分享链接
补 `/discovery/item/<id>` 到实际 ParserRegistry。解析阶段只改路径为 `/explore/<id>`，原 query 保持不变（含 xsec_token）。分享文字中带链接可以进入解析器，不再因缺失规则返回 skipped。
这里只离线验证了路由和签名参数保留，未使用用户登录 Cookie 访问小红书。源站验证码、登录状态或签名过期依然可能导致正文读取失败。

### Cookie 与媒体错误
原策略因一个非相关站点坏行丢弃所有平台 Cookie，并每次打印 WARNING；新策略只在内存导入：
- 标志合法但域名前导点冲突：依导出 scope 标志规范化，不修改源文件；
- 坏行单独跳过，保留其他有效行；解析 HttpOnly、Secure、expiry；
- 文件大小上限 8 MiB，按路径/mtime_ns/size 缓存；每版本至多一条 INFO 统计；
- 给每次 yt-dlp 调用构造无 filename 的 CookieJar，不将原文件作为 cookiefile，因此 yt-dlp 退出不能反写原始 Cookie；
- 不输出 Cookie 名/值、原始上游错误或带令牌 URL；probe 和 download 返回安全错误。

回归使用伪造 Cookie 验证实际 yt-dlp jar：域名隔离、HTTPS Secure、HttpOnly、原文件不变，以及失败日志不泄露。未验证用户真实 Cookie 是否有效/过期；格式修复不是登录态续期。

### doctor 与 verify
`dev.ps1` 选择外部 Runtime Python 但未激活 PATH；旧 doctor 只查 PATH 得到 nb_cli=missing。现优先检查所选 Python 同目录 nb.exe/nb，再回退 PATH。真实 doctor 输出 ok=true、nb_cli=ok、ready_for_nonebot_run=true；这是依赖检查，不是 NapCat 在线证明。

附件 24 个 mypy 问题已处理，未禁用检查/批量加 ignore：空配置返回类型、缺失队列回退 return、可空对象收窄、局部变量冲突、嵌套统计数据类型等。卡片文件仅类型注解/等价局部变量整理，未改样式或颜色数值算法，无需创建新截图。

## 验收步骤

重启当前机器人进程（不要新增同账号第二实例），按顺序测试：
1. 普通群成员 @ 机器人发送“你好”，观察多句回复不再包裹每句台词，正文中的“第二实例”等引用仍保留。
2. 控制台或 QQ：`维基 守岸人`、`维基 鸣潮守岸人`、`维基 漂泊者`、`维基 卡提希娅·`。
3. 再发原小红书分享文字，验证进入解析器；不代表源站必然允许抓取。
4. 重复发同一 B 站/YouTube 链接，观察无旧的 ignoring invalid Netscape 警告、不回显 Cookie。
5. `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify` 与 `doctor`。

## 剩余 TODO / 限制
- [ ] 用户 QQ 普通成员实机复验：本轮未实际给群里发送消息。
- [ ] 用户小红书、B站、YouTube、推特的真实登录态及源站可用性；本轮不使用用户 Cookie 联网。
- [ ] Wiki API 仍有超时/限流可能；当前配置最多 3 个索引页和 3 个搜索候选，不保证所有百科/任意网页结构通用。
- [ ] runtime-layout 仍报告源码 data 运行产物与 156 个 Python 缓存路径；未删除任何活动数据。
- [ ] 人格/世界观重构、长期记忆安全和群聊公共状态、视觉命令全量对齐、Mail 实机排查、完整备份/发布整理保持原 TODO。

## 最终验证证据
- 完整 `scripts/dev.ps1 verify` 退出 0：328 passed（1 条上游 Mail/Pydantic 弃用警告），Ruff All checks passed，mypy 169 source files 无错误。
- `doctor` 退出 0：ok=true，nb_cli=ok，ready_for_nonebot_run=true。
- `runtime-layout` 未通过：data 活动产物及 156 个源码缓存路径；独立于 verify，未删除。
- 四项真实公开 Wiki 查询均 matched=True；QQ、视频/小红书真实登录态未代替用户验收。
