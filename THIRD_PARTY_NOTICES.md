# 第三方代码与素材声明（Third-Party Notices）

## astrbot_plugin_parser（万能解析器）
- 用途：本项目 `plugins/bot_unified_runtime/output/card_render/` 的通用卡片 HTML 模板与
  RenderPayload 数据模型，设计参考自该插件的 `core/templates/universal_card.html`
  与 `core/render_html/models.py`、`core/render_html/bridge.py`。
- 来源：`https://github.com/Zhalslar/astrbot_plugin_parser`（本地参考副本
  `C:\Users\LancyCelestia\Documents\Documents\.astrbot\data\plugins\astrbot_plugin_parser`）。
- 许可证：MIT License，Copyright (c) 2024 Les Freire。
- 说明：本项目仅参考其**HTML 模板结构与字段设计**并做了适配改造；解析逻辑仍为自研
  （不使用其 GPL 依赖 `bilibili-api-python` 的任何代码），引用部分保留 MIT 版权注释。