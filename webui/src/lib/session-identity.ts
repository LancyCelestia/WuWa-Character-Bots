// 会话身份链（台账 D1–D4）纯函数：平台 / 群或频道 / 用户ID / 昵称 / 头像状态。
//
// 数据真身＝`GET /api/v1/stats/calls` 的 `data.identity`
// （后端 `control_plane/webui_stats.py`；四列落 `audit_records`，写入侧由
// `domains/ops/audit/logger.py` 在 bot 重启后幂等补齐）。
//
// 本文件零 React、零 `@/` 别名、零跨文件 import —— 才能被
// `node --test src/lib/*.test.ts` 直接加载（同 route-path.ts / labels.ts 先例）。
//
// 三条硬规矩：
//   ① 拿不到的字段显示「未采集」，不留空白、不填假值；
//   ② 平台归一只有 qq / telegram 两个枚举（不发明第三套），认不出的原样回显；
//   ③ 头像拿不到 URL 就降级首字占位，绝不破图。

/** 所有"没采集到"的统一文案（比空串诚实：空串分不清"没采集"与"采集到空值"）。 */
export const MISSING_LABEL = '未采集';

/**
 * 头像在本链路里**结构性地**拿不到：
 * OneBot v11 的 `sender` 只有 user_id / nickname / card / role / title / level / sex /
 * age / area，**没有 avatar**；入库层没有头像列，审计也没有。要头像只能逐个用户调
 * `get_stranger_info`（`avatar` 字段存在），那是 N 次网络调用，不在只读统计链路上。
 * 所以这里如实标未采集，UI 走首字母占位。
 */
export const AVATAR_UNCOLLECTED = MISSING_LABEL;

/** 平台归一：只有两支 + unknown（不认的平台不进枚举，见 platformLabel）。 */
export type PlatformKind = 'qq' | 'telegram' | 'unknown';

/** 平台别名表 —— OneBot 家族（qq / onebot / nonebot）都是 QQ 侧。 */
const PLATFORM_ALIASES: Record<string, PlatformKind> = {
  qq: 'qq',
  onebot: 'qq',
  nonebot: 'qq',
  telegram: 'telegram',
  tg: 'telegram',
};

export type SessionKind = 'group' | 'private' | 'email' | 'system';

export interface IdentityUser {
  user_id?: string | null;
  sender_nickname?: string | null;
  calls?: number | null;
}

/** `identity.sessions[]` 的一行（后端每个会话身份聚合后的形状）。 */
export interface IdentitySession {
  kind?: string | null;
  platform?: string | null;
  group_id?: string | null;
  group_title?: string | null;
  user_id?: string | null;
  calls?: number | null;
  users?: IdentityUser[] | null;
}

export interface IdentityRow {
  /** 稳定键，React key 与测试断言都认它。 */
  key: 'platform' | 'channel' | 'channelTitle' | 'userId' | 'nickname' | 'avatar';
  label: string;
  value: string;
  /** false = 这个字段没采集到（值是「未采集」）；UI 据此降权显示。 */
  collected: boolean;
}

const ROW_LABELS: Record<IdentityRow['key'], string> = {
  platform: '平台',
  channel: '群或频道',
  channelTitle: '群名或频道名',
  userId: '用户ID',
  nickname: '昵称',
  avatar: '头像',
};

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
}

/** 平台串 → 归一枚举。`onebot.v11` 这类带后缀的按首段认。 */
export function normalizePlatform(raw: unknown): PlatformKind {
  const lower = text(raw).toLowerCase();
  if (!lower) return 'unknown';
  const direct = PLATFORM_ALIASES[lower];
  if (direct) return direct;
  const head = lower.split('.')[0] ?? lower;
  return PLATFORM_ALIASES[head] ?? 'unknown';
}

/**
 * 平台展示名。归一得出来 → 统一写法（QQ / Telegram）；归一不出 → **原样回显**
 * （生产库里确实有 `email:` 会话行，谎称「未采集」＝把已采集的事实抹掉）。
 */
export function platformLabel(raw: unknown): string {
  const kind = normalizePlatform(raw);
  if (kind === 'qq') return 'QQ';
  if (kind === 'telegram') return 'Telegram';
  return text(raw) || MISSING_LABEL;
}

/** 会话种类中文名。未知值一律「系统」（系统行派生自 session_id 约定外，不猜）。 */
export function sessionKindLabel(kind: unknown): string {
  switch (text(kind)) {
    case 'group':
      return '群';
    case 'private':
      return '私聊';
    case 'email':
      return '邮件';
    default:
      return '系统';
  }
}

/** 频道维度的一格：群给「群 <群号>」，私聊/邮件/系统给种类名。 */
function channelValue(session: IdentitySession): { value: string; collected: boolean } {
  const kind = text(session.kind) || 'system';
  if (kind === 'group') {
    const groupId = text(session.group_id);
    return groupId
      ? { value: `群 ${groupId}`, collected: true }
      : { value: MISSING_LABEL, collected: false };
  }
  return { value: sessionKindLabel(kind), collected: true };
}

function firstUser(session: IdentitySession): IdentityUser | undefined {
  const users = Array.isArray(session.users) ? session.users : [];
  return users[0];
}

/**
 * 一条会话身份 → 六行可渲染的事实（顺序固定：平台 / 群或频道 / 群名 / 用户ID / 昵称 / 头像）。
 * 缺的一律给「未采集」并把 collected 置 false —— 调用方不许再自己判空。
 */
export function identityRows(session: IdentitySession): IdentityRow[] {
  const user = firstUser(session);
  const channel = channelValue(session);
  const platform = text(session.platform);
  const userId = text(session.user_id) || text(user?.user_id);
  const nickname = text(user?.sender_nickname);
  const title = text(session.group_title);

  const row = (
    key: IdentityRow['key'],
    value: string,
    collected: boolean,
  ): IdentityRow => ({ key, label: ROW_LABELS[key], value, collected });

  return [
    row('platform', platformLabel(session.platform), Boolean(platform)),
    row('channel', channel.value, channel.collected),
    row('channelTitle', title || MISSING_LABEL, Boolean(title)),
    row('userId', userId || MISSING_LABEL, Boolean(userId)),
    row('nickname', nickname || MISSING_LABEL, Boolean(nickname)),
    row('avatar', AVATAR_UNCOLLECTED, false),
  ];
}

/** 头像状态：有可用 URL 才 ready，否则 missing（调用方据此走首字占位）。 */
export function avatarState(url: unknown): 'ready' | 'missing' {
  return text(url) ? 'ready' : 'missing';
}

/**
 * 首字母占位：昵称首字 → 没有昵称退到用户ID首字符 → 都没有给 `?`。
 * 拉丁字母转大写，中文原样（`阿岚` → `阿`），避免"占位符比标题还长"。
 */
export function avatarInitial(nickname: unknown, userId: unknown): string {
  const name = text(nickname);
  if (name) return (name[0] ?? '').toUpperCase() || '?';
  const id = text(userId);
  if (id) return (id[0] ?? '').toUpperCase() || '?';
  return '?';
}
