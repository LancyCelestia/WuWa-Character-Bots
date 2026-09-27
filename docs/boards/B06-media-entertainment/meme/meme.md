# 表情包与图库 · 表情包生成

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.meme · 表情包生成

- 层级：一级 B06 → 二级 meme → 三级 `meme`
- 路由席位：`MEME`（matcher `meme`，command=True）
- 判定优先级：20
- 能力 id：`bot.meme`
- 实现落点：`plugins/bot_unified_runtime/domains/meme`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

用本机 meme-generator-rs 服务生成梗图：列模板、看模板参数、把用户提供的图片作为
底图套模板加字。命令形态 `/表情 列表`、`/表情 <模板> <文字…>`（斜杠可省、大小写
不限），产物写入 `bot_meme_api_output_dir` 指向的目录（经 Runtime 重映射）后作为图片部件走统一流水线发出。

## 怎么调用

`domains/meme/capabilities/meme.py:build_meme_capability` 构造，声明行认领
`RouteKind.MEME` / `bot.meme`；命令识别 `is_meme_command`。协议侧是自家客户端，
对端接口为 `GET /meme/version`、`GET /meme/keys`、`GET /memes/{key}/info`、
`POST /image/upload`（base64 上传拿 `image_id`）、`POST /memes/{key}`、
`GET /image/{image_id}`。

一个平台事实钉在这里：QQ 的多媒体签名 URL 第三方服务抓不到，因此需要底图时一律
由 bot 侧先把字节下载下来、再以 data URI 或 base64 形式上传，绝不去把平台的临时 URL 递给
生成器（与表情归档、识图同一口径）。

## 开关与参数

- `bot_meme_command_enabled`（缺省态以 `config.py` 该字段为真身）：命令面总闸，用于快速屏蔽整族表情指令。
- `bot_meme_api_enabled`（缺省态以 `config.py` 该字段为真身）：是否真的对接生成器；关了就是「会说没配上」。
- `bot_meme_api_base_url`（`http://127.0.0.1:2233`）：本机服务地址。
- `bot_meme_api_timeout_seconds`（缺省秒数以 `config.py` 该字段为真身）：单次请求上限。
- `bot_meme_api_output_dir`（产物目录，缺省路径以 `config.py` 该字段为准）：在 `config.py` 的
  `path_fields` 内重映射到 Runtime 数据根。
- `bot_meme_cache_max_bytes`：本域产物的缓存配额口径（与其它图类能力共用中央
  配额件，落点见 B08）。

谁能改：管理员（`.env` + `/bot runtime set`）。模板清单与参数由对端服务决定，
bot 侧不维护第二份模板表。

## 失败时看到什么

- 服务未启动/不可达：优雅降级提示「没接上」并附配置方向，不抛异常、不重试打爆。
- 模板名不存在：回 `列表` 引导，不猜用户想要哪个。
- 参数缺失或不合模板要求：把该模板的参数说明回给用户（取自 `/info`，不硬编码）。
- 生成成功但图片落盘失败：如实说明没发出去，不假装成功。
- 底图取不到（URL 过期、非图片、超限）：直接说明需要把图片和指令放在同一条消息里。

## 测试与验收

`tests/test_meme_domain_fixes.py`（协议客户端、模板解析、降级路径）、
`test_meme_image_input.py`（底图上传链路）、`test_meme_conflict_fix.py`（与相邻
触发词的让路关系）。真机：`docs/acceptance-manual.md` §6.4 的表情条目——
列模板、单图套模板、底图同条消息、服务未起四条。
