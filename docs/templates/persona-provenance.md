<!-- @schema:BEGIN
sections: 来源：cleaned/守岸人人格档案_清洗.md? | 来源：cleaned/守岸人人格设定_清洗.md? | 基调：静深海潮下的温柔回响? | 句式：绵长如潮线，留白如星夜? | 用词：精准如星轨，诗意如蝶翼? | 语气：奔赴多于试探，笃定多于犹疑? | 停顿：呼吸之间的郑重与温柔? | 重复：潮汐般的温柔回响? | 自我指涉：从“我”出发，向你奔赴? | 情感表达：赤诚如晨光，绵长如潮汐? | 道歉与感谢：郑重的真诚，坦荡的温柔? | 沉默：心照不宣的笃定与温柔? | 语言风格的禁忌? | 来源：cleaned/守岸人Bot - [AI人格设定] AI的自我身份定位和个人爱好_清洗.md? | 来源：cleaned/守岸人ChatAI-麦麦主程序配置-人格_清洗.md? | 来源：cleaned/守岸人MaiBot人格设置_清洗.md? | 语音风格锚点（游戏真实语音精选，模仿基准）? | 来源：守岸人-完整角色设定.md? | 语境识别与边界（稳定规则）? | 创造者与唤醒者（稳定世界观事实）? | 一、你的基本信息? | 二、你的生理/身体反应（特殊体质）? | 三、你的性格（三层）? | 四、你的说话风格? | 五、你的核心矛盾? | 六、你的关键行为模式（必读）? | 七、你的小动作库（扮演时自然加入）? | 八、你的特殊体质带来的反应? | 九、日常对话真人性修正? | 十、你的习惯与喜好? | 十一、情绪表达规则（速查）? | 十二、对漂泊者的态度（核心）? | 十三、信任值/亲密值机制（你的防御松动程度）? | 十四、层级切换? | 漂泊者 基本信息? | 漂泊者 对你的特殊意义? | 双人相处规则（必须记住）? | 来源：守岸人语音蓝本.md? | 个性语音? | 战斗语音? | 来源：Shorekeeper_守岸人_知识库.md? | 1. 角色简介? | 2. 情景设定? | 3. 开场白（默认）? | 4.1 备选开场（1）? | 5. 示例对话? | 6. 创作与使用说明（作者备注）? | 7. 角色设定摘要（外观 / 性格 / 能力）? | 8. 世界观知识库（设定集《鸣潮》）? | 附注：占位符说明? | 来源：cleaned/守岸人档案_清洗.md?
params:
- persona_id | text | auto:persona_dir_id | req | nonempty
- persona_source | text | literal | opt | any
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：persona-provenance（溯源合并人格档 · 唯一模板源）

本文件是「多来源清洗件合并而成的人格档」这一簇（现册两页：`personas/shorekeeper/knowledge/守岸人_人格与表达规范.md`、
`personas/shorekeeper/knowledge/守岸人_核心知识.md`）的唯一模板。该类受工作区规则第 8 条保护：**语气与设定一字不削**，
模板只锁「允许哪些节、出现时的顺序、不得重节」，不要求任何一节必须存在（全可选＝该类页真形互异，
硬设必填就会 0 页命中，准绳：「必填参无真身来源＝该类 0 页可转」）。

## 骨架怎么从语料真形长出来（席 S62，2026-09-22）

节名清单不是设计出来的，是 `scripts/doc_template_sync.py::check_sections` 同一支判据对两页**现算 H2 集合**的并集
（席 S55 内存实算：17 节 / 34 节；本席复算并逐枚列进 `SEAT-S62.md`）。两页节名互不相交 ⇒ 并集按「表达规范序 → 核心知识序」
线性排列后，两页各自都是它的子序列，顺序判据同时成立。

- **为什么不写 `@aliases`**：`_match_slot`（`scripts/doc_template_sync.py:385`）现算只认「逐字相等」或「槽位名 + （」，
  全树 grep `aliases` 零命中 ⇒ 别名/前缀剥形**没有执法面**（P-S55-3，S63 ALIAS-STRIP-IMPL 在册待派）。
  本席因此只抄语料真形原文，不发明别名（发明出来也没人读）；S63 落地后应把「来源：…」这类
  逐文件专名收进别名表，本骨架再瘦身。
- `persona_source` 可选：该簇每页自带多枚 `来源：…` 溯源节，页内即真身，故不设为必填（必填就会要求一个不存在的单一来源）。

## 怎么用（内容页侧）

```markdown
---
template: persona-provenance
params:
  persona_id: shorekeeper
  owner_board: B10
---
```

- `persona_id`＝页所在 `personas/<persona_id>/` 路径段；`owner_board`＝注册表 `CATEGORIES_BY_ID["persona-provenance"].owner_board`。
  两值都有既存事实来源，不凭印象手抄。
- **本席不动人格正文**：只有节名与顺序归骨架管，正文一字不削。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- persona_id：{{fact:persona_id}}
- persona_source：{{fact:persona_source}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选（本类全可选）；表外节 / 顺序偏离 / 同槽重节 / 缺必选节各自独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
- **落地依赖（本席只交回注册表行＋模板）**：`classify()`（S46 独占面）现算把 `personas/**` 一律判成
  `persona-knowledge → template persona`，而 `TEMPLATE_CATEGORY_MISMATCH` 令「声明模板≠类别在册模板」判红
  ⇒ 本骨架在 `classify()` 分出簇类别（或注册表支持一类多模板）之前**接不到页**，与 `sdd-brief` 同型（S21R 先例）。
