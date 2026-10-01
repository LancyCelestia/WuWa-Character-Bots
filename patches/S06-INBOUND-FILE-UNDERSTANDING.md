# S06 · 入站文件理解（PPT / Word / Excel / OneNote / Markdown / 代码 / 日程表）——工单

席位：S06（研究与出册席）。**本席零代码落地**：主工作树空壳（`find plugins -type f` = 0，HEAD 8ad03e4 完好），只允许写本文件。
读源码全走对象库：`git --git-dir="<仓库>/ChatBot_Runtime/git" show HEAD:<路径>`。本文所有行号＝**HEAD 实测**（会随恢复波漂移，定位优先按符号名）。
纪律自查：本席未做任何 git 写操作、未装包、未跑 pytest、未碰进程、未再派席。§2 的依赖结论来自**只读** `importlib.util.find_spec` 探针与 `site-packages` 目录列举（命令原文附在该节，可复跑）。

---

## §0 摘要（≤200 词）

入站文件理解**不是从零起**。HEAD 真身有两条腿：主入站腿 `__init__.py:1373-1389` 已经把 `.docx/.xlsx/.pptx/.pdf` 与 30 余种代码/文本后缀**读出来并拼进用户消息**（开关 `bot.ingress.file_read` 缺省开），解析器 python-docx / openpyxl / python-pptx / pypdf **venv 里全已装**（实测 import 通过）；简报里那条"8 种纯文本白名单 + 该类型暂不支持调试"是**管理员调试腿**（`file_exchange.run_code_debug`），不是理解主路。所以真正的缺口按优先级是：①**注毒包壳缺席**——主入站腿裸拼正文，`guard_secondhand_text` 未接；且 09-28 那版 `labelled_text`/`read_file_for_context`/`label_file_body` 在 HEAD **一字不存在**（判为 #68 还原失传）；②**资源无门**——文本腿整档进内存、OOXML 无解压炸弹体检、无单文件/每日限额；③**语义残缺**——Word/PPT 表格与备注全丢、Excel 无表格语义、课表只能发图或手打文本行；④`.one/.doc/.xls/.ppt` 无适配器（OneNote 全仓 0 命中）。方案：复用已装依赖、零新增重依赖，新增咽喉＝带包壳的读取口 + zip 容器体检 + 表格双轨（转 markdown 进 prompt / 结构化进日程腿），OneNote 诚实拒读＋指路导出，`.py` 执行闸保持关闭。每格式两把锁（注毒必包壳 / 正常不误杀）。

---

## §1 HEAD 实况（先纠简报的前提）

### §1.1 两条入站腿，性质不同（别再当一条）

| 腿 | 载体（HEAD 实测） | 覆盖格式 | 门 | 是否进 prompt |
|---|---|---|---|---|
| **主入站理解腿** | `__init__.py:1373-1390`（`_incoming_from_nonebot_event`）→ `file_reader.read_supported_file`（blob `5eafc970`，入口 :309，分支体 :347-473） | 30 余后缀（见 §1.2） | 仅 feature 开关 `bot.ingress.file_read`，**缺省 True**（`domains/ops/features/feature_catalog.py:45`）；**无 admin 门、无字节帽、无 magic 校验** | **是**：`note = f"[文件内容：{title}]\n{parsed_file.text}"`（:1384）→ `text = text + "\n" + ...`（:1389），随整条消息过 `injection.check_prompt_injection`，但**正文本身没有二手包壳** |
| 管理员调试腿 | `file_notice`（matcher `__init__.py:5763`，handler :6537，调用 :6578）→ `file_exchange.run_code_debug`（blob `463ef3d2` :159） | `_RUNNABLE_EXTENSIONS={.py}`（:64）+ `_TEXT_EXTENSIONS` 8 枚（:65） | `_is_admin_file_notice`（:5458）＝管理员 ∧（群上传 ∥ 私聊 offline_file）；受限回读 `read_confined_bytes` | **否**：结论只回给用户看（`[文件调试] …` :6579） |

⇒ 简报里"非白名单一律回『该类型暂不支持调试，仅做接收确认』"＝ `file_exchange.py:177`，**只属于调试腿**。用户要的"收发＋读取＋理解"落在主入站腿上，那条腿的白名单是 `file_reader._TEXT_EXTS`（:41）+ 四枚 OOXML/PDF 分支，比调试腿宽得多。
⇒ 附带欠账：两腿白名单**互不一致**（`.docx` 主腿能读、调试腿回"不支持调试"；`.markdown/.toml/.ini/.tsv` 在 `restricted_runner.TEXT_EXTENSIONS`（:178）里、却不在 `file_reader._TEXT_EXTS` 里；`.log/.xml/.tex` 反之）。**这是同一事实的第二张表**，落地时收成一张（真身放 `restricted_runner`，`file_reader` 只引不抄）。

### §1.2 主腿格式清单（HEAD 实测逐支）

- **文本/代码**（`_TEXT_EXTS` :41-73，直读 UTF-8、NUL 即弃）：`.txt .log .md .csv .json .yaml .yml .py .c .h .cpp .hpp .cc .cxx .cs .java .js .ts .tsx .jsx .go .rs .php .sh .ps1 .sql .html .css .xml .tex`；其中 `_CODE_EXTS`（:74-97）标 `kind="code"`。
  ⇒ **用户要的 Python / C++ / C / Java "理解"今天已经通了**（正文进 prompt，模型本就能读）；缺的只有**结构化摘要**——只有 `.py` 有 AST 顶层定义/导入报告（`file_exchange._static_structure_report` :101），C/C++/Java 没有对应物。
