import {getRequestConfig} from 'next-intl/server';
import {locales, defaultLocale} from '@/i18n/config';

export default getRequestConfig(async ({locale}) => {
  const supported = locales as readonly string[];
  const target = supported.includes(locale) ? locale : defaultLocale;
  const messages = (await import(`./${target}.json`)).default;
  return {locale: target, messages};
});


