// 「主人授权口令」(owner consent) —— 与 Bearer API token 分开的第二把钥匙。
//
// 为什么需要：配置写入过安全门时，R1/R2 档要主人亲批。控制面没有入站消息，
// 后端因此提供一条**显式 opt-in** 的通道：部署同时配置
//   BOT_CONTROL_PLANE_ALLOW_OWNER_CONSENT=true
//   BOT_CONTROL_PLANE_OWNER_SECRET=<口令>
// 调用方在写请求头带 X-Owner-Consent。它只在本浏览器保存，不上传别处。
const KEY = 'webui:owner-consent';

export function getOwnerConsentSecret(): string {
  try {
    return (localStorage.getItem(KEY) ?? '').trim();
  } catch {
    return '';
  }
}

export function setOwnerConsentSecret(secret: string | null): void {
  try {
    const next = (secret ?? '').trim();
    if (next) localStorage.setItem(KEY, next);
    else localStorage.removeItem(KEY);
  } catch {
    // localStorage 不可用：本次会话无法保存，界面按「未配置」处理，不假装已存。
  }
}

export function ownerConsentHeaders(): Record<string, string> {
  const secret = getOwnerConsentSecret();
  return secret ? { 'X-Owner-Consent': secret } : {};
}