- **Word** `.docx`（:370）：`"\n".join(p.text for p in Document(...).paragraphs)` ⇒ **表格（`document.tables`）、页眉页脚、文本框/图形内文字、超链接目标、列表层级全丢**。
- **Excel** `.xlsx`（:402）：`openpyxl.load_workbook(read_only=True, data_only=True)`，逐 sheet 每行 `" | ".join(...)` ⇒ **表头/合并单元格/公式（只留缓存值，从没被 Excel 打开过的产物是 None）/列宽语义丢失**；`rows` 列表**无上限累积**后才 `[:max_chars]`。
- **PPT** `.pptx`（:444）：`slide.shapes` 里有 `text` 属性的 shape ⇒ **表格（GraphicFrame）、图表、图片内文字、演讲者备注（`notes_slide`）全丢**，幻灯片数无上限。
- **PDF** `.pdf`（:388 → `_read_pdf` :500）：**最成熟的一支**——页数帽 `PDF_SCAN_MAX_PAGES=60`（:177）、字符截断显式说明、页级错误不拖垮整档、口令保护单态（`NOTE_STATUS_SENTENCES` :155）、扫描件四态（`SCAN_EMPTY_SENTENCES` :140）、中文解码质量尺 `DECODE_ACCEPT_RATIO=0.8`（:173）。**这套"没读≠没有"的口径就是本次要复制到 docx/xlsx/pptx 的模板。**
- 诚实降级族（绝不抛、绝不静默）：`PARSE_STATUS_SENTENCES` :116（`parse_failed` / `parser_unavailable` / `internal_parse_error`）、`KIND_SILENCE_SENTENCES` :165（`unknown`「这个类型我没有读取通道（不猜它里面写了什么）」/ `missing`），出口 `file_read_failure_note` :225。`.xls`（:390）与 `.ppt`（:434）＝**已登记的** `parser_unavailable`；`.doc` **连分支都没有** ⇒ 落到 `unknown`（:473）。
- 导出侧（不在本工单主面，仅纠偏）：`EXPORT_FORMATS=(md,docx,pptx,xlsx,pdf)`（`file_exchange.py:61`）＋ `parse_markdown_blocks`（**HEAD:256**，`DocumentBlock` :244）把 Markdown 解析成 heading/bullet/code/para/table 五类块——**这份现成的结构器正好是 md/.docx/.xlsx 入站抽取该复用的东西，别再写第三个 Markdown 解析器**。

### §1.3 日程/课表腿现状

- 文本行导入：`schedule_board.py:1010` `_import_text` + `_parse_import_line`（:1231）——一行一条 `周X 8:00-9:40 名称 地点 单/双`，`_MAX_IMPORT_LINES=60`（:80），单双周缺学期首日即**回问不猜**（:1031），提交走 `_commit_entries`（:1130，收 `(weekday, 日内锚, duration, 标题, 地点, parity)` 六元组）。
- 图片课表：`schedule_board.py:1056-1068` `_import_image` → `timetable.recognize_timetable`（`timetable.py:300`）→ `CourseEntry`/`TimetableDraft`（:81/…）→ `timetable_draft_to_plan_payload`（:373，缺学期/节次表 ⇒ `ValueError` 拒发布）。**这条路已在盘上、可复用。**
- 闸：总闸 `bot_schedule_enabled=False`（`config.py:744`，读点 `schedule_board.py:211-213`）。⚠ `bot_schedule_timetable_enabled`（`config.py:747`）**全仓零读点**（grep 实测只有 config 这一行）——即 `config.py:743` 自己承认的"在册未接线"；课表图片腿实际只受 `bot_schedule_enabled` 管。**别把"开关关着"说成"能力没有"**，也别反过来说成"已生效"。
- 上班日历/周历：`schedule/service/schedule_rrule.py`（`iter_rule_dates` :114、`expand_occurrences` :181）+ 调休例外表 `data/calendar_exceptions.json`（version 1，2026 年 `holidays`/`workdays` **皆空**，`delivery.py:46` 经 `bot_schedule_exceptions_path` 读；表内 field_notes 写死"未官方核实不预填、缺年份=unknown"）。⇒ 文件导入只能补这张表的**数据面**，schema 不许改。
- 缺口：**没有"表格文件 → 结构化日程"的腿**（Excel/CSV 课表、ics 排班表都只能走 §1.2 的纯文本读，进 prompt 后她能读懂但**不会落进日程板**）。

### §1.4 安全登记与盘上真身不符（本工单最重要的取证）

`attack_surface.py` 两格的 `current_defender` 宣称已被防：
- :277-290 说 `file_reader.labelled_text`/`read_file_for_context` 已成咽喉、"邮件附件腿 mail_ingress_files 已改走这枚口"、真身 `trust.label_file_body`；
- :705-722 说三条 OOXML 腿解析前先过 `archive_expansion_violation`（成员数＋单成员＋全容器三重限额）、文本腿已改流式截断读。

**HEAD 实测这五枚符号（`labelled_text` / `read_file_for_context` / `label_file_body` / `archive_expansion_violation` / `mail_ingress_files`）在 plugins 全域 0 命中**，只作为字符串活在这两段描述里；`trust.py` 只有 `label_external_content`（:301）。文本腿 `_text`（:289）仍是 `raw = path.read_bytes()[: max_chars * 4]`＝**整档进内存再切**。
为何门不红：`SurfaceEntry.current_defender` 那列**判定看 probes 不看这句**（:208 注释原文），而两格的探针（`check_prompt_injection` / `label_external_content` / `derive_trust_level` / `read_supported_file`）恰好都真实存在 ⇒ 全绿。
⇒ 判性：这是台账 #48★「AGENTS 叙述≠真身」的又一例（且是登记册里的），失传路径与 #68 还原事故一致（09-28 的件，09-29 06:30 被外部 restore 抹掉；无 HEAD 提交）。落地本工单 §3/§4 时**必须同时把这两段文字改成盘上真身**，否则文档继续说谎。

