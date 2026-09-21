# 图像与视频理解 · 以图搜图与来源

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.vision · 以图搜图与来源

- 层级：一级 B06 → 二级 vision → 三级 `image-search`
- 实现落点：`plugins/bot_unified_runtime/domains/media`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

「这张图是哪来的」。拿图片去 SauceNAO 反查，返回相似度、画师、来源页面与直链。
视觉模型只能猜「像谁」，反查能给出「出处链接」——两者互补，不能互相替代。

## 怎么调用

- `domains/media/capabilities/image_search.py:build_image_search_capability`：能力
  构造口，处理「搜图」文本与图片段提取。
- `domains/media/search/sauce_search.py:search_saucenao_ex`：真实请求口，返回
  `(命中列表, 错误类别)`；`search_saucenao` 是只返回列表的兼容口。
- 图片来源三条路，优先级固定：同条消息里的图片段 → 被引用消息的原图（协议端
  `get_msg` 反查后注入）→ 回复里那张图的原始直链。取不到图时明确提示「把图片和
  『搜图』放在同一条消息里」，不猜。
- 密钥解析走中央件 `domains/core/search/search_api.py:resolve_search_secret`
  （支持 `env:变量名`），本域不自行读环境。

## 开关与参数

- `bot_saucenao_api_key`（`env:SAUCENAO_API_KEY`）：唯一必需项；真实密钥只在 `.env`。
- 无独立总闸：没配 key 时功能自然不可用并给出 `no_key` 提示。
- 超时与请求参数在 `sauce_search.py` 内部（`db=999`、`output_type=2`），不暴露成
  配置键——要接第二家反搜源时再提参数化。

谁能改：管理员改 `.env` 或 `/bot runtime set`（重启生效）。全员可用，无角色门
（只读外呼，不写本机）。

## 失败时看到什么

三分类互不混淆，这是本入口的主要设计点：

- `no_key`：「还没配反搜密钥」——不是「没有这张图」。
- `http_error`：请求失败/超时/被限流——措辞是「现在查不动」，稍后再试。
- 真无结果：查询本身成功但没有可信命中，如实说没查到，并给出可复制的下一种问法。

命中后的呈现：相似度最高的若干条，每条给标题、画师/来源站点与可点链接；来源域名
出站前经统一打码（盘符路径与密钥形态），不泄露本机信息。

## 测试与验收

`tests/test_image_message_routing.py`（图片段/引用反查/同条消息三形态）、
`tests/test_group_recent_image.py`（与看图共享的最近图缓存）、
`test_subscription_vision.py`（订阅图文侧的复用面）。真机：`docs/acceptance-manual.md`
§6.6.1 的「搜图 + 回复图片」与「没配图时的提示」两条。
