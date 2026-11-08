import { Heading1, PageContent, Paragraph } from '../components/nlds/nlds';
import { useTranslation } from 'react-i18next';

export function HomePage() {
  const { t } = useTranslation();

  return (
    <PageContent>
      <Heading1>{t('app.title')}</Heading1>
      <Paragraph>{t('home.intro')}</Paragraph>
    </PageContent>
  );
}