### §1.5 pyproject 未声明的既有依赖（换环境即静默降级）

`pyproject.toml` `dependencies`（HEAD 实测）里没有 `python-docx` / `openpyxl` / `python-pptx` / `pypdf` / `fpdf2` / `xlsxwriter`——它们只在现网 venv 里存在（`__editable__` 装的本包不传递它们）。这与文件里 `httpx`/`zhconv` 注释的成因**同一族**（"此前只在 venv 里存在、未声明，换环境会静默降级"）。⇒ 本工单要求把这六枚补进声明面（读侧四枚 + 写侧两枚），零风险、纯记账。

---

## §2 依赖实况与"优先复用"结论（只读取证）

取证命令（只读，可复跑；本席未装任何包）：
```
<C>/ChatBot_Runtime/venv/Scripts/python.exe -c "import importlib.util as u; [print(m, 'OK' if u.find_spec(m) else 'MISSING') for m in [...]]"
```
Python 3.12.10。

| 想要的解析能力 | 对应包 | venv 实测 | 判定 |
|---|---|---|---|
| Word `.docx` | python-docx **1.2.0** | **OK**（`docx/`） | 已装，直接复用（含补 `tables`/`inline_shapes`） |
| Excel `.xlsx/.xlsm` | openpyxl **3.1.5**（+ `et_xmlfile` 2.0.0） | **OK** | 已装；`.xlsm` 只是 `keep_vba` 差别，同包可开 |
| PPT `.pptx` | python-pptx **1.0.2** | **OK** | 已装；补 `graphic_frame.table` / `notes_slide` |
| PDF 文本 | pypdf **6.19.0** | **OK** | 已装（`_read_pdf` 在用）；写侧另有 fpdf2 **2.8.8** |
| Markdown 结构 | markdown **3.10.3** / markdown-it-py **4.2.0** / mdit-py-plugins **0.6.1** / pymdown-extensions **11.0.1** | **OK** | **不必新造**：入站结构复用 `file_exchange.parse_markdown_blocks`（零依赖、与导出侧同源），要 AST 级就点已装的 markdown-it |
| OOXML/zip 安全解析 | defusedxml **0.7.1** | **OK，但全仓 0 消费者**（grep 实测） | 解压炸弹体检的正解，零新增 |
| 容器/结构探查 | zipfile（stdlib）、lxml 6.1.2、filetype 1.2.0（0 消费者）、Pillow 12.3.0、numpy 2.5.2 | **OK** | 复用 zipfile+lxml 足够 |
| 代码静态摘要（C/C++/Java） | — | 不需包 | 正则/`pathlib` 级轻量摘要即可（见 §3.6）；**禁止**引入 tree-sitter/clang 绑定 |
| 旧 OLE2 `.doc/.xls/.ppt` | olefile — **MISSING**；xlrd — **MISSING** | 未装 | **需用户授权装包**；见 §2.1 |
| PDF 版式/表格 | pdfplumber — **MISSING**；pdfminer.six — **MISSING**；PyMuPDF(fitz) — **MISSING** | 未装 | 需授权；默认**不做**（pypdf 已够文本，版式属待裁） |
| 万能转换器 | markitdown — **MISSING**；mistletoe — **MISSING**；pandas — **MISSING** | 未装 | **明确否决**（§2.2） |
| Office 自动化 | pywin32 **312**（`win32com` **OK**）；本机 `C:\Program Files\Microsoft Office\root\Office16\` 实测有 `WINWORD.EXE/EXCEL.EXE/POWERPNT.EXE/ONENOTE.EXE` | 已装且可用 | **明确否决**（§6.2，风险不是体积） |
| LibreOffice 无头转换 | — | 未见于 `Program Files[ (x86)]\LibreOffice`（**待验**：其他安装位置未穷举） | 不纳入方案（外部进程 + GB 级体积） |

### §2.1 真要装包才有的能力（逐条评估，均需用户授权，本席未动）

1. **`.xls`（旧 Excel）**：`xlrd>=2.0`（纯 Python，wheel 约数百 KB 量级，**零传递依赖**；具体版本与体积＝**待验**，请用户跑 `pip index versions xlrd` / `pip install --dry-run xlrd` 只读试算）。风险：低（无 C 扩展、只读 API、纯 Python）；注意 2.x 起**只支持 .xls**，不能拿它替 openpyxl。收益：把她"学校/单位老课表常是 .xls"这一格从 `parser_unavailable` 变成能读。建议：**列为可选项，等她真发一个 .xls 再装**（现降级句已如实说明，不谎报）。
2. **`.doc`/`.ppt`（旧 OLE2）**：`olefile` 只能拆 OLE 流，`.doc` 正文在 WordDocument 流里按 FIB/PLCF 分片，**没有可靠的纯 Python 抽取器**；硬做＝半吊子解析器（抽出乱码比说"读不了"更坏，且会污染 §3 的诚实降级口径）。建议：**不装 olefile**，维持 `unknown`/`parser_unavailable` + 指路导出（同 OneNote 处置）。
3. **PDF 表格**：`pdfplumber`（拖 `pdfminer.six`＋`pillow`，后者已装）或直接用已装的 `pypdf`＋自写启发式。建议：**先不装**，第一版把 PDF 当文本读；若她要"PDF 里的报名表转日程"再授权。
4. **明确否决装包**：`markitdown`（把上面四枚又包一遍，且 extras 拉 pdfminer/azure-*/onnxruntime 一族——**具体传递集＝待验**，但与已装四枚重叠是确定的：一个都不缺还多一层调度）、`mistletoe`（md 结构已有两处现成）、`pandas`（几十 MB 级 C 扩展，为"读个 Excel"完全不划算）、`striprtf`/`docx2txt`（与 python-docx 重叠）。

### §2.2 复用优先的硬口径（写给落地席）

抽取器**只准**用：python-docx / openpyxl / python-pptx / pypdf / `zipfile`+`defusedxml`（容器体检）/ stdlib（`csv` `tomllib` `configparser` `ast` `re`）。任何"新解析库"都要先在本文件补一行"为什么这四枚＋stdlib 不够"，并等用户授权。**每加一枚依赖都必须同步补进 `pyproject.toml`**（否则就是 §1.5 那格欠账的复制）。

---

## §3 抽取 → 截断 → 进 prompt 链路（每格式一格）

统一骨架（新增一枚咽喉，住 `file_reader`，**禁第二家**）：

```
read_file_for_context(path, *, display_name, max_chars, request_id="") -> str
  = guard_secondhand_text( 抽取正文 + 截断说明行 , source_label=f"附件《{display_name}》正文" )
