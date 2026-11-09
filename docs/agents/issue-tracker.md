# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

仓库：`LancyCelestia/WuWa-Character-Bots`（`git remote -v` 的 `origin`；`gh` 在 clone 内跑会自动认出）。

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`。长正文用 heredoc。
- **Read an issue**: `gh issue view <number> --comments`，配合 `jq` 过滤评论，并同时取 labels。
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label` / `--state` 过滤。
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** _（若本仓把外部 PR 当功能请求处理，改成 `yes`；`/triage` 读这个开关。）_

设为 `yes` 时，PR 走与 issue 相同的标签与状态，对应 `gh pr` 命令：

- **Read a PR**: `gh pr view <number> --comments`，diff 用 `gh pr diff <number>`。
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，只留 `authorAssociation` 为 `CONTRIBUTOR` / `FIRST_TIME_CONTRIBUTOR` / `NONE` 的（丢掉 `OWNER` / `MEMBER` / `COLLABORATOR`）。
- **Comment / label / close**: `gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 与 PR 共用一个编号空间，裸 `#42` 可能是任一种：先 `gh pr view 42`，失败再 `gh issue view 42`。

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`。**map** 是一张 issue，工单是它的 child issue。

- **Map**: 单张 issue，label `wayfinder:map`，正文承载 Notes / Decisions-so-far / Fog。`gh issue create --label wayfinder:map`。
- **Child ticket**: 挂到 map 下的 issue（GitHub sub-issues，走 `gh api` 的 sub-issues 端点）。sub-issues 不可用时，把 child 写进 map 正文的任务清单，并在 child 正文顶部写 `Part of #<map>`。labels：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。认领后 assign 给执行者。
- **Blocking**: 用 GitHub 原生 issue dependencies（UI 可见的规范表示）。`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是阻塞方的数字 **database id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，**不是** `#number`，也不是 `node_id`）。GitHub 用 `issue_dependencies_summary.blocked_by` 报未解阻塞（真正的闸）。dependencies 不可用时，退化为 child 正文顶部的 `Blocked by: #<n>, #<n>`。所有 blocker 都关闭才算解除。
- **Frontier query**: 列 map 的未关闭 children（`gh issue list --state open`，范围＝该 map 的 sub-issues / 任务清单），剔掉仍有未解 blocker（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行里还有未关的）或已有 assignee 的；按 map 顺序取第一个。
- **Claim**: `gh issue edit <n> --add-assignee @me`，这必须是本会话的第一次写操作。
- **Resolve**: `gh issue comment <n> --body "<answer>"` → `gh issue close <n>` → 往 map 的 Decisions-so-far 追加一条上下文指针（要点 + 链接）。
