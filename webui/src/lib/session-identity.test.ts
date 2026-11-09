// 会话身份链（D1–D4）的**纯函数**契约：平台 / 群或频道 / 用户ID / 昵称 / 头像状态。
//
// 为什么住这里而不是写进页面：本文件必须能被 `node --test src/lib/*.test.ts` 直接加载
// （零 React、零 `@/` 别名、零跨文件 import），页面只管渲染，口径只此一份。
//
// 三条硬规矩（用户裁定，页面与测试同守）：
//   ① 拿不到的字段显示「未采集」，**不许**留空白、不许填假值；
//   ② 平台归一只有 qq / telegram 两个枚举（不发明第三套），认不出的原样回显；
//   ③ 头像拿不到 URL 就降级首字占位，绝不破图。

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AVATAR_UNCOLLECTED,
  MISSING_LABEL,
  avatarInitial,
  avatarState,
  identityRows,
  normalizePlatform,
  platformLabel,
  sessionKindLabel,
} from './session-identity.ts';

/** 一条"什么都有"的审计身份记录（形状照 `stats/calls.identity.sessions[]`）。 */
const full = {
  kind: 'group' as const,
  platform: 'qq',
  group_id: '777',
  group_title: '守岸人测试群',
  user_id: '10001',
  calls: 3,
  users: [{ user_id: '10001', sender_nickname: '阿岚', calls: 3 }],
};

/** 迁移没跑到 / 老行：身份四件套全是 null。 */
const empty = {
  kind: 'group' as const,
  platform: null,
  group_id: null,
  group_title: null,
  user_id: null,
  calls: 1,
  users: [],
};

test('identityRows: 一条记录同时给出平台/群/群名/用户ID/昵称/头像', () => {
  const rows = identityRows(full);
  const byKey = new Map(rows.map((row) => [row.key, row]));

  assert.deepEqual(
    rows.map((row) => row.key),
    ['platform', 'channel', 'channelTitle', 'userId', 'nickname', 'avatar'],
  );
  assert.equal(byKey.get('platform')?.value, 'QQ');
  assert.equal(byKey.get('channel')?.value, '群 777');
  assert.equal(byKey.get('channelTitle')?.value, '守岸人测试群');
  assert.equal(byKey.get('userId')?.value, '10001');
  assert.equal(byKey.get('nickname')?.value, '阿岚');
  assert.equal(byKey.get('avatar')?.value, AVATAR_UNCOLLECTED);
  // 头像**永远**是未采集（审计链路里没有这个字段，见 D3）——这是本波如实留的缺口，
  // 不是漏做：其余五行必须真的采集到。
  assert.equal(byKey.get('avatar')?.collected, false);
  for (const row of rows) {
    if (row.key === 'avatar') continue;
    assert.equal(row.collected, true, `${row.key} 应当已采集`);
  }
});

test('identityRows: 缺字段明确标记「未采集」，不是 null / 空串', () => {
  const rows = identityRows(empty);

  for (const row of rows) {
    assert.equal(row.value, MISSING_LABEL, `${row.key} 必须显示未采集`);
    assert.equal(row.collected, false);
    assert.notEqual(row.value, '');
  }
});

test('identityRows: 群名单独缺失时只有那一行未采集，别的不受影响', () => {
  const rows = identityRows({ ...full, group_title: null });
  const byKey = new Map(rows.map((row) => [row.key, row]));

  assert.equal(byKey.get('channelTitle')?.value, MISSING_LABEL);
  assert.equal(byKey.get('channelTitle')?.collected, false);
  assert.equal(byKey.get('channel')?.value, '群 777');
  assert.equal(byKey.get('nickname')?.value, '阿岚');
});

test('identityRows: 私聊没有群号时频道行如实说私聊，不编群号', () => {
  const rows = identityRows({
    kind: 'private',
    platform: 'telegram',
    group_id: null,
    group_title: null,
    user_id: '10001',
    calls: 1,
    users: [{ user_id: '10001', sender_nickname: '私聊的人', calls: 1 }],
  });
  const byKey = new Map(rows.map((row) => [row.key, row]));

  assert.equal(byKey.get('channel')?.value, '私聊');
  assert.equal(byKey.get('nickname')?.value, '私聊的人');
  assert.equal(byKey.get('platform')?.value, 'Telegram');
});

test('normalizePlatform: 只有 qq / telegram 两个枚举，别名归到同一支', () => {
  for (const raw of ['qq', 'QQ', 'onebot', 'onebot.v11', 'nonebot', ' qq ']) {
    assert.equal(normalizePlatform(raw), 'qq', raw);
  }
  for (const raw of ['telegram', 'Telegram', 'tg']) {
    assert.equal(normalizePlatform(raw), 'telegram', raw);
  }
  for (const raw of ['', null, undefined, 'email', 'console']) {
    assert.equal(normalizePlatform(raw), 'unknown', String(raw));
  }
});

test('platformLabel: 认不出的平台原样回显，空才说未采集', () => {
  assert.equal(platformLabel('qq'), 'QQ');
  assert.equal(platformLabel('onebot'), 'QQ');
  assert.equal(platformLabel('telegram'), 'Telegram');
  // 生产库里确实有 email: 会话行 —— 不能把它谎称「未采集」，也不能硬塞进第三套枚举。
  assert.equal(platformLabel('email'), 'email');
  assert.equal(platformLabel(null), MISSING_LABEL);
  assert.equal(platformLabel('   '), MISSING_LABEL);
});

test('sessionKindLabel: 四种会话种类都有中文名，未知不猜', () => {
  assert.equal(sessionKindLabel('group'), '群');
  assert.equal(sessionKindLabel('private'), '私聊');
  assert.equal(sessionKindLabel('email'), '邮件');
  assert.equal(sessionKindLabel('system'), '系统');
  assert.equal(sessionKindLabel('whatever'), '系统');
});

test('avatarState: 审计链路里没有头像字段 → 未采集（不返回 URL 家族）', () => {
  assert.equal(avatarState(null), 'missing');
  assert.equal(avatarState(''), 'missing');
  assert.equal(avatarState('https://example.invalid/a.png'), 'ready');
});

test('avatarInitial: 昵称首字 → 无昵称回退用户ID尾号 → 都没有才占位符', () => {
  assert.equal(avatarInitial('阿岚', '10001'), '阿');
  assert.equal(avatarInitial('alice', '10001'), 'A');
  assert.equal(avatarInitial(null, '10001'), '1');
  assert.equal(avatarInitial('', ''), '?');
  assert.equal(avatarInitial(null, null), '?');
});