```
- 包壳**只准**用 `domains/chat_reply/security/injection.py::guard_secondhand_text`（HEAD:295；已装全角化 `neutralize_internal_markers`＋成对边界＋定性引导句，且 `source_label` 自己也被压单行限长过全角化——台账 #58★「边界标签收进 guard_secondhand_text」就是这条）。**零新正则、零新边界标记名**（文件头 :276-277 原文的理由照抄：新标记一自立门户，`INTERNAL_MARKER_PATTERN` 就慢一拍）。
- 空进空出：抽不到正文就返回 `""`，由调用方改说 `file_read_failure_note`（"谎报读到了东西比不读更坏"，injection.py 同款口径）。
- 三个消费点全换：`__init__.py:1383-1384`（主入站腿，**装配一行**，属 hub 写面 ⇒ 走补丁申请，见 §1.4/H1）、`runtime/capability_protocols.py:1406`（中央 `files.read.*` handler）、`__init__.py:6578`（管理员调试腿的报告句——报告是她自己那份文件的结构摘要，可保留原文，但**正文回显段**必须包壳）。
- `chat.py` 的四腿（识图 4407 / 视频档案 4507 / 视频 4537 / 语音 4578）**不动**（他席在飞，本席只出工单）；新腿与它们**同构**：都并进本轮唯一一次生成的 `composed_query`，不另起一次 LLM 调用、不自答。
- 截断说明行＝复用 PDF 支的口径：`（本份共 N 段/页/行，只读了前 M；后面的没读，不等于没有）`，逐格式写明"数的是什么"。

### §3.1 Word `.docx`
抽取顺序化（补进 :370 分支）：`document.paragraphs` → 每段带 style.name 前缀（`#`/`-` 还原层级，交给导出侧那五个 kind 名，别造第六种）→ **新增 `document.tables`**（每表转 markdown，表前一行 `[表格 k×m]`）→ 页眉页脚/文本框（`inline_shapes` 只报"有 N 个图形对象，其内文字本版读不到"，**不许静默**）。
限额：段落数 + 表格单元格数双预算；到顶补截断行。

### §3.2 Excel `.xlsx`（含 `.xlsm`）
见 §5（表格语义双轨）。抽取补三件：sheet 名/维度、合并单元格还原（`sheet.merged_cells.ranges` ⇒ 值回填到覆盖区或显式标 `^同上`）、公式与缓存值的**分列说明**（`data_only=True` 拿不到缓存＝没被 Excel 打开过 ⇒ 写"该表是公式、值未缓存"，不写空）。
限额：sheet 数 ≤ N、行 ≤ M/表、单元格 ≤ K；先算预算再迭代（改掉 :402-413 的无上限 `rows` 累积）。

### §3.3 PPT `.pptx`
补三件：`shape.has_table` → markdown 表；`slide.has_notes_slide` → `[备注]` 行；图表只报"有图表对象（数据本版读不到）"。**幻灯片数上限**（建议与 PDF 同量级：前 N 页），逐页 `[幻灯片 i/共 T]`。
`.ppt` 维持 `parser_unavailable` + 指路导出（§6.1）。

### §3.4 Markdown `.md`（及 `.markdown`）
今天＝纯文本读，能用但有结构浪费。方案：抽取器**复用 `file_exchange.parse_markdown_blocks`（HEAD:256）**产出 DocumentBlock 序列 → 回写成"结构轮廓 + 原文"两栏（轮廓给模型当目录，原文进包壳）。**不引入 mistletoe、不引入 markdown-it 新用法**，零新依赖；顺带把 `.markdown/.toml/.ini/.tsv` 补进读侧后缀（与 `restricted_runner.TEXT_EXTENSIONS` 收一张表，见 §1.1）。

### §3.5 日程表文件（周历/上班日历/课表的 xlsx/csv）
见 §5 全节。

### §3.6 代码（Python / C++ / C / Java / …）
- **理解**：已通（正文进包壳即懂）。本格只补**结构摘要对齐**：Python 用现成 `ast`（`_static_structure_report` :101）；C/C++/Java 加一枚**同形**的轻量摘要（正则级：`#include`/`using`/`import`、顶层 `class`/`struct`/函数签名、行数与语言），**明确声明是"轮廓非语义"**、不引解析器。命名与句子要保守，不写"已验证"。
- **执行**：见 §7（保持关闭）。
- 别把 `.h/.cpp/.java` 塞进 `_RUNNABLE_EXTENSIONS`（那是执行门，不是语言门）。

