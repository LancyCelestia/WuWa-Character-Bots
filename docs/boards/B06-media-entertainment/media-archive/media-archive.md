# 媒体归档 · 媒体归档

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.media-archive · 媒体归档

- 层级：一级 B06 → 二级 media-archive → 三级 `media-archive`
- 路由席位：`MEDIA_ARCHIVE`（matcher `media_archive`，command=True）
- 判定优先级：43
- 能力 id：`bot.media_archive`
- 实现落点：`plugins/bot_unified_runtime/domains/media/archive`、`plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py`
- 帮助主题：媒体归档
<!-- BOARD-AUTO:END -->

## 这个入口做什么

一条命令把媒体存成档案。三种触发形态：同条消息「媒体 + 指令」（发图顺手说
「收藏」）、回复某条媒体消息说「收藏」（handler 层通过协议端 `get_msg` 反查把媒体段
注入进来）、回复合并转发说「存聊天记录」（经 `get_forward_msg` 展开成 Markdown）。
产出是一条回执文本（必要时带缩略），归档本体落在
`bot_media_archive_dir` 下的 `<类别>/<IP>/<时间戳>_<sha8>.<ext>`，同名 `.json` 旁车
存完整元数据（来源会话、发送者、VLM 标签、NSFW 分）。

生效条件：`bot_media_archive_enabled`（缺省 True）且发送者角色达到
`bot_media_archive_min_role`（缺省 super_admin）。

## 怎么调用

`domains/media/capabilities/media_archive.py:build_media_archive_capability` 构造，
经 `capability_registry.py` 的声明行认领 `RouteKind.MEDIA_ARCHIVE` /
`bot.media_archive`；触发判定 `is_media_archive_command`、参数解析
`parse_archive_args` 在同文件。落盘与去重走存储层
`domains/media/archive/media_archive.py:MediaArchiveStore`（`exists` / `archive` /
`stats`），字节摘要统一调 `domains/media/digest.py:media_digest`，本域不再自算
sha256；取字节复用中央下载咽喉的 SSRF 判定，并额外挂一个**逐跳复查重定向**的
护栏（`urlopen` 默认自动跟随 30x，重定向目标指向内网或元数据地址时必须就地拒绝）。

指令参数（写在指令文本里，用空格分隔）：

- `分类=<类别>`、`IP=<作品来源>`、`角色=<角色名>`：显式覆盖 VLM 判定；
- `子路径=<相对路径>`：仅管理员可用，用于自建更细的目录树；
- 裸「收藏」/「归档」/「archive」：全自动判定。
- 触发别名含「存聊天记录」与英文/拼音形态，完整别名以 `/bot help 媒体归档` 与
  `docs/command-catalog.md` 为准（生成物，勿手抄）。

## 开关与参数

- `bot_media_archive_enabled`（True）：总闸。
- `bot_media_archive_dir`（`data/media_archive`）、`bot_media_archive_db_path`
  （`data/media_archive.sqlite3`）：两者都在 `config.py` 的 `path_fields` 里，
  经 `scripts/runtime_paths.py` 重映射到 Runtime 数据根。
- `bot_media_archive_min_role`（`super_admin`）：权限门，取值沿用
  `domains/chat_reply/policy/roles.py` 的六级角色。
- `bot_media_archive_max_file_mb`（100）、`bot_media_archive_daily_limit`（50）、
  `bot_media_archive_per_message_limit`（4）：三道限额。
- `bot_media_archive_summary_enabled`（True）：是否生成聊天记录归档的摘要行。
- `bot_media_archive_video_frames`（5）：视频抽帧数量。
- 依赖识图能力：模型注册表 `bot_vision_model_registry` 与 `bot_vision_enabled`
  （见 `../vision/README.md`），本能力不另立一份模型配置。

逐键的热更性以 `docs/config-catalog-full.md` 为准；生产改 `.env` 后必须重启。

## 失败时看到什么

- 角色不够：不进归档，走统一的用户向拒绝（由 B02 门禁给，本能力不自拼文案）。
- 单条超件数 / 当日超额度：只处理额度内的件，回执点名被跳过的那几件。
- 取字节失败或 SSRF 校验拒绝：该件跳过并说明「没能取到」，不影响同条其它件。
- magic bytes 与扩展名不符、文件损坏：判为格式未识别，拒绝落盘并在回执计入跳过数。
- VLM 未启用或调用失败：按媒体类型降级归类，回执明确标注「未分析」，不假装判过。
- 内容重复：幂等命中既有记录，回执说「已经存过了」并给出既有路径。
- 写盘失败（含目录不可建）：该件跳过并留痕，已成功的件照常回报。

## 测试与验收

`tests/test_media_archive.py`（含目录名消毒的穿越负样本、去重幂等、限额四态、
VLM 失败降级、回复媒体注入路径、合并转发展开）。真机：
`docs/acceptance-manual.md` §6.6.2 全条目；配额与权限用 `/bot runtime set` 现场改
后重启复验。归档库的 owner 与清理清单登记在 `docs/db-owners.md`。
