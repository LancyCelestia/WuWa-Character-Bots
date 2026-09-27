<!-- 派生件：由 probes/s764-requires-rows.py 现算，源头＝S744 矩阵 JSON＋十库 VERSION。
     重生成即覆盖，禁手改本表；改意图请改声明源的 策略/例外/豁免 三面。 -->

# 52 对期望投影行（落地态 ② cross_library_edges 的 kind=import-ast 全集）

锚：矩阵窗 HEAD=a5226ec 声明源sha=a76235f025024d69 矩阵生成于 2026-09-26T06:52:27Z

| # | 消费方 | 提供方 | 策略 | requires_min | requires_max_exclusive | 语句边 | 被消费符号 | 符号出现 |
|---:|---|---|---|---|---|---:|---:|---:|
| 1 | persona-chat-safety | media-entertainment | same-major | 0.0.1 | 1.0.0 | 10 | 23 | 23 |
| 2 | routing-dispatch | external-data-services | same-major | 0.0.1 | 1.0.0 | 15 | 23 | 23 |
| 3 | control-plane-observability | render-outbound | same-major | 0.0.1 | 1.0.0 | 13 | 18 | 22 |
| 4 | control-plane-observability | persona-chat-safety | same-major | 0.0.1 | 1.0.0 | 14 | 18 | 19 |
| 5 | control-plane-observability | media-entertainment | same-major | 0.0.1 | 1.0.0 | 11 | 18 | 18 |
| 6 | persona-chat-safety | memory-knowledge-notes | same-major | 0.0.1 | 1.0.0 | 5 | 15 | 15 |
| 7 | control-plane-observability | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 4 | 14 | 14 |
| 8 | external-data-services | render-outbound | same-major | 0.0.1 | 1.0.0 | 17 | 13 | 20 |
| 9 | routing-dispatch | media-entertainment | same-major | 0.0.1 | 1.0.0 | 9 | 12 | 12 |
| 10 | media-entertainment | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 16 | 11 | 20 |
| 11 | persona-chat-safety | render-outbound | same-major | 0.0.1 | 1.0.0 | 9 | 11 | 14 |
| 12 | persona-chat-safety | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 7 | 10 | 11 |
| 13 | schedule-automation | memory-knowledge-notes | same-major | 0.0.1 | 1.0.0 | 3 | 10 | 11 |
| 14 | media-entertainment | external-data-services | same-major | 0.0.1 | 1.0.0 | 9 | 9 | 12 |
| 15 | engineering-governance | external-data-services | same-major | 0.0.1 | 1.0.0 | 8 | 9 | 11 |
| 16 | media-entertainment | render-outbound | same-major | 0.0.1 | 1.0.0 | 21 | 8 | 27 |
| 17 | memory-knowledge-notes | external-data-services | same-major | 0.0.1 | 1.0.0 | 6 | 8 | 8 |
| 18 | media-entertainment | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 2 | 7 | 7 |
| 19 | schedule-automation | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 9 | 6 | 10 |
| 20 | persona-chat-safety | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 5 | 6 | 8 |
| 21 | ingress-protocol | render-outbound | same-major | 0.0.1 | 1.0.0 | 3 | 6 | 6 |
| 22 | routing-dispatch | schedule-automation | same-major | 0.0.1 | 1.0.0 | 6 | 5 | 6 |
| 23 | control-plane-observability | memory-knowledge-notes | same-major | 0.0.1 | 1.0.0 | 1 | 5 | 5 |
| 24 | render-outbound | external-data-services | same-major | 0.0.1 | 1.0.0 | 2 | 5 | 5 |
| 25 | media-entertainment | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 4 | 4 | 5 |
| 26 | external-data-services | media-entertainment | same-major | 0.0.1 | 1.0.0 | 2 | 4 | 4 |
| 27 | memory-knowledge-notes | persona-chat-safety | same-major | 0.0.1 | 1.0.0 | 1 | 4 | 4 |
| 28 | persona-chat-safety | external-data-services | same-major | 0.0.1 | 1.0.0 | 3 | 4 | 4 |
| 29 | persona-chat-safety | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 2 | 4 | 4 |
| 30 | routing-dispatch | persona-chat-safety | same-major | 0.0.1 | 1.0.0 | 4 | 4 | 4 |
| 31 | external-data-services | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 4 | 3 | 4 |
| 32 | routing-dispatch | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 3 | 3 | 4 |
| 33 | media-entertainment | persona-chat-safety | same-major | 0.0.1 | 1.0.0 | 3 | 3 | 3 |
| 34 | persona-chat-safety | schedule-automation | same-major | 0.0.1 | 1.0.0 | 3 | 3 | 3 |
| 35 | render-outbound | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 1 | 3 | 3 |
| 36 | media-entertainment | memory-knowledge-notes | same-major | 0.0.1 | 1.0.0 | 3 | 2 | 3 |
| 37 | memory-knowledge-notes | render-outbound | same-major | 0.0.1 | 1.0.0 | 2 | 2 | 3 |
| 38 | render-outbound | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 3 | 2 | 3 |
| 39 | render-outbound | media-entertainment | same-major | 0.0.1 | 1.0.0 | 2 | 2 | 3 |
| 40 | control-plane-observability | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 1 | 2 | 2 |
| 41 | external-data-services | persona-chat-safety | same-major | 0.0.1 | 1.0.0 | 2 | 2 | 2 |
| 42 | routing-dispatch | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 1 | 2 | 2 |
| 43 | schedule-automation | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 2 | 2 | 2 |
| 44 | schedule-automation | media-entertainment | same-major | 0.0.1 | 1.0.0 | 2 | 2 | 2 |
| 45 | control-plane-observability | engineering-governance | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 46 | engineering-governance | control-plane-observability | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 47 | external-data-services | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 48 | memory-knowledge-notes | ingress-protocol | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 49 | routing-dispatch | engineering-governance | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 50 | schedule-automation | external-data-services | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 51 | schedule-automation | render-outbound | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |
| 52 | schedule-automation | routing-dispatch | same-major | 0.0.1 | 1.0.0 | 1 | 1 | 1 |

守恒：行数 52 == pairs_with_edges 52；Σ语句边 261 == 跨库 261；Σ符号出现 399 == 399。
读法：本表逐对回答「拆库日谁需要钉谁的哪个区间」——缺省策略下 52 对全部自动可派生，
      真身里需要**手写**的只有偏离缺省的例外与显式豁免（本席首拍两集合均为空，见报告 §三）。
