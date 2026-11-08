import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './App';
import { createI18n } from './i18n/i18n';

describe('App', () => {
  it('shows the Dutch application title as the main heading', async () => {
    const i18n = await createI18n();

    render(<App i18n={i18n} />);

    expect(
      await screen.findByRole('heading', { level: 1, name: 'PodiumD Beheer' }),
    ).toBeInTheDocument();
  });
});
