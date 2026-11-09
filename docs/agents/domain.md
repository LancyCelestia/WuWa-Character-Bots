# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**布局结论：multi-context。** 本仓在初始化时与用户确认为 multi-context —— 子项目各一份 `GLOSSARY.md`，根目录一份 `GLOSSARY-MAP.md` 指向它们。

## 现状：词条已建立（2026-10-19）

首次落词条发生在 issue #7（b · 命名/说明规范回到与代码一致的基线 + 术语表首立）：
根目录 `GLOSSARY-MAP.md` 指向主包那份 `plugins/bot_unified_runtime/GLOSSARY.md`。
本仓当前只有一个内容 context（主包），故索引只指一处；将来出现第二个 context 时，**在 `GLOSSARY-MAP.md` 加一行**，不建第二份索引。

旧名 `CONTEXT.md` / `CONTEXT-MAP.md`（新版技能只认 `GLOSSARY.md` 与 `GLOSSARY-MAP.md`）在本仓从未出现过，无需改名。

context 边界＝子项目的目录边界；词条只收「同一个词被当成两三种意思」的那些，不为占位糊空文件。

## Before exploring, read these

- **`GLOSSARY-MAP.md`** at the repo root if it exists: it points at one `GLOSSARY.md` per context. Read each one relevant to the topic.
- **`GLOSSARY.md`** in the context directory you're working in, if it exists.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Multi-context repo (presence of `GLOSSARY-MAP.md` at the root):

```
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← system-wide decisions
└── <context>/
    ├── GLOSSARY.md
    └── docs/adr/                      ← context-specific decisions
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the context's `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
