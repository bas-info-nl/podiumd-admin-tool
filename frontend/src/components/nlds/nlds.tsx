/**
 * Thin React components on top of NL Design System CSS components
 * (@utrecht/component-library-css). We use the CSS components and design
 * tokens directly instead of a React component library, so the UI follows
 * NL Design System (ADR 0007) without depending on a React library's
 * peer dependencies.
 */
import type { ComponentPropsWithoutRef } from 'react';

function cx(...classes: (string | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

export function PageContent({ className, ...props }: ComponentPropsWithoutRef<'main'>) {
  return <main className={cx('utrecht-page-content', className)} {...props} />;
}

export function Heading1({ className, children, ...props }: ComponentPropsWithoutRef<'h1'>) {
  return (
    <h1 className={cx('utrecht-heading-1', className)} {...props}>
      {children}
    </h1>
  );
}

export function Paragraph({ className, ...props }: ComponentPropsWithoutRef<'p'>) {
  return <p className={cx('utrecht-paragraph', className)} {...props} />;
}
