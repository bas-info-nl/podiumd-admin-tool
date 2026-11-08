import i18next, { type i18n as I18n } from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import nl from './locales/nl.json';

/** The UI is Dutch (ADR 0007); English exists for development (design D6). */
export const defaultLanguage = 'nl';
export const supportedLanguages = ['nl', 'en'] as const;
export type Language = (typeof supportedLanguages)[number];

export const resources = {
  nl: { translation: nl },
  en: { translation: en },
} as const satisfies Record<Language, { translation: typeof nl }>;

/**
 * Create an isolated i18next instance, so tests and the app never share
 * global state.
 */
export async function createI18n(language: string = defaultLanguage): Promise<I18n> {
  const instance = i18next.createInstance();
  await instance.use(initReactI18next).init({
    resources,
    lng: language,
    fallbackLng: defaultLanguage,
    supportedLngs: supportedLanguages,
    interpolation: {
      // React already escapes rendered values.
      escapeValue: false,
    },
  });
  return instance;
}
