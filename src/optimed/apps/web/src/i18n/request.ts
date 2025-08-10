import { getRequestConfig } from 'next-intl/server';
import { locales, defaultLocale } from '@/i18n/config';

export default getRequestConfig(async ({ locale }) => {
  const supported = locales as readonly string[];
  const current = (locale ?? defaultLocale) as string;
  const target = supported.includes(current) ? current : defaultLocale;
  const messages = (await import(`./${target}.json`)).default;
  return { locale: target, messages };
});


