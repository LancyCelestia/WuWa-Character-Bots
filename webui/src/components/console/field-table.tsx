// 四列数据字典表（W15 T4）。
//
// 用户点名的「四列自然语言字典」：自然语言键名 / 键值 / 简介 / 说明 + 值。
// 文案一律从 `lib/field-dict.ts` 取，本文件**不写任何指标名称**——字典是唯一真身。
//
// 本文件最要紧的一条（用户点名要防的谎报）：
//   `availability === 'absent'` 的字段，值位置恒渲染「尚未采集」，**绝不允许渲染成 0 或 —**。
//   「库里没有」与「值是 0」是两件事；把前者画成后者就是编数据。
//   实现上是一道硬闸：absent 时**不读 `values[doc.key]`**（调用方传了 0 也只显示「尚未采集」），
//   所以「传了 0 就显示 0」这条路径根本不存在，而不是靠调用方自觉。
//
// 版式只走既有尺子：字号五档 fs-*、间距 4px 栅格、语义色 / tone-*、圆角 md/lg/xl/full。
// 列宽走 `grid` + `fr`（A5 唯一放行的比例轨道）：`flex-[2]` / `w-40` 这类都被门禁拒，
// 而 `DataGridRow` 只透传 children/className、不接 `title`（那是 patterns.tsx 的事，
// 本席不动它），所以宽档行用原生 `div` 复刻 DataGridRow 的行几何。
import type { ReactNode } from 'react';
import { fieldDoc, type FieldDoc } from '@/lib/field-dict';
import { UNKNOWN_VALUE } from '@/lib/format';
import { cn } from '@/lib/utils';
import { KvRow } from '@/components/console/panel';
import { DataGrid } from '@/components/patterns/patterns';

/** 未采集字段在值位置的显式标注（不阻塞、不恐吓红，用 warn 档）。 */
const ABSENT_TEXT = '尚未采集';

/** `说明` 列最终展示的文本：简介与来源只在这里拼一次，宽/窄两档共用同一个真相。 */
function detailOf(doc: FieldDoc): string {
  // absent 字段把来源挂进括号：读者要知道「查的是哪个库/哪一列才判定它没有」。
  return doc.availability === 'absent' ? `${doc.detail}（来源：${doc.source}）` : doc.detail;
}

/**
 * 值位置。absent 字段走独立分支，`value` 在此分支下**从不被读取**。
 * 没给值 = 这个值当前不可知，走全库唯一未知符号（lib/format 的 UNKNOWN_VALUE），不写字面量。
 */
function ValueCell({ doc, value }: { doc: FieldDoc; value?: ReactNode }) {
  if (doc.availability === 'absent') {
    return <span className='fs-caption text-tone-warn'>{ABSENT_TEXT}</span>;
  }
  return <span className='fs-body'>{value ?? UNKNOWN_VALUE}</span>;
}

/**
 * 单行。字段不认识时返回 null（不造空白行）。
 *
 * 宽档（`compact !== true`）：四列 —— 键名 / 键值 / 简介 / 说明 + 值。
 * 窄档（`compact === true`）：两列 —— 标签 / 值；键值、简介、说明折进行的 `title`。
 *   **说明文字不凭空消失**，只是换了承载形态（悬停可读全文）。
 */
export function FieldTableRow({ fieldKey, value, compact }: { fieldKey: string; value?: ReactNode; compact?: boolean }) {
  const doc = fieldDoc(fieldKey);
  if (!doc) return null;
  const detail = detailOf(doc);

  if (compact) {
    // 窄详情栏：两列。`title` 一次带全键值 + 简介 + 说明，悬停即可读到宽档的全文。
    // 用原生 div 而非 DataGridRow：后者只透传 children/className，不接 `title`，
    // 而「说明不许消失」这条只能靠 title 兑现。行几何照抄 DataGridRow。
    return (
      <div className='flex min-w-0 items-start gap-3 border-b py-2 last:border-b-0' title={`${doc.key} · ${doc.summary}\n${detail}`}>
        {/* 标签**不截断**：键值/简介/说明已折进 title，若标签也裁掉，窄栏里就只剩悬停可读。
            `break-words` 让长键名换行而不是溢出到隔壁玻璃。 */}
        <span className='min-w-0 flex-1 break-words fs-body text-foreground'>{doc.label}</span>
        <span className='shrink-0 text-right'>
          <ValueCell doc={doc} value={value} />
        </span>
      </div>
    );
  }

  return (
    // 行几何与 DataGridRow 一致（min-w-0 items-center gap-3 border-b py-3 last:border-b-0），
    // 只多挂一个 title —— 说明文字在窄视口下被截断时的兜底出口。
    <div className='grid min-w-0 items-start gap-3 border-b py-3 last:border-b-0 grid-cols-[minmax(0,2fr)_minmax(0,2fr)_minmax(0,2fr)_minmax(0,3fr)_auto]' title={detail}>
      <span className='min-w-0 fs-body text-foreground'>{doc.label}</span>
      <span className='min-w-0 truncate fs-caption font-mono text-muted-foreground'>{doc.key}</span>
      <span className='min-w-0 fs-caption text-muted-foreground'>{doc.summary}</span>
      <span className='min-w-0 fs-caption text-muted-foreground'>{detail}</span>
      <span className='shrink-0 text-right'>
        <ValueCell doc={doc} value={value} />
      </span>
    </div>
  );
}

/**
 * 四列数据字典表。
 * 消费 `FIELD_DICT`：传 key 数组，值用 `values` 覆盖（缺省显示「—」）。
 *
 * 不认识的 key 由 `FieldTableRow` 直接返回 null —— 这里不再前置过滤一遍：
 * 一道闸就够，多一道反而多一处可能与字典漂移的判定。
 */
export function FieldTable({
  keys,
  values,
  compact,
  className,
}: {
  /** 要渲染的字段键值（顺序即渲染顺序）。 */
  keys: readonly string[];
  /** 键值 → 实际数值的展示节点。没给的显示 `UNKNOWN_VALUE`（复用 lib/format.ts）。 */
  values?: Record<string, ReactNode>;
  /** 紧凑档：说明折成 title 提示，只留三列（窄详情栏用）。 */
  compact?: boolean;
  className?: string;
}) {
  return (
    <DataGrid className={cn('min-w-0', className)}>
      {keys.map((key) => (
        <FieldTableRow key={key} fieldKey={key} value={values?.[key]} compact={compact} />
      ))}
    </DataGrid>
  );
}

/**
 * 键值行形态（页面内的「已选中实体」摘要等）。
 * 仍是同一把闸：absent 字段恒「尚未采集」且**不吃** `value`——
 * 复用 `ValueCell` 而不是另写一套判定，免得两处口径漂移。
 */
export function FieldKvRow({ fieldKey, value }: { fieldKey: string; value?: ReactNode }) {
  const doc = fieldDoc(fieldKey);
  if (!doc) return null;
  return <KvRow label={doc.label} hint={doc.summary} value={<ValueCell doc={doc} value={value} />} />;
}
