# v21r5 RENDER-PROBE 席日志

- 日期：2026-09-19
- 席位：RENDER-PROBE（只读席；唯一写面=本 log；零代码编辑；render/** 与 tests/render_hashes.json 禁碰）
- 解释器：`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`
- 纪律：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`；pytest `--basetemp="$TEMP/renderprobe-tmp" -p no:cacheprovider`

## 开场盘点

- `tests/test_rendering_contract.py` 存在
- `tests/test_mica_builders_contract.py` 存在
- `tests/test_render_hashes_contract.py` **不存在**（本工作区无此文件；哈希门由 verify_hashes.py + render_hashes.json 承担）
- `tests/test_mermaid_reply_render.py` 存在
- `tests/verify_hashes.py` 存在
- `tests/render_hashes.json` 存在，且 git status 显示为 Modified（前端会话在飞改动；本席未触碰）
- `git status` 中 `plugins/bot_unified_runtime/render/` 未见 porcelain 输出行（首个 40 行窗口内）——待复核

## 实跑 1：渲染契约族（test_rendering_contract.py + test_mica_builders_contract.py）

（待填）

## 实跑 2：verify_hashes --check

（待填）

## 实跑 3：test_mermaid_reply_render.py

（待填）

## 判定

（待填）

## 前端交接句

（待填）

---
RENDERPROBE-SEAT DONE
