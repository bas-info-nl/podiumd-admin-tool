import { describe, expect, it } from 'vitest';

import { createI18n, defaultLanguage, resources, supportedLanguages } from './i18n';

function keysOf(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    keysOf(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe('i18n', () => {
  it('uses Dutch as the default language (ADR 0007)', async () => {
    const i18n = await createI18n();

    expect(defaultLanguage).toBe('nl');
    expect(i18n.language).toBe('nl');
    expect(i18n.t('app.title')).toBe('PodiumD Beheer');
  });

  it('offers English for development', async () => {
    const i18n = await createI18n('en');

    expect(supportedLanguages).toEqual(['nl', 'en']);
    expect(i18n.t('app.title')).toBe('PodiumD Admin');
  });

  it('falls back to Dutch for an unsupported language', async () => {
    const i18n = await createI18n('fr');

    expect(i18n.t('app.title')).toBe('PodiumD Beheer');
  });

  it('has the same keys in every language', () => {
    const dutchKeys = keysOf(resources.nl.translation).sort();

    for (const language of supportedLanguages) {
      expect(keysOf(resources[language].translation).sort()).toEqual(dutchKeys);
    }
  });
});