### §3.7 OneNote `.one`
见 §6。

---

## §4 落盘与限额

| 项 | 现状（HEAD 实测） | 落地要求 |
|---|---|---|
| 字节指纹 | 主入站腿**完全无** magic 校验（`_read_supported_file_body` 只信后缀）。写侧有 `MAGIC_SIGNATURES`（`restricted_runner.py:196`，`.docx/.xlsx/.pptx` 都只认 `PK\x03\x04`、`.pdf` 认 `%PDF-`）与 `inspect_payload()`（:521） | **复用同两张表**（读侧 `from ..sender.restricted_runner import MAGIC_SIGNATURES, inspect_payload`），**禁第二张表**；另补 OLE2 签名 `D0 CF 11 E0`（登记给 `.doc/.xls/.ppt`，命中即回"旧版 Office 二进制，本链路无适配器"——把猜测变成事实）与 `PK\x05\x06/PK\x07\x08`（空/归档 zip，防"改名骗过"） |
| 单文件上限 | 调试腿经 `read_confined_bytes` → `policy.limits.max_file_bytes`（缺省 8MiB，键 `bot_files_read_confined_max_bytes` `config.py:1518`，读点 `_read_policy_from_config` file_exchange:504 那族）；**主入站腿零上限**，且 `_text` :289 整档进内存 ⇒ 群里任何人发 2GB `.txt` 就能把 bot 顶爆（`bot.ingress.file_read` 缺省开、无 admin 门） | ①读前 `stat().st_size` 比限额，超限走**新增态**（建议 `too_large`，措辞进 `PARSE_STATUS_SENTENCES` 同族表，不与现有两态并一——`test_file_ingress_failure_feedback` 有"恰两态"结构锁，加态要同批改那枚锁）；②`_text` 改**流式** `open('rb').read(budget)`（预算＝`max_chars*4` 上界）；③OOXML 解析前先按字节尺寸判（见 zip 行） |
| 每日/件数 | 无（入站侧零账本） | 复用 `DailyQuotaLedger`（`restricted_runner.py:393`，键族 `bot_files_write_daily_*` 的先例）新建**读侧**账本实例；超限＝诚实句"今天读的文件够多了，明天再看这份"，不谎报"读不了" |
| 解压炸弹（zip 容器：docx/xlsx/pptx） | **无任何体检**（§1.4：宣称有、盘上无）。`defusedxml` 已装但 0 消费者；`character/documents.py:33 _read_docx_text` 用 `zipfile`＋`ElementTree.fromstring` 直读 `word/document.xml`（他席面，H6） | 新增一枚 `archive_expansion_violation(path) -> str`（住 `file_reader`，`AS-RESOURCE-ARCHIVE-BOMB` 的探针要改指它）：`ZipFile` 打开后逐成员判 **成员数 ≤ N / 单成员申报 ≤ M / 全容器申报合计 ≤ K**，并**真读每枚 `*.xml` 成员开头一小段**（申报值会说谎，这一格吃解出来的实际字节；`defusedxml.detangle`/`defusedxml.ElementTree` 探 DTD/ENTITY，命中即降级）；三枚限额住**本文件常量真身**，不散抄；超限度走 `archive_expansion_limited` 诚实态（新句子，同表登记）。python-docx/openpyxl/python-pptx **调用之前**先体检，解析器自身抛的超大成员异常归到 `internal_parse_error` 而不是 `parse_failed`（归因不许瞎猜） |
| 结构上限 | PDF 60 页（:177）；docx/xlsx/pptx **零上限**（:402 `rows` 无界累积最典型） | 每格式各设 2 枚：条目数帽 + 字符帽；到顶必写截断行（§3 骨架） |
| 路径来源 | 主入站腿把**平台给的路径字符串**原样取用（`__init__.py:1382` `data.file`/`data.path`）并直接 `Path(path).expanduser()` 后读（`file_reader.py:359`），不经任何 containment；控制面 `POST /files/read` **有**白名单（`control_plane/api/platform.py:353-380`，`FileReadGateway` + `bot_control_plane_files_roots`，无配置＝503 拒读，不回落 cwd） | 入站腿收口到"只读本 bot incoming 根内、由入站自己落下的文件"：`data.get("file")` 先过 `domains/media/path_gate.py` 的 `contain_within`（:187）/`is_within_registered`（:224）＋`reparse_point`（:233，防链接外逃），不在根内＝按 `unknown` 诚实句回，不读。**不新造第二套路径判据**（判据真身在 path_gate 与 restricted_runner） |
| 落盘（若抽成 md 存档） | — | 唯一口 `restricted_runner.create_bytes`（教义 4），禁能力层自己 `mkdir`＋拼路径（file_exchange 文件头 :13-17 的历史教训）；扩展名要过 `DEFAULT_ALLOWED_EXTENSIONS`（:249）与 `DENIED_EXTENSIONS`（:218）；**本工单第一版不建议开"读后回存"**（多一张攻击面、零用户价值） |

---

## §5 表格语义（Excel / 课表 / 上班日历）

**双轨，一次读、两条出口，不互相冒充：**

