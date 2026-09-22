# 隔离工作区后端与适配契约

## 已有实现

- 服务：`plugins/bot_unified_runtime/control_plane/workspaces.py`。
- HTTP：`plugins/bot_unified_runtime/control_plane/api/workspaces.py`。
- 生成适配：`plugins/bot_unified_runtime/control_plane/sandbox.py`。
- 默认装配：`plugins/bot_unified_runtime/control_plane/factory.py::build_workspace_service`、`_app.py`。
- 数据位置由 `bot_control_plane_workspaces_db` 指定，默认 `data/control_plane_workspaces.sqlite3`，按既有Runtime规则映射。浏览器不传路径、不直接访问数据库。

## API

全部使用v1 envelope和Bearer认证；工作区含私密测试内容，读取也要求超管且限定拥有者。未持有工作区的其他身份得到404。

| 方法 | 路径 | 请求 |
|---|---|---|
| POST | `/api/v1/workspaces` | WorkspaceSettings；未指定mode为sandbox；未指定人格使用服务器配置默认profile |
| GET | `/api/v1/workspaces` | 当前拥有者未过期工作区列表 |
| GET | `/api/v1/workspaces/{workspace_id}` | 仅元数据，不携带原文 |
| DELETE | `/api/v1/workspaces/{workspace_id}` | query expected_version |
| POST | `/api/v1/workspaces/{workspace_id}/messages` | content、expected_version |
| GET | `/api/v1/workspaces/{workspace_id}/messages` | 当前隔离对话历史 |
| POST | `/api/v1/workspaces/{workspace_id}/preview` | expected_version |
| POST | `/api/v1/workspaces/{workspace_id}/send` | expected_version、confirmation_token、idempotency_key |
| POST | `/api/v1/workspaces/{workspace_id}/reset` | expected_version |
| GET | `/api/v1/workspaces/{workspace_id}/audit` | 脱敏操作摘要 |

所有写请求禁额外字段。默认profile可从 `/api/v1/protocol` 的workspaces.default_persona_profile_id获取。版本是工作区级单调版本；预览开始与完成分别推进版本。前端必须采用服务器返回的新版本，不假定永远只增加1。

## 状态与隔离

每个工作区有独立 `ws_*`、`test_*` 标识、历史、预览和确认。SQLite写事务校验版本，忙状态拒绝重置/改写；新消息和reset撤销旧预览。失败恢复idle，错误不回显模型异常正文。

默认sandbox：

1. 生成器只收到设置、test_session_id和工作区对话值对象。
2. 不构建生产CharacterContextProvider，不读写生产记忆、好感、限流或发送队列。
3. 人格文本由装配方指定的已登记loader读取，资料作为不可信用户层引用，不混入人格系统层。
4. 不调用ModelRouter的生产健康和usage全局sink；模型调用记录放在当前工作区预览artifact。
5. send仅创建simulated回执；不会调用真实会话适配器。
6. 未配置工具隔离适配器前，allow_external_tools=true明确拒绝。

默认生成装配每次预览读取当前config，支持static和OpenAI兼容协议，不在app启动时调用模型。
模型选择是显式三元组：`default_provider` / `default_channel` / 配置中的API模型名。这两个default ID是本地注册身份，不是假定供应商名称，也不能把模型名当渠道。
未指定或不明确的资料、超额预算和不支持的推理强度明确报错，不偷偷忽略。

## 真实会话端口（尚未连接生产）

`RealWorkspaceAdapter.context(session_id)`：提供已脱敏上下文。
`generate(scope)`：提供预览，不发送。
`deliver(scope)`：必须实现Policy、Review、Renderer、SendQueue及receipt；不可直接调用平台API。收到稳定delivery_id，底层必须以该ID幂等。

真实会话创建需要明确session_id和已注入适配器，否则503。默认生成只预览；确认绑定拥有者、当前版本和五分钟期限。真实预览不返回原始Prompt。

受理发送先写持久化pending记录并消费确认，再调用端口；发生超时/异常记unknown，重复幂等请求返回原回执，不再次调用端口。不能把unknown展示为成功。

## 保留期限与资源上限

- 工作区原文24小时固定TTL，不因刷新延长；app启动及每分钟清理到期工作区。
- 删除工作区同时清除发送记录，摘要审计保留；SQLite启用secure_delete，不让删除的内容继续残留在数据库空闲页。
- 每个拥有者最多20个活动工作区；对话最多100条；单条消息16000字符。
- 单预览artifact最多128KB、工作区总JSON最多512KB；默认模型上下文64000字符、输出最多2048 Token。
- Token缺失返回null，不当成0；static明确标示离线，不冒充真实模型输出。
- 长期全局Usage/Trace未接入，当前model_calls仅为短期工作区记录。

## 尚未达到计划的内容

- 默认装配只接配置中的默认人格和单模型；完整人格列表、世界观/世界书、知识库动态检索、独立记忆CRUD尚未装配。
- 资料注入支持显式字典注册，但不是生产世界书或知识库管理API。
- persist_memory只允许workspace范围；目前工作区历史持久化不等同于已实现结构化记忆库。
- 真实会话Policy/SendQueue生产适配器未实现；测试中的stub不代表生产路径已验证。
- 生成结果长期Trace、流式生成、差异对比、消耗排名仍未完成。
- 前端页面不在本阶段；未来模板应按认证OpenAPI及 `/api/v1/protocol` 能力声明接入。
