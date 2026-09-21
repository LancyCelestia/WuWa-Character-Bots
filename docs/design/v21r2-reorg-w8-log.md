# v21r2 重组 W8 席施工日志 —— W1b：link_parse 其余 16 件（基建+support+fetchers+content_parser）

> 席位：RW8（2026-09-18）。方案书序列中尚未被认领的下一波=W1b（RW1a 已完结离场、RW7 留有 http_util 7 处移交）。
> 占域声明：COORDINATION.md「W8 席…认领占域施工中」；全程零 git 写操作、未 commit（共享工作树）。

## §一、波前取证（实跑）

1. **移动清单（16 件，§2.3 映射核对）**：
   - parsers 基建 8+1：`sources/parsers/{http_util,ssrf_guard,cookies,wbi,image_stitch,context,types,platform_login}.py` + `sources/parsers/__init__.py`（833 行聚合真身：build_content_parser_registry/build_cookie_provider/build_source_input/extract_http_urls/music_candidate_providers/music_search_providers + 28 platforms 聚合导入 + ParserRegistry）
   - `capabilities/content_parser.py`（链接解析能力，被引符号 9：build_content_capability/render_card_png/parse_matched_url/build_subscription_push_capability/render_subscription_push_card/subscription_item_to_parse + 下划线 _clean_summary/_format_publish_time/_summarize_subtitle）
   - support 3：`sources/{url_cleaner,parse_history,registry}.py`（registry.py 实读确认归域：ParserRegistry+contracts.media，方案低置信标记解除）
   - fetchers 3：`sources/fetchers/{__init__,playwright_backend,xhs_sign}.py`
2. **monkeypatch 命中清单（波前）**：字符串式 0（W1a 已清零实证，与 W7 log §二一致）；对象式/属性式命中测试文件=auditfix_parsers(http_util._build_opener×5+ssrf_guard_mod×1+platforms_generic/wbi_mod 纯读)、auditfix_wave3_resources(wbi_mod×8 处用法)、market_fin_phase1(http_util 对象式×7)、short_link_hop_guard(http_util×1)、content_parser_quota_throttle(cp×3)、cookie_import_hot_reload(聚合 parsers_module×2，**判定不改**，见 §四偏差1)、media_quality_port(http_util._sleep/_build_opener×10，**波前扫描 head 截断漏检，终验批抓到后补改**)。
3. **AST 符号面扫描**（ast.walk ImportFrom 全树）：旧路径 from-import 符号总面 43 名，其中下划线 4=content_parser 三件（垫片预置转发）+cookies._resolve_relative_cookie_path（首版垫片漏转发→插件冒烟 ImportError 实锤后补）。
4. **相对导入**：仅 context.py:5（`.http_util`）一处。
5. **RW7 移交坐标**：finance http_util 7 处=6 data 头部（fx/market/market_crosscheck/bond/stock/commodities）+stocks.py:119 函数级。

## §二、移动与改写

- 文件系统 `mv`（禁 git mv）16 件入 `domains/link_parse/{parsers(9),capabilities(1),support(3),fetchers(3)}`；聚合真身覆盖新包占位 `__init__.py`。
- 真身导入切 canonical：聚合 `__init__`（cookies+28 platforms 直连真身+support.registry）、8 基建互引（http_util↔ssrf_guard 函数级、image_stitch/wbi/http_util、context 相对→绝对）、content_parser 5 处 link_parse 面（聚合/context/http_util/ssrf_guard/types；music/contracts/output/runtime/llm 跨域面保持旧路径）、playwright_backend:18、fetchers/__init__ 2 处。
- 同域 27 个 platforms 真身 33 行基建 import 切 canonical（含 platforms_bilibili:36 `import wbi as _wbi` 包属性直连）。
- **finance 7 处接管再迁**（RW7 移交）：6 data 头部+stocks:119 → `domains.link_parse.parsers.http_util`。
- 跨域消费方一律不动（垫片覆盖）：weather/stocks(已 canonical)/moegirl/mediawiki/news_feeds/today_history/steamfree/epicfree/acg_search/subscriptions 三适配器/xiaohongshu_adapter/root `__init__`/console_chat/policy.gate/capabilities.{download,subscribe,epic,today_history}。

## §三、垫片（16 张，旧位 re-export 薄壳）

- 8 基建：`sources/parsers/{context,cookies,http_util,image_stitch,platform_login,ssrf_guard,types,wbi}.py`（`import *`；cookies 加显式 `_resolve_relative_cookie_path` 转发——初版漏转发被插件冒烟 `platform_credentials.py:22` ImportError 抓到）。
- 聚合 `sources/parsers/__init__.py`：`import *` + 显式 6 公开函数 + 8 基建模块对象（28 platforms 模块属性由 import 机制自动落位，test_douyin 等旧路 `from sources.parsers import platforms_generic` 实证可用）。
- support 3 + fetchers 3 + `capabilities/content_parser.py`（显式转发 3 下划线名）。
- 垫片同一性冒烟：**35/35 same-object 断言通过**（6 聚合函数+http_util 3 符号+wbi+cookies 3 含下划线+context+ssrf_guard+types+platform_login+image_stitch+registry+parse_history+url_cleaner+fetchers 2+content_parser 5 含下划线+platforms_generic 2）。
- 垫片期顺序纪律（W1a §五）**W1b 后双向安全**：旧路径先行（垫片链）与新路径先行（canonical 聚合）均无环；W1a 留下的「旧路径 import 先行」测试前导注释全部保持原样可用。

