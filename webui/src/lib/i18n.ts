// i18n 基建移植自 AxonHub frontend/src/lib/i18n.ts（Apache-2.0，已注明修改）：
// 保留 glob 合并 locales 与语言探测；语种收敛为 zh-CN 优先（本项目用户面为中文）。
import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

function mergeTranslations(...translations: Array<Record<string, unknown>>) {
  return Object.assign({}, ...translations);
}

type LocaleModule = { default: Record<string, unknown> };

function getModuleDefaultExport(module: unknown): Record<string, unknown> {
  if (module && typeof module === 'object' && 'default' in module) {
    return (module as LocaleModule).default;
  }
  return module as Record<string, unknown>;
}

const enModules = import.meta.glob('../locales/en/*.json', { eager: true }) as Record<string, unknown>;
const zhCNModules = import.meta.glob('../locales/zh-CN/*.json', { eager: true }) as Record<string, unknown>;

const enTranslation = mergeTranslations(...Object.values(enModules).map(getModuleDefaultExport));
const zhTranslation = mergeTranslations(...Object.values(zhCNModules).map(getModuleDefaultExport));

const resources = {
  en: { translation: enTranslation },
  zh: { translation: zhTranslation },
  'zh-CN': { translation: zhTranslation },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'zh-CN',
    debug: false,
    supportedLngs: ['en', 'zh', 'zh-CN'],
    interpolation: {
      escapeValue: false, // React 已默认转义
    },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      convertDetectedLanguage: (lng: string) => {
        const normalized = lng.toLowerCase();
        if (normalized === 'zh-cn' || normalized.startsWith('zh-')) return 'zh-CN';
        return lng;
      },
    },
  });

export default i18n;
