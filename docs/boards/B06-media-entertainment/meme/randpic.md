# 表情包与图库 · 随机图片

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.meme · 随机图片

- 层级：一级 B06 → 二级 meme → 三级 `randpic`
- 路由席位：`RANDPIC`（matcher `randpic`，command=True）
- 判定优先级：41
- 能力 id：`bot.randpic`
- 实现落点：`plugins/bot_unified_runtime/domains/meme`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

从**用户自己指定的文件夹**里随机甩一张图。思路借鉴开源 randpic 插件的「指令→随机图」
玩法，实现完全自研：不建数据库、不接收上传、不自建目录，一把随机梭哈即可。
触发形态含「随机图」「来张图」与繁體/拼音别名，产物是一个图片部件。

## 怎么调用

`domains/meme/capabilities/randpic.py:build_randpic_capability` 构造，声明行认领
`RouteKind.RANDPIC` / `bot.randpic`。核心两件：

- `list_gallery_images(dirs, *, max_bytes)`：递归扫描配置目录里的图片扩展名，
    带进程内 TTL 缓存（窗宽以该实现的常量为准，LRU 有界，过期键读取时惰性清除），所以往文件夹里加图
  最多一个缓存周期就能被抽到，不需要重启。
- `pick_random_image(dirs, *, rng=None, max_bytes)`：从清单里等概率抽一张，
  空清单返回 `None`。
- 触发判定走中央件 `domains/core/text_boundary.py:is_trigger`（边界字符集与
  大小写语义全仓唯一口径），本域不留第二份字符集副本。

## 开关与参数

- `bot_randpic_enabled`（True）：总闸。
- `bot_randpic_dirs`（空）：图片目录列表。**没配目录等于这个功能不存在**——
  绝不猜目录、绝不自建。相对目录按进程工作目录解析，因此要么配绝对路径，
  要么接受随启动目录漂移（推荐绝对路径）。
- `bot_randpic_trigger_words`（空）：追加触发词（与内置词并集，不是替换）。
- `bot_randpic_max_file_mb`（缺省 MB 数以 `config.py` 该字段为真身）：单文件上限，超过直接不进候选（防止把几十兆的
  原始视频帧甩进群里）。
- 图片扩展名集合与扫描缓存参数是模块常量，不暴露成配置键。

谁能改：管理员（`.env` / `/bot runtime set`，改后重启生效）。

## 失败时看到什么

- 没配目录、目录不存在、目录为空、扫到的文件全部超限：统一给一句友好降级，
  不报错、不在源码树或 Runtime 里留下任何新目录。
- 单个文件读取失败（权限、被占用）：跳过并继续抽，不让一张坏图毁掉整次请求。
- 文件不是真图片（扩展名对但内容坏）：交给出站侧的质检与发送失败路径处理，
  本入口不冒充「已发出」。
- 目录里图片极少时不做去重与冷却（等概率抽取，允许重复），这与表情库的加权
  抽取是两套语义，别互相套用。

## 测试与验收

`tests/test_randpic_identity.py`（身份与降级文案、只读目录）、
`test_randpic_scan_cache_l10.py`（缓存有界与过期清除、目录变更可见）、
`test_traditional_news_randpic.py`（繁體触发形态）。真机：
`docs/acceptance-manual.md` §6.6.1 的随机图条目（含「目录为空」「新增图片后一个缓存周期内
可抽到」两条）。
