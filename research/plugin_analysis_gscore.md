# GsCore UID 插件分析报告（鸣潮 / 终末地 / 战双）

> 分析对象：XutheringWavesUID、EndUID、PGRUID（Loping151）
> 源码位置：research/plugin_sources/{XutheringWavesUID-main,EndUID-main,PGRUID-main}
> 结论：**三个都是早柚核心（gsuid_core）插件，必须装在 GsCore 里，不移植进 NoneBot。**

## 1. 架构定性

| 插件 | 平台 | 运行载体 | 数据源 |
|---|---|---|---|
| XutheringWavesUID | 鸣潮 | GsCore 插件（clone 进 GsCore plugins 目录，或 `core安装插件XutheringWavesUID`） | 库街区 `api.kurobbs.com`（国服）+ 启动器 SDK `sdkapi.kurogame-service.com` / `pc-launcher-sdk-api.kurogame.net`（国际服） |
| EndUID | 终末地 | 同上 | 鹰角系接口（同架构） |
| PGRUID | 战双帕弥什 | 同上 | 库洛系接口（同架构） |

README 明确：「该插件为早柚核心(gsuid_core)的扩展」「直接对 bot 发送 core安装插件XutheringWavesUID，然后重启 core 以应用安装」。

## 2. 鸣潮插件能力与关键接口（XutheringWavesUID）

- **UID 查询面板**：HTML 模板（templates/）+ GsCore 渲染 → 图片卡（角色/声骸/深塔/图鉴等 20+ 卡片）
- **库街区登录流**：扫码 / 邮箱 / token 三种绑定（`api.kurobbs.com`），用户自持 token；**不强行要求登录**（公开数据匿名可查）
- **凭据续期链**：access_token → 过期 → auto_token 静默续登 → exchange_access_token（`launcher_chain.py`）
- **评分/伤害计算**：本地计算权重与服务器一致（该插件卖点）；「总排行」需向作者群申请 token（防伪造数据）
- **截图识别**：支持小程序/库街区截图直出角色面板（ScoreEcho 生态）
- 关键 API：`https://api.kurobbs.com`（KuroUrlProxyUrl 可配代理）、`https://sdkapi.kurogame-service.com/sdkcom/v2`、device 指纹 did、`WAVES_GAME_ID` 区分国服/国际服

## 3. 该装哪里：推荐方案

**方案 A（推荐）：装进 GsCore**
- 理由：三个插件依赖早柚核心的插件系统、消息收发、数据库、面板渲染与登录流；直接移植等于重写半个 GsCore 生态，维护成本极高且无法跟随上游更新。
- 我们已有 GsCore 适配桥（`sources/gscore_bridge.py`，ws://HOST:PORT/BOT_ID?token=，MessageReceive/Send 协议，真机往返测试通过）——**机器人在 GsCore 装这些插件，消息经由桥自动转发**，两全其美。
- 操作：
  1. 部署 gsuid_core（参考 GenshinUID 安装）
  2. GsCore 里 `core安装插件XutheringWavesUID`（EndUID/PGRUID 同理）→ 重启 core
  3. 我们的 `.env` 打开 `BOT_GSCORE_ENABLED=true` + host/port/token → 桥接通即用

**方案 B（不推荐）：内置进本项目**
- 需要重写：库街区 SDK 全套（登录/续期/角色数据/面板字段）、20+ HTML 模板、评分计算器——工作量以「周」计，且上游更新时无法跟进。
- 若只想要「UID → 角色列表」这一个轻量功能，可以用匿名公开接口自写（库街区部分接口匿名可查），但完整面板/评分不值得。

## 4. 许可证与风险

- XutheringWavesUID/EndUID/PGRUID 均自带 LICENSE（GPL/MIT 混合，以各仓库为准）；只作 GsCore 插件安装使用，不拷贝源码进本项目。
- 风险：库街区 token 属用户私有凭据；总排行需申请（防伪造）。

## 5. 结论

**装进 GsCore（方案 A）。** 我们的桥已经就绪，这一项不需要写任何移植代码；剩下的是部署 GsCore + 配置桥参数，等用户装好 GsCore 后联调即可。
