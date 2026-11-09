import { Users } from 'lucide-react';
import { PageHeader, SectionCard, CategoryChip } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type CallsData, type CallsIdentitySession } from '@/lib/api-client';
import { formatCount } from '@/lib/format';
import {
  MISSING_LABEL,
  avatarInitial,
  identityRows,
  sessionKindLabel,
} from '@/lib/session-identity';

// 会话身份页（台账 D1–D4）：平台 / 群或频道 / 群名 / 用户ID / 昵称 / 头像。
//
// 数据真身＝`/api/v1/stats/calls` 的 `data.identity`（后端 `control_plane/webui_stats.py`）
// ⇒ 四列落 `audit_records`，写入侧 `domains/ops/audit/logger.py` 在 bot 重启后**幂等**补齐。
//
// 两条硬规矩落在这里：
//   ① 拿不到的字段显示「未采集」（`identityRows` 已把 null/空串统一成它），不留空白；
//   ② 头像**结构性**拿不到（OneBot v11 的 sender 没有 avatar，审计也没有头像列），
//      所以一律走首字占位、不渲染 <img>（从根上没有破图可能）。

function SessionAvatar({ session }: { session: CallsIdentitySession }) {
  const nickname = session.users[0]?.sender_nickname ?? null;
  return (
    <span
      aria-hidden
      className='flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 fs-caption text-primary'
    >
      {avatarInitial(nickname, session.user_id)}
    </span>
  );
}

function SessionCard({ session }: { session: CallsIdentitySession }) {
  const rows = identityRows(session);
  return (
    <div className='surface flex flex-col gap-3 rounded-lg p-4'>
      <div className='flex min-w-0 items-center gap-3'>
        <SessionAvatar session={session} />
        <div className='flex min-w-0 flex-col gap-1'>
          <span className='flex min-w-0 items-center gap-2'>
            <span className='truncate fs-body'>{rows[1].value}</span>
            <CategoryChip label={sessionKindLabel(session.kind)} tone='info' />
            {session.group_id_source === 'session_id' && (
              // 存量行没有群号列，群号是从 `group_<gid>_<uid>` 会话键派生的——标出来，
              // 别让"库里记的"与"键里推的"在界面上长得一样。
              <CategoryChip label='群号派生' tone='flat' />
            )}
          </span>
          <span className='truncate fs-caption text-muted-foreground'>
            {rows[2].value} · 调用 {formatCount(session.calls)}
          </span>
        </div>
      </div>

      <dl className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
        {rows.map((row) => (
          <div key={row.key} className='flex min-w-0 items-baseline gap-2'>
            <dt className='w-24 shrink-0 fs-caption text-muted-foreground'>{row.label}</dt>
            <dd
              className={
                row.collected
                  ? 'min-w-0 truncate fs-caption'
                  : 'min-w-0 truncate fs-caption text-muted-foreground'
              }
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>

      {session.users.length > 0 && (
        <ul className='flex flex-col gap-1 border-t pt-3'>
          {session.users.map((user) => (
            <li key={user.user_id ?? 'unknown'} className='flex min-w-0 items-center gap-2 fs-caption'>
              <span className='shrink-0 font-mono'>{user.user_id ?? MISSING_LABEL}</span>
              <span className='min-w-0 truncate text-muted-foreground'>
                {user.sender_nickname ?? MISSING_LABEL}
              </span>
              <span className='ml-auto shrink-0 tabular-nums text-muted-foreground'>
                ×{formatCount(user.calls)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SessionsPage() {
  const query = useSemanticQuery<CallsData>(['sessions-identity', 'page'], () => controlApi.statsCalls(), {
    refetchInterval: 30_000,
  });

  if (query.state.phase !== 'ok') {
    return (
      <div className='flex w-full flex-col gap-4'>
        <PageHeader title='会话身份' subtitle='/api/v1/stats/calls · 平台 / 群 / 用户 / 昵称' />
        <SemanticState state={query.state} onRetry={query.refetch} />
      </div>
    );
  }

  // 旧后端没有 identity 块 ⇒ 整块按「未采集」降级，而不是当成"零个会话"。
  const identity = query.state.data.identity;
  const sessions = identity?.sessions ?? [];

  return (
    <div className='flex w-full flex-col gap-4'>
      <PageHeader
        title='会话身份'
        subtitle='/api/v1/stats/calls · 平台 / 群或频道 / 群名 / 用户ID / 昵称（24h 窗口）'
        actions={
          <span className='fs-caption text-muted-foreground'>
            会话 {formatCount(sessions.length)} 个 · 头像一律未采集
          </span>
        }
      />

      {!identity ? (
        <SectionCard title='这一页需要新版后端'>
          <p className='fs-caption text-muted-foreground'>
            当前 GET /api/v1/stats/calls 还没有 identity 块（旧构建）。所有身份字段显示「
            {MISSING_LABEL}」，不做任何猜测。
          </p>
        </SectionCard>
      ) : null}

      {identity && !identity.available ? (
        <SectionCard
          title={
            <span className='flex items-center gap-2'>
              <Users className='size-4' />
              身份四列还没入库
            </span>
          }
          description='平台 / 群ID / 群名 / 昵称 四列要等 bot 重启后首次写入时自动补齐（迁移幂等、可重复执行）'
        >
          <p className='fs-caption text-muted-foreground'>
            审计库当前还是 10 列版本，所以这四项如实显示「{MISSING_LABEL}」；群/私聊与用户ID
            仍可从 session 约定派生，先照实给出。重启前不改库、不猜值。
          </p>
        </SectionCard>
      ) : null}

      {sessions.length === 0 ? (
        <SectionCard title='窗口内没有会话'>
          <p className='py-6 text-center fs-caption text-muted-foreground'>
            最近 24 小时没有审计行；换窗口看调用统计页。
          </p>
        </SectionCard>
      ) : (
        <SectionCard
          title={`会话身份（${formatCount(sessions.length)}）`}
          description='按会话身份聚合：同一群人合一行，私聊/系统按用户各自成行'
        >
          <div className='flex flex-col gap-3'>
            {sessions.map((session) => (
              <SessionCard
                key={`${session.kind}-${session.group_id ?? session.user_id ?? 'x'}-${session.platform ?? 'n'}`}
                session={session}
              />
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  );
}
