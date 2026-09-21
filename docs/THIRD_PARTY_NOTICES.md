# Third-Party Notices

本文件是本项目引用/移植的第三方开源组件的**唯一出处记录**（MIT 许可要求许可声明随软件副本保留）。
应用内与源码注释中不再重复出现上游名称，一律指向本文件。

## 1. 卡片渲染子包（output/card_render/）

- **来源**：`astrbot_plugin_parser`（https://github.com/Zhalslar/astrbot_plugin_parser）
- **许可**：MIT License（Copyright (c) 归上游作者 Zhalslar 所有）
- **使用方式**：移植并精简/适配（models.py、bridge.py、universal_card.html 的结构与渲染契约来自上游；
  样式、模板与本项目集成层为重写）。按 MIT 许可随本项目分发，本文件即随附的许可声明记录。

## 2. 仅借鉴思路（未复制代码）的社区开源项目

- `astrbot_plugin_eat_what` ——「吃什么」能力的交互思路参考（domains/food/capabilities/eat.py 为原生实现）。
- `astrbot_plugin_gscore_adapter` ——GsCore/gsuid-core 适配桥的实现思路参考（domains/ops/integrations/gscore_bridge.py）。
- 社区气象预警类插件 —— 能力边界与失败策略的调研参考（未复制实现）。

> 以上仅作能力调研与思路对照，未复制其代码；相应文件头注释统一表述为
> 「参考社区开源插件/外部参考项目」并指向本文件。

## 3. 说明

- 依据用户 2026-09-12 指示，除本文件外，项目内不再出现上游框架与插件的品牌字样；
  用户可见面（卡片页脚、默认 bot 名等）已全部改为「守岸人 / ShoreKeeper」。
- 本文件即 MIT 许可义务下的出处与许可声明保留位置，请勿删除。

## 4. AxonHub frontend（Apache-2.0，已采纳并修改，2026-09-18）

- **来源**：AxonHub 前端 `frontend/` 目录（https://github.com/looplj/axonhub ，unstable 分支，快照 commit `19a3c27`，2026-09-17）。
- **许可**：Apache License 2.0（上游仓库 `llm/` 目录为 LGPL-3.0，本项目未采用、不涉及）。
- **使用方式**：路线 B「抽设计系统 + 定向移植」——仅采纳 shadcn 风格 UI 组件子集、lib 工具、`index.css` token 组织结构与 i18n 基建至 `webui/`；全部色彩/圆角/阴影 token 已重映射为守岸人卡片值册（换算表见 `docs/design/webui-axonhub-adoption.md`），属注明修改的衍生使用。
- **许可义务落点**：上游 LICENSE 与 frontend/NOTICE（内嵌 shadcn-admin MIT 归属，Copyright (c) 2024 Sat Naing）副本存于 `webui/THIRD_PARTY/`；本条目即声明保留位置；本项目不以 AxonHub 名义宣传。

## 5. zhconv（繁简转换库，运行时依赖，2026-09-21 WP2 席引入）

- **来源**：`zhconv` 1.4.3（https://github.com/gumblex/zhconv ，作者 Dingyuan Wang）。
- **许可**：上游元数据声明为 GPL-2.0-or-later——**代码文件 LICENSE 实为 MIT**，
  带 GPL 义务的是随包词表 `zhcdict.json`（`LICENSE.data`：派生自 MediaWiki 的
  简繁转换表，GPLv2+）。故本项目经该库链接使用的是 GPL 数据表，而非 GPL 代码；
  这是如实登记，分发面（若将来对外分发安装包）需按 GPLv2+ 处理该数据文件。
- **使用方式**：仅作**运行时依赖**调用其公开函数 `convert(text, "zh-cn")`，不复制其
  任何代码或词表进本仓库；落点在
  `plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py` 的
  匹配面繁简折形（把繁体输入折成简体后再过词面），归一化文本不写回记忆/审计/回复。
- **依赖性质**：纯 Python、无 C 扩展、零传递依赖（`pip show zhconv` 的 `Requires:` 为空）、
  词表 JSON 随包离线可用；wheel `sha256=877def7073763697cfb6401c796b0c92250adc3f2ed1117a899ac7c4bf108dc0`。
- **退役条件**：若该库不再可用，同一模块自动降级到内置字级兜底表并显式 WARNING
  （降级态该红线视为半开），不构成功能硬阻断，但需尽快恢复依赖并重启。