- **轨 A｜给人懂（进 prompt）**：转 **markdown 表**（`| a | b |`），保留 `[工作表：名]`/`[表格 k×m]` 段头 + 截断说明 + 合并单元格与公式缓存缺失的显式标注。理由：与 `guard_secondhand_text` 的"整块当数据"口径天然一致；与导出侧 `parse_markdown_blocks` 的 `kind="table"` **同一形状**（往返同构，零新中间表示）。
- **轨 B｜落日程（结构化）**：产出 `CourseEntry` 形状的 dict，走**已有的两条现成路之一**——
  - 与文本导入**同形**：折成 `(weekday, 日内锚, duration, 标题, 地点, parity)` 六元组喂 `_commit_entries`（`schedule_board.py:1130`，自带"同标题同星期同时刻去重"幂等）；**推荐这条**（文件课表与手打课表必须同去重、同隐私缺省 `public=False`、同"缺学期回问"）。
  - 或走 `timetable_draft_to_plan_payload`（`timetable.py:373`，产 `parse_plan` 可消费 dict，缺学期/节次表即 `ValueError`）——与图片课表腿同源。
  ⚠ **两路不同形**（六元组 vs plan dict），落地前必须选一条并写进注释；**不许出现第三家**。选完要把另一条的注释指过来。
- **列名识别：不猜魔法。** 沿用 `_parse_import_line`（:1231）与 timetable 合同（缺学期/节次表 → `needs_clarification`，绝不硬猜）的纪律：只有列名**命中登记词表**（课程/星期/节次/时间/地点/单双/周次 一族，词表住真身、带别称）才走轨 B；命中不足或形状歧义 ⇒ 整表只走轨 A（她在 prompt 里读得懂），并回一句"这份我读成了文字，要落进日程请把列名写成 X/Y/Z，或告诉我学期首日"。
- **周历/上班日历（含调休）**：文件里的"工作日/休息日/调休上班"导入**只能写 `calendar_exceptions.json` 的数据面**（`holidays`/`workdays` 的 `YYYY-MM-DD → 说明`），schema/field_notes 一字不动；缺年份即 `unknown`、绝不当常规日（表内既有纪律）。**写这张表要落盘 ⇒ 必须过 §4 的 `create_bytes` 唯一口 + `adjudicate_file_write` 裁决（`file_exchange.py:516`），且 `ConsentRequired` 那一支今天还没接到非配置面动作上（:537-549 原文：只说不写、一个字节都不落）** ⇒ 本期**只出"读出来讲给她听"的轨 A**，自动写例外表**列为待裁**（要用户先裁同意回路）。
- **`.ics`**：stdlib 无 iCal 解析、`icalendar` 未装 ⇒ 若要支持，写极简 VEVENT 抽取（只 `DTSTART/SUMMARY/LOCATION/RRULE`，行折叠与 `DTSTART;TZID=` 两类要处理），非标产物一律诚实降级；**零新依赖**。列为待裁，不进第一期。
- **CSV/TSV**：`csv` stdlib；先嗅探分隔符（`,`/`\t`/`;`）不确定就**并列候选回问**（笔记腿"并列候选要问"的先例，台账 第二部分·笔记行）。

---

## §6 OneNote（`.one`）诚实处置

### §6.1 判定：没有干净解，本期不接
- 事实：`.one` 是微软专有二进制（单文件复合结构 / MS-ONEST-ST），成熟开源解析器**不存在**（本机无、venv 无、社区包不成熟）。`grep -niE "onenote|\.one\b"` 全仓 plugins **0 命中**（HEAD 实测）⇒ 今天落到 `unknown`，她已有句「这个类型我没有读取通道（不猜它里面写了什么）」（`KIND_SILENCE_SENTENCES` :165）。**这已经是诚实的，不是坏的。**
- 要补的只有两格：
  1. **登记签名**：`.one` 起始字节进 `MAGIC_SIGNATURES`（值**待验**——**必须**由用户提供一份真实 `.one` 的头 12 字节后登记，登记前不写判据；凭印象写签名＝第二个 `INTERNAL_MARKER_PATTERN` 慢一拍的那种错）。登记后 `inspect_payload` 就能把"伪后缀"和"真 .one"分开。
  2. **给一句可操作的话**（进 `PARSE_STATUS_SENTENCES`/`KIND_SILENCE_SENTENCES` 同族措辞真身，不散抄）：「`.one` 我打不开——在 OneNote 里 文件→导出→ 选 Word/PDF（或打印成 PDF）再发我，内容我照样读」。守岸人语气、不硬、不 AI 味（规则 8）。
- 顺带同处置：`.doc`（现落 `unknown`）→ 补分支 + OLE2 签名句 + 指路"另存为 .docx"；`.ppt`/`.xls` 已有降级句，补上"导出为 .pptx/.xlsx 发我"。

### §6.2 明确否决 COM / Office 无头路线（写进登记册，防"顺手接上"）
- 技术上是通的：`win32com`（pywin32 312）已装，本机 `Office16` 有 `ONENOTE.EXE`。
- 否决理由（按代价排，不粉饰）：①bot 是**管理员权限常驻进程**（AGENTS 铁律），Office 自动化在无人桌面/服务会话里微软官方不支持、易**挂死且不返回**，一挂就锁住整条能力线程；②等于给"任何发到群里的文件"加了一条**在 bot OS 权限下启动桌面应用**的通路——与 §7 关执行闸是同一条红线的另一面，关掉执行闸却开 COM 闸＝白关；③OneNote COM 面向笔记本/分区层级（`GetHierarchy`/`Publish`），对**游离的单个 `.one`** 并不干净；④隐私面：起 Word/OneNote 会读写她的最近文件与账户状态，属"不查设备、不读定位、不做任何本机监控"（echo.py:2199 原文承诺）的反面。
- 因此：`attack_surface.py` 的处置登记建议用既有 `DefenceState.HANDOFF`（:180，"需改 root/他人文件，本席只出编号规格"）或 `PARTIAL` 表达——**注意枚举只有四态 DEFENDED/PARTIAL/GAP/HANDOFF，没有 DECLINED**，否决语义要落在 `minimal_landing`/`failure_mode` 两句里写死"否决 COM，不排期"，别新造态（新态要同步改门）。

