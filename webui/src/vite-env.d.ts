/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 控制面基址（dev proxy / 生产同源留空），如 http://127.0.0.1:8742 */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
