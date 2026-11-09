# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

右列就是本仓实际使用的标签串，五枚均已在 `LancyCelestia/WuWa-Character-Bots` 建好；以后若要换词，改右列并同步在 GitHub 侧改名，别让两处漂移。

## 与其他已建标签的关系

`/wayfinder` 另需五枚标签（`wayfinder:map` 与 `wayfinder:research`/`prototype`/`grilling`/`task`），它们和 triage 五角色是两套词汇，不互相替代：triage 角色描述「这张票处在什么状态」，wayfinder 标签描述「这张票属于哪种类型」。
