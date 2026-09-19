// fetch 流式 SSE 读取器（日志尾流专用）。
// 为什么不用 EventSource：控制面鉴权只认 Authorization: Bearer 头（auth.py：token 禁止进 URL/query），
// 而 EventSource 无法自定义请求头 → 必须用 fetch + ReadableStream 自实现。
// 帧格式（api/events.py）：`id: <cursor>` / `event: log|error` / `data: <json envelope>` / 空行分发；
// 心跳为注释行 `: heartbeat`。断线指数退避重连并回传 Last-Event-ID；410 cursor_expired 停止自动重连
// （events.py 约定：缺口须由用户显式选择重新订阅，客户端不得静默重置游标）。

import { getApiToken, logsStreamUrl, type LogEventRow } from './api-client';

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'gap' | 'auth_error' | 'stopped';

export interface StreamCallbacks {
  onStatus: (status: StreamStatus, info?: { attempt?: number; code?: string; message?: string }) => void;
  onEvent: (row: LogEventRow) => void;
  onHeartbeat: () => void;
  /** 游标超出保留窗口：自动重连已停止，等用户显式重新订阅。 */
  onGap: (message: string) => void;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export class LogsStreamClient {
  private controller: AbortController | null = null;
  private callbacks: StreamCallbacks | null = null;
  private cursor: string | null = null;
  private filters: { source?: string; category?: string } = {};
  private attempt = 0;
  private stopped = true;
  private timer: ReturnType<typeof setTimeout> | null = null;

  get lastCursor(): string | null {
    return this.cursor;
  }

  get running(): boolean {
    return !this.stopped;
  }

  /** 启动（可带初始 after 游标；不带的语义=回放当前保留窗口，events.py 口径）。 */
  start(options: { after?: string | null; source?: string; category?: string; callbacks: StreamCallbacks }): void {
    this.stopInternal();
    this.stopped = false;
    this.attempt = 0;
    this.cursor = options.after ?? null;
    this.filters = { source: options.source, category: options.category };
    this.callbacks = options.callbacks;
    this.connect();
  }

  /** 用户显式重新订阅：清空游标从当前保留窗口重放（410 缺口后的唯一合法恢复路径）。 */
  resubscribeFresh(): void {
    if (!this.callbacks) return;
    this.start({ after: null, source: this.filters.source, category: this.filters.category, callbacks: this.callbacks });
  }

  stop(): void {
    this.stopInternal();
    this.callbacks?.onStatus('stopped');
  }

  private stopInternal(): void {
    this.stopped = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.controller?.abort();
    this.controller = null;
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.attempt += 1;
    const delay = Math.min(BASE_BACKOFF_MS * 2 ** (this.attempt - 1), MAX_BACKOFF_MS);
    this.callbacks?.onStatus('reconnecting', { attempt: this.attempt });
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    this.controller = new AbortController();
    const { signal } = this.controller;

    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    const token = getApiToken('admin') ?? getApiToken('ro');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    // Last-Event-ID 优先于 after（events.py）；首连无游标则回放保留窗口。
    if (this.cursor !== null) headers['Last-Event-ID'] = this.cursor;

    let response: Response;
    try {
      this.callbacks?.onStatus(this.attempt === 0 ? 'connecting' : 'reconnecting', { attempt: this.attempt });
      response = await fetch(logsStreamUrl(this.filters), { headers, signal });
    } catch (error) {
      if (signal.aborted) return;
      this.scheduleReconnect();
      return;
    }

    if (!response.ok) {
      const code = await errorcode(response);
      // 410 游标过期：停止自动重连，缺口交用户决断（events.py 明文约定）。
      if (response.status === 410) {
        this.stopped = true;
        this.callbacks?.onGap(code.message);
        this.callbacks?.onStatus('gap', { code: code.code ?? undefined });
        return;
      }
      // 鉴权/未配置令牌/参数错误：重试无意义，停止并如实上报。
      if (response.status === 401 || response.status === 403 || response.status === 422 || response.status === 503) {
        this.stopped = true;
        this.callbacks?.onStatus('auth_error', { code: code.code ?? undefined, message: code.message });
        return;
      }
      // 429/5xx 抖动：退避重连。
      this.scheduleReconnect();
      return;
    }

    if (!response.body) {
      this.stopped = true;
      this.callbacks?.onStatus('auth_error', { message: '响应无正文流' });
      return;
    }

    // 连接建立：重置退避。
    this.attempt = 0;
    this.callbacks?.onStatus('open');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    // 帧累积状态跨 chunk 保持（一次 read 可能只拿到半帧）。
    let pendingId: string | null = null;
    let pendingEvent = 'message';
    let dataLines: string[] = [];

    const dispatch = (pendingId: string | null, pendingEvent: string, dataLines: string[]) => {
      if (pendingId !== null) this.cursor = pendingId;
      if (dataLines.length === 0) return;
      let payload: unknown;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        return; // 畸形帧丢弃（不中断流）。
      }
      const callbacks = this.callbacks;
      if (!callbacks) return;
      if (pendingEvent === 'error') {
        // 流内错误帧：{data:null, error:{code,...}}。
        const record = payload as { error?: { code?: string; message?: string } };
        const errorCode = record?.error?.code ?? '';
        if (errorCode === 'cursor_expired') {
          this.stopInternal();
          callbacks.onGap(record?.error?.message ?? '保留窗口已推进，当前订阅存在缺口。');
          callbacks.onStatus('gap', { code: errorCode });
          return;
        }
        if (errorCode === 'events_unavailable') {
          this.scheduleReconnect(); // 存储抖动：退避重连。
          return;
        }
        this.scheduleReconnect(); // 其余错误帧保守退避重连。
        return;
      }
      const record = payload as { data?: LogEventRow };
      if (record?.data) callbacks.onEvent(record.data);
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newlineAt: number;
        while ((newlineAt = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, newlineAt).replace(/\r$/, '');
          buffer = buffer.slice(newlineAt + 1);
          if (line === '') {
            dispatch(pendingId, pendingEvent, dataLines);
            pendingId = null;
            pendingEvent = 'message';
            dataLines = [];
            if (this.stopped) return;
          } else if (line.startsWith(':')) {
            this.callbacks?.onHeartbeat(); // 注释行 = 心跳。
          } else if (line.startsWith('id:')) {
            pendingId = line.slice(3).trim();
          } else if (line.startsWith('event:')) {
            pendingEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trimStart());
          }
        }
        if (this.stopped) return;
      }
    } catch {
      // 读流中断（网络断/服务重启）。
    }
    if (signal.aborted || this.stopped) return;
    this.scheduleReconnect(); // 服务端正常关流：续游标重连。
  }
}

async function errorcode(response: Response): Promise<{ code: string | null; message: string }> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    return { code: body?.error?.code ?? null, message: body?.error?.message ?? `HTTP ${response.status}` };
  } catch {
    return { code: null, message: `HTTP ${response.status}: ${response.statusText}` };
  }
}
