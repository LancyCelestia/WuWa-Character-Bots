# Third-Party Notices

本文件是本项目引用/移植的第三方开源组件的**唯一出处记录**（MIT 许可要求许可声明随软件副本保留）。
应用内与源码注释中不再重复出现上游名称，一律指向本文件。

## 1. 卡片渲染子包（output/card_render/）

- **来源**：`astrbot_plugin_parser`（https://github.com/Zhalslar/astrbot_plugin_parser）
- **许可**：MIT License（Copyright (c) 归上游作者 Zhalslar 所有）
- **使用方式**：移植并精简/适配（models.py、bridge.py、universal_card.html 的结构与渲染契约来自上游；
  样式、模板与本项目集成层为重写）。按 MIT 许可随本项目分发，本文件即随附的许可声明记录。

## 2. 仅借鉴思路（未复制代码）的社区开源项目

- `astrbot_plugin_eat_what` ——「吃什么」能力的交互思路参考（capabilities/eat.py 为原生实现）。
- `astrbot_plugin_gscore_adapter` ——GsCore/gsuid-core 适配桥的实现思路参考（sources/gscore_bridge.py）。
- 社区气象预警类插件 —— 能力边界与失败策略的调研参考（未复制实现）。

> 以上仅作能力调研与思路对照，未复制其代码；相应文件头注释统一表述为
> 「参考社区开源插件/外部参考项目」并指向本文件。

## 3. 说明

- 依据用户 2026-09-12 指示，除本文件外，项目内不再出现上游框架与插件的品牌字样；
  用户可见面（卡片页脚、默认 bot 名等）已全部改为「守岸人 / ShoreKeeper」。
- 本文件即 MIT 许可义务下的出处与许可声明保留位置，请勿删除。
