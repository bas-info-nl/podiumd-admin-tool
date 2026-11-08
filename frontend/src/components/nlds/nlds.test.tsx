import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Heading1, PageContent, Paragraph } from './nlds';

// Test fixtures, not UI copy: kept in variables so i18next/no-literal-string stays strict.
const TITLE = 'Titel';
const TEXT = 'Tekst';

describe('NL Design System components', () => {
  it('renders semantic elements with the NL Design System classes', () => {
    render(
      <PageContent>
        <Heading1>{TITLE}</Heading1>
        <Paragraph>{TEXT}</Paragraph>
      </PageContent>,
    );

    expect(screen.getByRole('main')).toHaveClass('utrecht-page-content');
    expect(screen.getByRole('heading', { level: 1, name: 'Titel' })).toHaveClass(
      'utrecht-heading-1',
    );
    expect(screen.getByText('Tekst').tagName).toBe('P');
    expect(screen.getByText('Tekst')).toHaveClass('utrecht-paragraph');
  });

  it('merges extra class names and passes other props through', () => {
    render(
      <Heading1 className="extra" id="kop">
        {TITLE}
      </Heading1>,
    );

    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveClass('utrecht-heading-1', 'extra');
    expect(heading).toHaveAttribute('id', 'kop');
  });
});
