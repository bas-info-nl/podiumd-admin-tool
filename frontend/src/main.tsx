import '@utrecht/component-library-css/dist/index.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { createI18n } from './i18n/i18n';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('Missing #root element in index.html');
}

const i18n = await createI18n();

createRoot(container).render(
  <StrictMode>
    <App i18n={i18n} />
  </StrictMode>,
);
