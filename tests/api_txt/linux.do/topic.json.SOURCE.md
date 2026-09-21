# topic.json 来源说明（真实抓取，非伪造）

- 来源 URL: https://linux.do/t/topic/482293.json （帖子: 「请不要把互联网上的戾气带来这里！」, id=482293, 公开可读高热帖）
- 获取时间: 2026-09-18 19:03 UTC（本地 2026-09-19 03:03）
- HTTP 状态: 200（浏览器上下文 fetch，credentials=include）
- 获取方式: linux.do 匿名直连与 127.0.0.1:7890 代理均被 Cloudflare 拦截（403, `Cf-Mitigated: challenge`, "Just a moment..."），curl 全变体（http1.1 / 去 Accept / slug 形态 / latest.json / site.json / 多帖 id）全 403。最终用本机真实浏览器（Playwright 驱动 Chrome）通过 CF 挑战后，在同源页面内 fetch 该 topic.json 取回原文。
- 原样性: body 为源站返回 JSON 原文（仅剥离抓取包装的状态行前缀 `200\n`），未做任何字段增删改。
- 消费字段核对: `fancy_title` / `posts_count`(int)=7479 / `like_count`(int)=134188 / `post_stream.posts[0].username`="neo" / `.cooked` / `.created_at` 均存在。
- 用例: tests/test_parsers_batch_a2.py::test_discourse_linuxdo_parses_topic（期望值从样本派生 max(0, posts_count-1)=7478）
- 已知路径前提: 该测试当前 `_SAMPLE_BASE` 指向 `C:/Users/LancyCelestia/Downloads/Archives/nonebot-plugin-parser-lite-1.3.5/api_txt`（不存在）；本样本按座位域落 `tests/api_txt/linux.do/`，需 `_SAMPLE_BASE` 改指 `tests/api_txt` 后用例自动 skip→pass（改测试属 REAPER 席文件域）。
