import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { i18n as I18n } from 'i18next';
import { useState } from 'react';
import { I18nextProvider } from 'react-i18next';
import { createBrowserRouter, RouterProvider } from 'react-router';

import { HomePage } from './pages/HomePage';

interface AppProps {
  i18n: I18n;
}

export function App({ i18n }: AppProps) {
  const [queryClient] = useState(() => new QueryClient());
  const [router] = useState(() => createBrowserRouter([{ path: '/', element: <HomePage /> }]));

  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nextProvider>
  );
}
