# nonebot-plugin-bili-query

✨ B站查询与提醒插件 for NoneBot2 ✨

## 功能

- `/用户查询` - 查询B站用户信息（粉丝数、投稿数、最近视频等数据）
- `/视频查询` - 查询B站视频信息（播放量、点赞、投币、收藏等数据），支持 BV 号 / 完整链接 / b23.tv 短链接
- `/订阅` - 订阅UP主，新视频发布时自动在群里提醒
- `/取消订阅` - 取消订阅
- `/help` - 显示所有指令

## 安装，指令二选一

```bash
nb plugin install nonebot-plugin-bili-query
pip install nonebot-plugin-bili-query
```

## 使用
在群聊中 @机器人 并输入以下命令：

指令	     参数	               说明
/help	     无	                  显示所有指令
/用户查询	  UID或空间链接	         查询用户信息
/视频查询	  BV号或视频链接	     查询视频信息
/订阅	     UID或空间链接        订阅用户更新
/取消订阅	  UID或空间链接	         取消订阅

## 示例
/用户查询 123456

/用户查询 https://space.bilibili.com/123456

/视频查询 BV1xx411c7mD

/视频查询 https://b23.tv/AbCdEf

/订阅 123456

/取消订阅 123456

/help

对的/help后面啥都没有

## 配置
无需配置即可使用。可选配置项（写入 .env 文件）：

```ini
bili_query_check_interval_minutes=5
```

订阅更新检查间隔（分钟），默认 5。

## 数据存储
订阅数据：使用 nonebot-plugin-localstore 管理，文件位于插件数据目录下
定时任务：使用 nonebot-plugin-apscheduler，按配置间隔检查订阅用户更新

## 注意事项
1️⃣ 需要机器人有发送群消息的权限
2️⃣ 订阅功能依赖定时任务，需确保机器人持续运行
3️⃣ 首次使用前无需额外配置
4️⃣ 订阅时会自动记录UP主当前最新视频作为基线，只有之后发布的新视频才会提醒

## 0.2.0 更新日志

修复了一系列问题：

- **修复致命 bug**：`CommandArg()` 参数注解错误导致 `/用户查询`、`/视频查询`、`/订阅`、`/取消订阅` 在新版 nonebot2（2.4+ / pydantic v2）下完全无响应
- **修复** b23.tv 短链接查询始终失败的问题
- **修复** 多个群订阅同一位UP主时，只有一个群能收到更新通知的问题
- **修复** 首次检查时把UP主的历史最新视频误当作“新视频”播报的问题（现在订阅时自动建立基线）
- **修复** 私聊使用 `/订阅` 无任何响应的问题（现在会提示仅支持群聊）
- **修复** 多个 Bot 同时在线时订阅通知发送失败的问题
- **修复** `httpx` 未声明依赖导致短链接解析在部分环境报 `ModuleNotFoundError`
- **修复** `requires-python` 与依赖版本冲突（Python 3.9 无法安装），现要求 Python ≥ 3.10
- 新增配置项 `bili_query_check_interval_minutes`
- 新增测试套件（nonebug + pytest）

## 开发

```bash
pip install -e ".[test]"
pytest
```

## 开源协议
MIT
