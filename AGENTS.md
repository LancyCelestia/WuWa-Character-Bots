# ChatBot AI 工作区规则

本目录是唯一允许 Codex/AI 默认扫描和修改的源码工作区：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`

## 外部运行数据

以下目录不属于当前工作区，默认不要递归扫描、索引或读入上下文：

- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime`
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive`
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot`

机器人通过 `.env`、`plugins/bot_unified_runtime/config.py` 和 `scripts/runtime_paths.py` 访问外部数据，不通过 Markdown 文档运行。需要确认路径映射时，优先阅读：

1. `docs/external-runtime-access.md`
2. `WORKSPACE_GUIDE.md`
3. `docs/workspace-archive-policy.md`

除非用户明确要求，不要删除或压缩以下活动数据：SQLite、FAISS、向量嵌入、聊天记忆、NoneBot data、Cookie、订阅状态、媒体缓存、日志、卡片 SVG 和 Runtime 虚拟环境。

## 测试与缓存

源码只保留 `tests/` 下的少量关键回归测试，不要堆叠大型测试树。使用以下入口，不要直接在源码目录生成 pytest/Ruff/mypy 缓存：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
```

源码工作区中不应出现 `__pycache__`、`*.pyc`、`.pytest_cache`、`.ruff_cache` 或 `.mypy_cache`。绕开 dev.ps1 直接用 python/pytest 跑脚本时，必须设置 `PYTHONDONTWRITEBYTECODE=1`，否则会在源码树生成字节码缓存。

## 前端卡片 UI 规范

所有 HTML→PNG 卡片（解析信息卡、通用分支、兜底卡、订阅推送卡、帮助页）统一遵循 Windows 11「Mica 云母」规范：

- **底色渐变一律由平台标志色派生，禁止写死任何品牌色**（包括岸宝粉 `#fb7299`）。平台内容卡的唯一颜色来源是 `output/card_render/bridge.py` 的 `PLATFORM_COLORS`，经模板 `--pc` 变量用 `color-mix(in srgb, var(--pc) N%, #fff)` 掺白派生（外壳 5-11%、面板 4-8%、高光 14%）；未知平台回退中性灰 `#607080`。
- 帮助页没有平台语境，主色来自配置 `bot_help_card_color`（十六进制，留空 = 中性灰），同样走派生 token，不允许在模板里写死色值。
- 阴影只允许两枚 token（外壳大柔光 `--mica-shadow` + 面板微光 `--mica-shadow-soft`），禁止多层彩色光晕叠加；圆角走 `--r-shell / --r-panel / --r-tile`；字重最大 700；`body` 保留 `-webkit-font-smoothing: antialiased` 与透明背景（截图 `omit_background` 依赖它）。
- 修改卡片样式或颜色派生逻辑后：用样例 payload 渲染各平台截图核对（临时脚本放源码树外，如 `%TEMP%`），并跑上面三个 dev.ps1 任务验证。

## 归档

历史、研究、完整测试树和旧工作树统一归档到：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive`

归档内容先压缩并验证，再从源码工作区移出。不要把 Runtime 或 Archive 设为 Codex 工作区，也不要重新创建已废弃的嵌套 `_Archive` 路径。
