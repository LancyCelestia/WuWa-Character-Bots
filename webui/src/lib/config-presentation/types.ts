// 配置项展示层的类型定义（D 席：参数编辑）。
//
// 三层来源，**职责不重叠**：
//   ① `data/*.ts`（生成物）＝后端 `Config.model_fields` 全量 806 键 + 写面/冻结名册，
//      标题与说明由生成器按「键名词表 + docs/config-catalog-full.md 的作用列」推导；
//   ② `handwritten/*.ts`（手写）＝高频键的详细中文说明（讲清「调大了会怎样、调小了会怎样」）；
//   ③ 运行时 `GET /api/v1/config/catalog`＝**当前值、版本、can_write、敏感标记**的唯一真身。
//
// 🔴 静态层只说「这枚键是什么、怎么解释、该用什么控件」，**绝不**断言它此刻的值或能不能写。
// 能不能写一律以 live catalog 的 `can_write` 为准（后端 `ConfigControlService.catalog` 现算）。

/** 控件形态。由值类型自动选，手写层可覆盖。 */
export type ControlKind =
  | 'switch' // bool → 开关
  | 'number' // int / float → 数字输入 + 滑块（有上下界时）
  | 'select' // 枚举 → 单选
  | 'multiselect' // 固定集合里的多选
  | 'text' // 字符串 → 输入框
  | 'code' // JSON / 列表 / 字典 → 代码框 + 校验
  | 'readonly'; // 无写入口或安全键 → 只读展示

/** 三档覆盖度。判据见 `config-presentation.ts` 的 `TIER_LABEL`。 */
export type Tier =
  | 'T1' // 手写详细说明
  | 'T2' // 已登记写面，说明自动推导
  | 'T3'; // 仅 schema 元数据，无写入口

export interface ConfigOption {
  value: string;
  label: string;
  /** 选项级补充说明（可选）。 */
  desc?: string;
}

/** 写面归属。后端 `ConfigControlService.catalog` 的 `change_method` 是同一把尺。 */
export type ChangeScope =
  | 'hot' // 在 SETTABLE_KEYS：`POST /set` 真能写，消费方现读
  | 'restart' // 在 RESTART_REQUIRED_KEYS：改 .env 后重启
  | 'env-only'; // 两表都未登记：只读展示，改 .env 后重启也不保证

/** 一枚配置键的完整展示规格。 */
export interface ConfigField {
  /** 后端键名（大写，如 `BOT_CHAT_MODEL`）。 */
  key: string;
  /** 中文标题。 */
  title: string;
  /** 中文说明。T1 会讲清调大/调小的后果；T2/T3 是推导或文档原文。 */
  desc: string;
  /** 分组 id，对应 `CONFIG_GROUPS`。 */
  group: string;
  kind: ControlKind;
  tier: Tier;
  /** 写面归属（决定控件是否可提交）。 */
  scope: ChangeScope;
  /** 后端注解原文（`bool` / `int` / `list[str]` …），用于代码框的类型提示。 */
  type: string;
  /** 默认值的人类可读形态（已脱敏；`factory:` 表示默认由工厂产出）。 */
  default: string;
  min?: number;
  max?: number;
  step?: number;
  /** 数值单位（秒 / 天 / 字节 / % …）。 */
  unit?: string;
  options?: ConfigOption[];
  /** 安全键：值恒脱敏，永不提供编辑控件。 */
  secret?: boolean;
}

/** 手写层的条目：只写中文与控件，不重复 type/default（那些来自生成物）。 */
export interface HandwrittenEntry {
  title: string;
  desc: string;
  kind: ControlKind;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: ConfigOption[];
  secret?: boolean;
}

export const CONTROL_KIND_LABEL: Record<ControlKind, string> = {
  switch: '开关',
  number: '数字',
  select: '单选',
  multiselect: '多选',
  text: '文本',
  code: '代码',
  readonly: '只读',
};

export const TIER_LABEL: Record<Tier, string> = {
  T1: '详细说明',
  T2: '自动说明',
  T3: '仅展示',
};
