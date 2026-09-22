# 路径重映射与树卫生 · 压缩→验证→移出

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.workspace-hygiene · 压缩→验证→移出

- 层级：一级 B10 → 二级 workspace-hygiene → 三级 `archive-procedure`
- 实现落点：`scripts/runtime_paths.py`、`docs/workspace-archive-policy.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「清理工作区」这件容易变成删库事故的动作固化成一条不可跳步的流水线：**压缩 → 验证 → 移出 → 附 manifest**。顺序本身就是护栏——先确认包能打开、内容在里面，才允许从源码区移除原件。

规程正文在 `docs/workspace-archive-policy.md` 第三节（本模块的规范真身），本页补执行细节与踩过的坑。

## 怎么调用

七个动作按序做完：

1. 停掉机器人、pytest、IDE 任务和相关 Python 进程（数据还在写就别归档）。
2. 确认目标**不是**运行所需的源码、配置、活动人格、知识源、数据库或 venv。
3. 压缩：`.zip` 或 `.tar.gz`，大目录优先 tar.gz。
4. 验证：zip 用 `testzip()` 或直接列目录清单（`tar -tzf`），确认包能正常打开；大改动另做副本比对。
5. 落位：压缩包放进 `ChatBot_Archive\YYYY-MM-DD\`（日期目录必须**直接**位于归档根下，禁止 `ChatBot_Archive\ChatBot_Archive\...` 的嵌套路径）。
6. 只有在第 4 步通过后，才从源码工作区移除原目录。
7. 在该日期目录的 `README.md`（manifest）里记录：原路径、压缩包用途、日期、敏感信息风险。

命令形态示例（PowerShell，逐步执行、不合并）：

```powershell
$root = 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
$archive = 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\2026-09-12'
tar -czf "$archive\<name>.tar.gz" -C $root <target>
tar -tzf "$archive\<name>.tar.gz" | Select-Object -First 20
# 清单确认无误后再 Remove-Item <root>\<target>
```

恢复：先解压到临时目录，**不要直接在压缩包内部修改**；测试性目录跑完再移出源码区。

## 开关与参数

无配置键、无脚本、无机器门——这是本入口最需要注意的一点：归档规程目前完全靠人（或 AI）按序执行，加上 `runtime-layout` 事后体检（移出后源码树不该再有该目录）。因此两条纪律要当成硬约束记：

- **归档前确认目录访问权限**，且真实 `.env`、token、cookie、数据库内容、邮件状态与完整 prompt 不得写进聊天、报告或归档说明。若密钥曾被复制到不安全位置，处置是**在安全渠道轮换**，而不是把值贴出来讨论。
- **归档即冻结**：不在归档包里就地编辑，也不回头重建已移出的历史目录（需要时按需解压单个文件）。先例包：`ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（旧文档，附 manifest）与 `2026-09-12\code-hygiene-20260912.zip`；另有 `2026-09-20\napcat-retire-backup-2026-09-20.zip`（协议端换代时保留的采集侧资产，内含 README 说明用途与启用方式）。

## 失败时看到什么

三种典型：

- **找不到被归档的东西**：manifest 写得不明（没记原路径或用途）。这就是第 7 步不许省的原因——manifest 是唯一索引，`docs/` 与 git 历史都覆盖不到移出源码区的目录。
- **包打不开**：第 4 步被跳过。补救是先从备份或 git 历史恢复原件，再重做流程，绝不「先删了再说」。
- **源码树残留运行数据目录与各类缓存**（`__pycache__`、`.pytest_cache` 等）：属清理而非归档问题，处置见 `runtime-paths.md` 末节（备份到系统临时目录 → 清 → 复跑 `runtime-layout`）。同族事故形态是把随包内置资产（如 weather 域的 NMC 区县码表）当缓存清掉，判据是「该文件在不在 git 跟踪集且有 `.gitignore` 否定规则」。

## 测试与验收

验收判据三问，缺一不算归档完成：包能列出清单吗？manifest 里能查到原路径与用途吗？源码区复跑 `dev.ps1 -Task runtime-layout` 是否 PASS？

`docs-check` 任务侧有一条弱锁：`README.md` 必须提到 `ChatBot_Archive`、`docs/workspace-archive-policy.md` 必须提到 `ChatBot_Archive`（`scripts/dev.ps1:Invoke-DocsCheck`），防的是「归档制度整体失踪」而不是单次违规。
