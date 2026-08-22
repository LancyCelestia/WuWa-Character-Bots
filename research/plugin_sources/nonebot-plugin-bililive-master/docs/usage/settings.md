# 进阶配置

BiliLive 存在一些**非必须的**进阶配置项，用户可以在 `.env.prod` 或 `.env.dev` 文件中添加这些配置来改变 BiliLive 的**默认行为**。

::: tip 提示
添加配置项只需在 `.env.*` 文件最底下另起一行直接添加即可。
::: details 示例（点我展开）

```json {7-8}
HOST=0.0.0.0
PORT=8080
SUPERUSERS=[]
NICKNAME=[]
COMMAND_START=[""]
COMMAND_SEP=["."]
BILILIVE_TO_ME=false
BILILIVE_GUILD_ADMIN_ROLES=["Haruka", "频道主"]
```

:::

## BILILIVE_TO_ME

默认值：True

在群里使用命令前是否需要 @机器人。设置为 `False` 则可以直接触发指令。

```json
BILILIVE_TO_ME=False
```

## BILILIVE_LIVE_OFF_NOTIFY

默认值：False

是否开启下播提醒。

```yml
BILILIVE_LIVE_OFF_NOTIFY=True
```

## BILILIVE_PROXY

默认值：None

设置后所有网络请求将使用代理端口，仅支持 HTTP 代理。

```yml
BILILIVE_PROXY=http://127.0.0.1:10809
```

## BILILIVE_INTERVAL

默认值：10

不推荐使用，请更换为 `BILILIVE_LIVE_INTERVAL`。
直播刷新间隔，单位：秒。

```yml
BILILIVE_INTERVAL=20
```

## BILILIVE_DYNAMIC_INTERVAL

默认值：0

动态刷新间隔，单位：秒。设置为 0 时根据网络情况自动调整间隔。

```yml
BILILIVE_DYNAMIC_INTERVAL=5
```

## BILILIVE_LIVE_INTERVAL

默认值：`BILILIVE_INTERVAL` 设置的值

直播刷新间隔，单位：秒。

```yml
BILILIVE_LIVE_INTERVAL=20
```

## BILILIVE_DYNAMIC_AT

默认值：False

动态、投稿是否也要@全体。

```yml
BILILIVE_DYNAMIC_AT=True
```

<!-- ## BILILIVE_SCREENSHOT_STYLE

默认值：mobile

截图样式，可选值：mobile（手机）、pc（电脑）。

```yml
BILILIVE_SCREENSHOT_STYLE=pc
``` -->

## BILILIVE_CAPTCHA_ADDRESS

默认值：<https://captcha-cd.ngworks.cn>

验证码地址，用于解决动态截图验证码问题。
（如果你不知道这是什么，请忽略）

```yml
BILILIVE_CAPTCHA_ADDRESS=https://captcha-cd.ngworks.cn
```

## BILILIVE_CAPTCHA_TOKEN

默认值：bililive

验证码 Token，用于验证码服务器鉴权，若不填写一天内只能使用 5 次。

```yml
BILILIVE_CAPTCHA_TOKEN=bililive
```

## BILILIVE_BROWSER_UA

默认值：""

自定义浏览器 UA
（如果你不知道这是什么，请忽略）

```yml
BILILIVE_BROWSER_UA="Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.210 Mobile Safari/537.36"
```

## BILILIVE_CHROMIUM_ENDPOINT

默认值：""

外部 Chromium 的 CDP 连接地址。配置后插件将优先连接该浏览器进行动态抓取与截图，不再自动下载 Playwright 内置 Chromium。

启动示例（Windows）：

```bat
chrome.exe --remote-debugging-port=9222
```

```yml
BILILIVE_CHROMIUM_ENDPOINT=http://127.0.0.1:9222
```

连接失败时会自动回退到 Playwright 内置浏览器。请在外部 Chromium 中登录 B 站账号，以降低动态接口风控概率。

## BILILIVE_DYNAMIC_TIMEOUT

默认值：10

动态加载超时，单位秒。
网络不好一直超时请调大此数值。

```json
BILILIVE_DYNAMIC_TIMEOUT=30
```

## BILILIVE_DYNAMIC_FONT

默认值："Noto Sans CJK SC"

自定义动态截图使用的字体。只能使用系统中已经安装的字体。

```json
BILILIVE_DYNAMIC_FONT="Microsoft YaHei"
```

## BILILIVE_DYNAMIC_BIG_IMAGE

默认值：False

是否使用大图模式，大图模式下会将动态图片扩展至页宽。

```json
BILILIVE_DYNAMIC_BIG_IMAGE=True
```

## BILILIVE_COMMAND_PREFIX

默认值：""

添加命令前缀，所有 BiliLive 的命令需要带上前缀才能触发。

```json
# 使用方式：“bl帮助”、“bl关注列表”
BILILIVE_COMMAND_PREFIX="bl"
```

## BILILIVE_GUILD_ADMIN_ROLES

默认值：["超级管理员", "频道主"]

在频道里使用命令的身份组，可以写入多个身份组

```json
BILILIVE_GUILD_ADMIN_ROLES=["BiliLive", "频道主"]
```
