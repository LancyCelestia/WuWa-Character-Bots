# Git 本地工作流（无需 harness）

这份文档说明怎么只用 git 本身更新、存档、回滚这个仓库。全部操作都在本地完成，
不需要任何 AI 工具；配合 `scripts/git.ps1` 可以把常用操作缩短成一条命令。

## 0. 前提约定

- `.env`、`data/`、`.venv/`、`research/` 里的下载源码**永远不进 git**（`.gitignore` 已配置）。
- 密钥、cookie、数据库、日志都放在 `.env` 和 `data/` 里，提交时不会带上。
- 换机器只需：克隆仓库 → 复制 `.env.example` 为 `.env` → 填配置 → `scripts/dev.ps1 install`。

## 0.5 提交信息规范（必须遵守）

每条 commit message 必须用中文写清两件事：

1. **改了什么**：这次提交具体修改了哪些内容；
2. **有什么效果**：修改后解决了什么问题或带来了什么收益。

示例：

```text
feat(config): 接入 SQLite ORM 底座，解决启动时无数据库的问题，并为后续 ORM 插件提供持久化支持
```

禁止使用 `update`、`fix`、`tmp` 这类没有说明的提交信息。
## 1. 第一次拿到仓库

```powershell
git clone <仓库地址> Bot-Character-Bots
cd Bot-Character-Bots
Copy-Item .env.example .env      # 本地配置，不会被 git 跟踪
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

## 2. 日常存档（推荐：每完成一个小改动就存一次）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 save "feat: 新增时梗层，让机器人能对特定时间梗给出符合人格的回应"
```

等价于 `git add -A && git commit -m "..."`。**存档粒度越小，回滚越精准。**

## 3. 打快照标签（"这版能跑"就标一下）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 tag v0.1-working
```

以后任何时刻都能回到这个点：

```powershell
git checkout v0.1-working          # 查看
git checkout -b fix-from-v0.1      # 或从它开新分支修
```

## 4. 更新（有远程仓库时）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 update
```

内部执行 `fetch` + `pull --ff-only`：只有"本地没有新提交"时才快进；
如果本地领先远程（分叉），只告警、绝不动工作区，防止把本地改动弄丢。

## 5. 回滚（出问题时）

先看历史：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 history 20
```

三种回滚方式，从安全到彻底：

| 方式 | 命令 | 效果 | 何时用 |
| --- | --- | --- | --- |
| 安全回滚 | `scripts/git.ps1 revert <提交号>` | 反向应用某次提交，历史保留 | 只想撤销某一笔、不想动后面的工作 |
| 硬回滚 | `scripts/git.ps1 rollback <数量>` | 丢弃最近 N 条提交（需输入 yes 确认） | 最近几步整体走错了，想直接退回 |
| 回到标签 | `git checkout <标签>` | 切换工作区到某个快照 | 回到"确定能跑"的版本 |

直接用原生 git 也可以：

```powershell
git reset --hard HEAD~2     # 丢弃最近 2 条提交
git reset --hard <commit>   # 回到指定提交
git checkout -- .           # 只丢弃未提交的改动
git stash                   # 未提交的改动先收起来（可 git stash pop 取回）
```

**注意：`reset --hard` 会真的删除那之后的提交，谨慎使用；未提交的改动先 `save` 或 `stash`。**

## 6. 加新功能的分支式做法

```powershell
git checkout -b feat/my-feature     # 开分支
# ... 改代码、跑 scripts/dev.ps1 verify ...
powershell -ExecutionPolicy Bypass -File scripts/git.ps1 save "feat: 新增xxx能力，解决xxx问题"
git checkout main                   # 完成后合并
git merge --ff-only feat/my-feature
```

## 7. 常见问题

- **忘了 .env 会不会被提交？** 不会，`.gitignore` 已忽略 `.env` 与 `data/`。用 `scripts/git.ps1 status` 确认改动列表里没有它们。
- **换行符**：`.gitattributes` 已统一（文本 LF、ps1 CRLF），Windows/macOS/Linux 混用不会互相污染。
- **想推到远程**：`git push`；本项目助手脚本**故意不代做 push**，推送时机由你决定。
