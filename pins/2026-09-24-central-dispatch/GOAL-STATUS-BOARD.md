# 目标状态板（尺 s625.1，现跑于 2026-09-26T17:35:19Z）

> 只列**现算**事实。每行都可由 §末命令重跑。这张板不宣布完成；它的作用是让「进度」二字有对账面。

## A 目标的最终形态（用户原话：每个一级分类创建自己的 git 库）

| 指标 | 今值 |
|---|---|
| **我们自己的**一级分类库（排除 vendored） | **0** 个 |
| 外层仓（现有单仓） | 1 个：`ChatBot` |
| vendored 第三方嵌套 .git（**不算我们的库**） | 2 处：third_party/astrbot_plugin_meme_manager、third_party/astrbot_plugin_portrayal |

## B 三条前置的状态

| 前置 | 现算证据 | 判定 |
|---|---|---|
| ① 中央调度统一 | 在册表 `CAPABILITY_DESCRIPTOR` 今值 **125** 枚（口径=运行期 len(CAPABILITY_DESCRIPTOR)（静态数不出），本板现算）；字符串运行期依赖另见 s610.2 产物（DYN＝29／REFL＝55，**引自该件、非本板现算**） | 在册表与管线在、**但机制靠字符串接线，静态尺看不见** |
| ② 文件物理归类 | 生产 `.py` **589** 枚；一级分类只覆盖 469 枚，**120 枚无主** | **未闭合** |
| ③ 规格统一 | 顶层契约版本常量真值 **1 枚**（{'SCHEMA_VERSION': ['plugins/bot_unified_runtime/domains/core/contracts/envelope.py:30']}） | 远未统一（十库各需一枚） |

## C 「每类一库」的四个对象类（用户原话点名：子功能／插件／适配器／接口协议）

| 对象类 | 现算 | 能否进一级分类 |
|---|---|---|
| ① 子功能 | 无主的业务件：`domains/chat_reply/*` 段 **30** 枚 | 半成 |
| ② 接口协议 | `domains/core/contracts` 无主 **11** 枚 | **不能**（一级归属 0） |
| ③ 适配器 | `domains/transport` 无主 **7** 枚（其余被 B08 认领） | **归属错** |
| ④ 插件（上游 pip） | 非本仓目录（9 枚在册，见 S603 §1.3） | 不适用；该进 `pins` |

## D 分类尺自身是否可用（E-7/E-8 的对账面）

- 声明根总数 **136**；其中**非 `plugins/` 的 17 条**（逐板：B01:1／B03:1／B07:1／B08:1／B09:1／B10:12）
- 🔴 裸目录名声明根（一删就吞整树）：B10→tests
- 双主文件（一文件多板）**0** 枚：
- 无主面最大三块：`plugins/bot_unified_runtime/domains/chat_reply/runtime` 19／`plugins/bot_unified_runtime/domains/core/contracts` 11／`plugins/bot_unified_runtime/domains/core/safety_exec` 9

## E 版本统筹有没有地基（E-9 的对账面）

- `pyproject.toml` 声明：`version = "0.1.0"`；git tag：**1** 枚（v0.0.1-alpha.2）
- 运行期读点 `_plugin_version()` 在盘：True
- lock file 数：**0**（0 ⇒ 上游升级会静默进生产）
- 合法 semver ∩ annotated tag 集：唯一 tag `v0.0.1-alpha.2` 去 `v` 不过 semver ⇒ **空** ⇒ `pins.pinned_version` 无处可取

## F 复跑（一条命令出本板）

```bash
cd "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot" && PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPYCACHEPREFIX="$TEMP/s625-pyc" BOT_AUTOSYNC=0 \
  "../ChatBot_Runtime/venv/Scripts/python.exe" \
  .superpowers/sdd/2026-09-24-central-dispatch/probes/s625-goal-status-board.py
```