## §四、monkeypatch 波内清零 + 终验

- 改写 6 文件：auditfix_parsers(http_util 块+ssrf_guard_mod 函数级→canonical)、auditfix_wave3(wbi_mod)、market_fin_phase1(对象式×7+**字符串式×2**，字符串式系 AST 终验抓到的正则漏网)、short_link_hop_guard、content_parser_quota_throttle(cp 模块对象)、media_quality_port(http_util+ParseHttpError，补改)。
- **不改判定 2 处（消费方仍在旧路径，强制 canonical 反而断）**：`test_auditfix_subscriptions_capabilities.py:316`（消费者 social_v2 旧路径函数级取符号，patch 旧 shim 模块对象=对齐）、`test_eat_image_quality.py:195`（消费者 eat.py:518 旧路径函数级，同理）。AST 终验残留=恰此 2 处 LEGAL，BAD=0。
- **连带移交/自愈记录**：test_auditfix_parsers 内 transcribe 2 处+vision_describe 1 处系 W11（media）在飞迁移落在本文件的红——transcribe 2 处由 RW11 并行自行改写（本席 replace 断言 0 命中实锤其已改），vision 红在终批复跑时已被 RW11 自愈转绿。
- cookies 垫片下划线转发教训：多行括号 from-import 的下划线符号正则扫描不可靠，AST ImportFrom 扫描才是终审（方法论③再验证）。

## §五、回归实跑（固定解释器+PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，basetemp=$TEMP/v21r2-rw8，-p no:cacheprovider）

| 门 | 结果 |
|---|---|
| 定向批 28 测试文件 | **316 passed / 1 failed / 2 skipped**（唯一红=test_parsers_batch_a2::test_discourse_linuxdo_parses_topic，见 §六偏差3） |
| 广域 -k（parse/ssrf/cookie/wbi/douyin/fetcher/short_link/acg/mediawiki/moegirl_search/market/stocks/commodities/bond_data/finance） | **1204 passed / 2 failed / 5 skipped**（discourse 环境红+W11 vision 红〔终批已自愈转绿〕） |
| 插件导入冒烟+垫片同一性 | OK+35/35 same-object |
| ruff 本波面 | **All checks passed**（--fix 收 47=I001×31+垫片 noqa 形态×16，根因=项目未启用 F403、W3 式裸 star 无 noqa 为正解）；全树余 33 错均他席在飞面，零命中本波 |
| mypy（--explicit-package-bases --ignore-missing-imports plugins，与 dev.ps1 同参） | 488 文件 **本波面 0 错**；余 2 错=control_plane/api/platform.py 既有外部（W7/R1/R3 同口径） |
| runtime_layout_smoke | 唯二失败=BOT_KNOWLEDGE_FILES 两个**工作区外**用户文档缺失（环境项，与迁移无关） |
| tests/verify_hashes.py --check | exit 0 |
| test_doc_sync_gates | 4 passed |
| test_no_source_tree_data_writes | 5 passed |
| 树卫生 | 源码树零 \_\_pycache\_\_/.pytest\_cache/.mypy\_cache/data/ |
| qx.json | `domains/weather/assets/qx.json` sha256 e8285e77d8ed、362774 字节，与 RW7 记录一致，完好 |

## §六、偏差与诚实登记

1. **test_cookie_import_hot_reload 判定不改**：root `__init__` `_cached_content_parser_registry` 经**函数级旧路径** from-import 取符号，测试 patch 旧聚合垫片模块对象=调用时同对象取符号，天然对齐；改 canonical 反而使 patch 与取符号面分裂变红。纯读纪律的 patch 版特例，已在代码处保持原样。
2. **两处 LEGAL 旧路径字符串 patch 保留**（§四），垫片退役尾声波时随消费方（social_v2=W8 序、eat 已迁但 :518 函数级旧路径调用）一并收口。
3. **环境型既有红（非本波引入，不动）**：`test_parsers_batch_a2::test_discourse_linuxdo_parses_topic` 断言真实样本值 6848，`_SAMPLE_BASE` 指向工作区外 `C:/Users/LancyCelestia/Downloads/Archives/nonebot-plugin-parser-lite-1.3.5/api_txt`（本机现缺→_HAS=False 走合成样本必红；同目录 batch_a 有 skipif 守卫而 a2 此例没有=潜在测试缺陷，建议后续席位补 skipif，本席不越权改断言语义）。runtime-layout 的两个 BOT_KNOWLEDGE_FILES 缺失同类（外部用户文档）。
4. **并行席瞬态一次**：media 席迁移窗口致冒烟 `sources.transcribe` ModuleNotFoundError 一次，取证（文件在盘/domains/media 已建/RW11 已声明）→退避 20s 重跑自愈（R3/W1a 同款先例）。
5. **波次编号**：本席任务号 RW8，按方案书序列执行 W1b（link_parse 其余）；COORDINATION 占域行已注明「W8 序=W1b」。
6. 未跑 dev.ps1 全量门（席位禁令）；未跑 command_catalog --write（零触碰 echo/config）。

## §七、交接注记

- W8 序剩余：**subscribe 21 件**（§5 W8 主波，未认领）；W9 notes+files 已由 RW9 认领在飞、W11 media 已由 RW11 认领在飞。
- 垫片退役尾声波注意：旧路径消费方残余大头=capabilities/content_parser 垫片的各域 render_card_png 函数级调用（weather/music/eat/divination/epic/today_history 六处+root），届时随各域波或尾声统一收。
