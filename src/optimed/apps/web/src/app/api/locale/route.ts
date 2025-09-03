import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { LOCALE_COOKIE, locales, defaultLocale } from "@/i18n/config";

export async function POST(request: Request) {
  try {
    const { locale } = await request.json();
    const target = (locales as readonly string[]).includes(locale) ? locale : defaultLocale;
    cookies().set(LOCALE_COOKIE, target, { path: "/", httpOnly: false, sameSite: "lax" });
    return NextResponse.json({ ok: true, locale: target });
  } catch (e) {
    return NextResponse.json({ ok: false }, { status: 400 });
  }
}

// Support robust language switching with a redirect
export async function GET(request: Request) {
  const url = new URL(request.url);
  const locale = url.searchParams.get('locale') || undefined;

  const base = process.env.FRONTEND_URL || url.origin;
  const redirectTo = new URL('/settings', base).toString();

  const target = (locales as readonly string[]).includes(locale || '') ? (locale as string) : defaultLocale;

  const res = NextResponse.redirect(redirectTo);
  res.cookies.set(LOCALE_COOKIE, target, { path: '/', httpOnly: false, sameSite: 'lax' });
  return res;
}


