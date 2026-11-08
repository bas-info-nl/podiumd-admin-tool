import AxeBuilder from '@axe-core/playwright';
import { expect } from '@playwright/test';
import { createBdd, test as base } from 'playwright-bdd';

interface Fixtures {
  /** Fails the scenario when the current page has WCAG 2.2 A/AA violations (ADR 0007). */
  expectAccessible: () => Promise<void>;
}

export const test = base.extend<Fixtures>({
  expectAccessible: async ({ page }, use) => {
    await use(async () => {
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(results.violations).toEqual([]);
    });
  },
});

export const { Given, When, Then } = createBdd(test);