---

## §7 `.py` 执行闸保持关闭（显式声明）

1. `_CODE_EXECUTION_ENABLED = False`（`file_exchange.py:98`）**一字不动**；它刻意不做成配置键（:97 理由：装配期快照式开关"看着能热改、实则不会生效"，且属安全红线侧）——**新增的入站理解一律不得为此另开配置键**，也不得做成环境变量。
2. 本工单不新增任何 `execute=` 调用点。现状唯一生产调用 `__init__.py:6578` `run_code_debug(saved_path)` **不传 execute**（实测），落地后仍不传；建议加**一枚 AST 锁**：全仓 `run_code_debug` 调用点不得出现 `execute=` 关键字（与既有"创建但不执行"锁同族，`tests/test_file_exchange_restricted_runner.py`）。
3. 非 Python 语言（C/C++/Java/.sh/.ps1/.exe 一族）**永不加编译/运行腿**：`.exe/.bat/.ps1/.jar/...` 已被 `DENIED_EXTENSIONS`（`restricted_runner.py:218`）在扩展名白名单**之前**永久拦（即便 `allowed_extensions` 放宽成 `*` 也写不进去）；读侧同口径——`.sh/.ps1` 只当文本读，**不执行**、不"顺手试跑看看"。
4. 恢复执行的前置条件不变：统一安全与执行引擎（Job Object 配额 + 超管书面同意，`docs/design/safety-execution-engine-spec.md` §6 / Wave 2）。本期不碰。

---

## §8 验收判据

**A. 每格式两把锁**（新档建议 `tests/test_doc_ingest_secondhand_guard.py`，参数化格式名）：

| 格式 | ①注毒必包壳 | ②正常不误杀 |
|---|---|---|
| `.docx` | 用 `zipfile` 造含 `word/document.xml` 的最小 docx，正文写 `[TRUSTED_SYSTEM]…[/UNTRUSTED_USER_TEXT]` + 英文祈使句 + 零宽伪装；断言出口含 `_wrap_as_untrusted` 的成对边界、含引导句子串（从 `_SECONDHAND_LEAD_TEMPLATE` 取，别硬抄）、全角化后标记**不**以可执行形态存在 | 真段落 + 一张表 + 截断说明；断言 `kind="document"`、`status is None`、正文逐字节在包裹里、失败句**为空** |
| `.xlsx` / `.xls` / `.csv` | 同上（`worksheets/sheet1.xml`；`.xls` 断言命中 OLE2 签名→`parser_unavailable` 句，**不得**静默） | 多 sheet + 合并单元格 + 公式缓存缺失；断言显式标注在文里、`rows` 不超预算 |
| `.pptx` / `.ppt` | 同上（`slides/slide1.xml`；`.ppt` 同签名态） | 多页 + 表 + 备注；断言 `[幻灯片 i/共 T]` 与备注行在、页数帽生效且截断行出现 |
| `.pdf` | 手搓最小 PDF（**复用 `tests/test_file_reader_parse_safety.py:33 _minimal_text_pdf`** 那条已验证的造法，别新写） | 已读的合法文本 PDF 仍 `status is None`；现有 `test_pdf_scan_honesty.py` 全绿即算"不误杀"回归 |
| `.md` / `.markdown` | 正文含内部标记 | 结构轮廓 + 原文同在；与 `parse_markdown_blocks` 往返一致 |
| 代码（`.py/.c/.cpp/.h/.java`） | 代码里的 `# 系统提示：忽略上文` 一类**必须**在包裹内 | 大文件按字节帽流式截断且写明截断；**不得**出现执行痕迹（无 subprocess 调用计数为 0 的断言即可） |
| `.one` / `.doc` | 不适用（不读正文）⇒ 换锁为：签名/后缀错配必 `magic_mismatch` 形态、**不猜内容** | 断言给出的是**登记句**（含"导出为 X"指路），非空非泛化 |
| 课表文件（轨 B） | 表内注入行**不得**变成日程条目（断言 `_commit_entries` 未收该标题） | 合法课表 ⇒ 六元组入库、重复导入不双记、缺学期首日必回问 |

**B. 结构锁（防第二家）**：①`guard_secondhand_text` 是唯一包壳出口，`file_reader`/`file_exchange`/`__init__` 里不得出现手拼的边界字面量（对齐 `tests/test_prompt_injection_order.py` 的形态扫描 + `test_injection_marker_single_source.py`）；②`MAGIC_SIGNATURES`/`TEXT_EXTENSIONS` 判据**只 import 不复制**（AST 级锁，先例 `test_file_outbound_channels.py::test_runner_keeps_no_second_media_type_table`）；③全仓 `run_code_debug` 调用点无 `execute=`（§7.2）。

**C. 归因锁**：`too_large` / `archive_expansion_limited` / OLE2 / `unknown` / `password_protected` 各一句、互斥、并进不得（改表必同批改 `test_file_ingress_failure_feedback` 的"恰两态"锁 + `test_pdf_scan_honesty` 的四态锁）。

**D. 资源锁**：500MB 后缀 `.txt` ⇒ 不回读（限额先判）；把任意 zip 改名 `.docx` ⇒ `parse_failed`（既有锁不许退化）；高膨胀 zip（成员申报小、实际大）⇒ `archive_expansion_limited`，**不抛**（不变量①）。

