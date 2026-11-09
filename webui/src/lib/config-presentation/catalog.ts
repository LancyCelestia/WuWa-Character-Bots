// 生成物聚合器：把各分组数据模块拼成一张表（主文件只聚合，不写数据）。
// 为什么要静态聚合而不是按组懒加载：设置页的硬判据是「全局搜索能搜到每一枚键」，
// 懒加载会让未展开分组的键搜不到。数据是纯字符串常量（gzip 后约 20KB），
// 换来搜索一次命中，是刻意的取舍。
import type { ConfigField } from './types.ts';
import { CHAT_FIELDS } from './data/chat.ts';
import { REPLY_FIELDS } from './data/reply.ts';
import { PERSONA_FIELDS } from './data/persona.ts';
import { AFFINITY_FIELDS } from './data/affinity.ts';
import { MEMORY_FIELDS } from './data/memory.ts';
import { WEB_FIELDS } from './data/web.ts';
import { TTS_FIELDS } from './data/tts.ts';
import { MEDIA_FIELDS } from './data/media.ts';
import { MEME_FIELDS } from './data/meme.ts';
import { POKE_FIELDS } from './data/poke.ts';
import { RATE_FIELDS } from './data/rate.ts';
import { GROUP_FIELDS } from './data/group.ts';
import { SUBSCRIBE_FIELDS } from './data/subscribe.ts';
import { MUSIC_FIELDS } from './data/music.ts';
import { WEATHER_FIELDS } from './data/weather.ts';
import { FINANCE_FIELDS } from './data/finance.ts';
import { SCHEDULE_FIELDS } from './data/schedule.ts';
import { CAMPUS_FIELDS } from './data/campus.ts';
import { EMERGENCY_FIELDS } from './data/emergency.ts';
import { CONTENT_FIELDS } from './data/content.ts';
import { RENDER_FIELDS } from './data/render.ts';
import { OUTBOUND_FIELDS } from './data/outbound.ts';
import { API_FIELDS } from './data/api.ts';
import { RUNTIME_FIELDS } from './data/runtime.ts';
import { CONTROL_FIELDS } from './data/control.ts';
import { MODEL_FIELDS } from './data/model.ts';
import { MISC_FIELDS } from './data/misc.ts';

export const GENERATED_FIELDS: ConfigField[] = [
  ...CHAT_FIELDS,
  ...REPLY_FIELDS,
  ...PERSONA_FIELDS,
  ...AFFINITY_FIELDS,
  ...MEMORY_FIELDS,
  ...WEB_FIELDS,
  ...TTS_FIELDS,
  ...MEDIA_FIELDS,
  ...MEME_FIELDS,
  ...POKE_FIELDS,
  ...RATE_FIELDS,
  ...GROUP_FIELDS,
  ...SUBSCRIBE_FIELDS,
  ...MUSIC_FIELDS,
  ...WEATHER_FIELDS,
  ...FINANCE_FIELDS,
  ...SCHEDULE_FIELDS,
  ...CAMPUS_FIELDS,
  ...EMERGENCY_FIELDS,
  ...CONTENT_FIELDS,
  ...RENDER_FIELDS,
  ...OUTBOUND_FIELDS,
  ...API_FIELDS,
  ...RUNTIME_FIELDS,
  ...CONTROL_FIELDS,
  ...MODEL_FIELDS,
  ...MISC_FIELDS,
];
