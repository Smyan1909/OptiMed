import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { UserProvider } from "@/contexts/UserContext";
import { cookies } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { LOCALE_COOKIE, defaultLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "CLARA - AI Medical Diagnostic Assistant",
  description: "Advanced AI-powered medical diagnostic system",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const locale = (cookieStore.get(LOCALE_COOKIE)?.value || defaultLocale) as Locale;
  const messages = await getMessages(locale);

  return (
    <html lang={locale}>
      <body className={inter.className}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <UserProvider>
            {children}
          </UserProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}