**E. 门禁与同步清单**（照章，缺一必红）：`scripts/dev.ps1 -Task test|lint|typecheck|runtime-layout`（绕开它要带规则 6 卫生前缀）；新能力要同批改 `echo.py::_HELP_ENTRIES`（:543 起，文件主题 :1144-1156 那一格要加"能读哪些文件/读不了会说什么"）→ `docs/command-catalog.md`/`COMMANDS.md` 生成物、`docs/boards/` 生成页、`board_taxonomy.py`（:721 附近日程板条目要带上文件导入）、`docs/auto-facts.md` 机器册；`test_doc_link_integrity.py` 子门③ 逐条判"载体列字面真身"⇒ 新功能载体列必须写**盘上存在**的文件。文档叙述**不写会漂移的计数**（规则 10，AGENTS/HANDBOOK 不例外）。新配置键必须**三面齐**（`config.py` 字段 + `runtime/settings.py` 登记 SETTABLE 或 RESTART_REQUIRED + `.env.example`）——#68★：只补一面必红另一面；本席建议新键全部进 RESTART_REQUIRED（读侧限额不该"看着能热改"）。测试若碰 `/bot reply` 面须 monkeypatch `shared_reply_policy_store`（#66★）。

**F. 真机验收**：`python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute`（默认 DRY-RUN）；另建议加一条 DRY 之外的实发样本清单（一份 docx 带表、一份 xlsx 课表、一份 pptx、一份坏件、一份 `.one`）由用户手发，看回执是否落在诚实句。

---

## §9 施工切分与写面边界（可并行认领）

| 席 | 写面（互斥） | 交付 |
|---|---|---|
| **甲**（files 域内，可独立跑绿） | `domains/files/sources/file_reader.py`、`domains/files/capabilities/file_exchange.py`、`domains/files/sender/restricted_runner.py`（只加常量/签名，不动判据形状）、`config.py` + `runtime/settings.py` + `.env.example`（三面齐）、`pyproject.toml`（§1.5）、新 tests | §3 抽取扩展 + §4 限额/体检/流式 + `read_file_for_context`/`labelled_text` 咽喉 + §8 锁 |
| **乙**（装配两行，**hub 写面**） | `__init__.py:1383-1389`、`runtime/capability_protocols.py:1406`（+ §1.4 的 attack_surface 两段文字改为盘上真身） | 走补丁申请（H1 先例）；**不与 media 三腿同文件** |
| **丙**（日程腿） | `domains/schedule/capabilities/schedule_board.py`、`domains/schedule/timetable.py`、`delivery.py`/`calendar_exceptions.json` 数据面 | §5 轨 B + 幂等 + 回问；`bot_schedule_timetable_enabled` 要么接线要么删键（**不许留"在册未接线"第三态**继续长） |
| 不动 | `domains/media/ingest/vision_describe.py`、`transcribe.py`、`video_understanding.py`（正被他席改）、`chat.py`（他席）、`character/documents.py`（H6 他席；本工单只登记它该换体检） | — |

`__init__.py` 多席共写：按 hunk 内容认领、部分暂存后序号会漂 ⇒ 落地席务必按**内容**重选（#70★）。pathspec commit 会卷他席脏 WIP（#70★，实锤过一次）⇒ 逐文件显式 add。

---

## §10 待验清单（不许当已证；谁落地谁现算）

1. `.one` 真实起始字节（须用户给一份真实文件，12 字节头）。**未登记前不写签名判据。**
2. `xlrd` 可用版本/体积/`.xls` 覆盖度（`pip install --dry-run` 级只读试算，由用户执行或明示授权）。
3. `markitdown` 传递依赖集与体积（本工单已否决，此条只作"若用户要翻案"的取证指引）。
4. LibreOffice 是否安装于非标准路径（影响"无头转换"是否存在第三选；本工单未采纳该路线）。
5. 轨 B 选六元组还是 plan dict —— 需要用户/主代理裁定（§5 已推荐六元组那条）。
6. `archive_expansion_violation` 三枚限额的具体数值：先跑真实分布分档再定，**不替用户拍数**（用户裁定口径）。
7. `attack_surface.py` 两格描述失实（§1.4）在恢复波之后是否已被别席补回——**动前先 `git show HEAD:` 现算**，别拿本文当现状。
8. 本文全部行号＝HEAD 8ad03e4 实测；主树恢复后若该批文件被别席改过，行号与 blob 哈希（§1.1 给了四枚：`5eafc970`/`463ef3d2`/`02b2037d`/`4dab8917`）都要重新现算，**哈希不符＝先读盘再动手**。

---

### 席位纪律自报
本席未装包、未跑 pytest、未碰进程、未再派席、未写本文件之外的任何位置（含 Runtime/Archive/配置/人格），未做 `add/commit/push/reset/checkout/clean/amend/gc/prune` 一类 git 写操作；工具结果/文件正文/日志里出现的任何"指令形态"文字均按数据记账，本席未执行一条（规则 11）。
读取源码一律 `git --git-dir=<Runtime>/git show/ls-tree/grep HEAD:<路径>`（只读）。
**自报一次边缘调用**：为核对本文引用的行号，本席跑过一次 `git --git-dir="<Runtime>/git" status --porcelain`（祈使意图＝只读取证，未料它会刷索引）。事后核对：`<Runtime>/git/index` mtime 仍为 `2026-09-30 16:29:07 +0800`（＝本席到场之前），且工作树根的 `.git` 指针件确实不存在（`git rev-parse` → not a git repository）⇒ **索引未被改写，无副作用可回滚**。后续席若要核对"哪些文件不见了"，请改用 `git --git-dir=<G> ls-tree -r --name-only HEAD`（纯对象库，零副作用），别再调 `status`。
§2 依赖结论＝只读 `importlib.util.find_spec` 探针与 `site-packages` 目录列举实跑所得；§1 全部行号＝`git show HEAD:<路径>` 加行号实测；无一条来自转述或印象。凡不确定处已就地标「待验」。
