# kb_wiki 对账 topics 子集护栏修复（2026-09-20）

## 改动
- `plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py`
  - **:308-315（核心）**：`reconcile_with_manifest` 里 `corpus_topics &= allowed`（`allowed = set(topics)`，非空才交）——删除判据与收窄 `entries` 用同一个 topics 集；子集外域一律进 `reconcile_held`/`remove_suspended`，绝不进 `removable`。`topics=[]` 时跳过交集，全量路径逐字段不变。
  - :264-269、:287-291：docstring 收口（代码与声称契约对齐）。
- `tests/test_kb_topic_name_contract.py`：追加 2 例（:147- :180-），原 8 例零改动。
- `character/kb_wiki.py` 旧路径系纯 re-export 垫片，修复自动透传，未动。

## RED（修复前实跑）
```
$ PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_kb_topic_name_contract.py -q --basetemp="$TEMP/kbfix" -p no:cacheprovider
E  AssertionError: 授权域内的真删除照常生效，授权域之外一条都不许删
E  assert {'域10/bwiki/词条_域10_2', ...} == {'鸣潮/bwiki/已删词条_鸣潮_9'}
1 failed, 9 passed in 4.81s
```
（失败即漏洞本体：14 个未授权域 28 条活文档全进 removable；控制台 GBK 致中文乱码，非本席输出日文。）

## GREEN（修复后实跑）
```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_kb_topic_name_contract.py tests/test_kb_wiki_metadata_sync.py -q --basetemp="$TEMP/kbfix" -p no:cacheprovider
29 passed in 3.35s
$ … -m pytest tests/test_kb_topic_name_contract.py tests/test_kb_wiki_metadata_sync.py tests/test_kb_wiki_retriever_wiring.py tests/test_kb_wiki_sync.py tests/test_sdd9_n3re.py tests/test_v21r2_stall_kbsync.py -q --basetemp="$TEMP/kbfix" -p no:cacheprovider
70 passed in 5.01s
```

## 静态门 + 卫生
```
$ … python.exe -m ruff check --no-cache plugins/…/kb_wiki.py   → All checks passed!
$ … python.exe -m mypy --cache-dir="$TEMP/mypy-kbfix" --explicit-package-bases --ignore-missing-imports plugins/…/kb_wiki.py → Success: no issues found in 1 source file
$ find plugins tests scripts -name "__pycache__" -o -name "*.pyc" → 空；根目录无 .pytest_cache/.ruff_cache/.mypy_cache/data
```
诚实披露：repo 级 ruff 现存 12 错，其中 10 错在他人热区文件（providers/card_render/quiet_hours 等，本席禁碰清单内），1 错为本文件存量 `L98 missing 未用`（既有测试、按约未动，本席新增用例用 `_missing`）；均非本席引入。全程离线 mock（鸭子类型 `_LedgerStore`），未触碰 `ChatBot_Runtime`，零 git 写操作。
