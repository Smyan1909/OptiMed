export const locales = ["en", "sv"] as const;
export type Locale = typeof locales[number];

export const defaultLocale: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";

export const localeOptions: Array<{ value: Locale; label: string }> = [
  { value: "en", label: "English" },
  { value: "sv", label: "Svenska" }
];


