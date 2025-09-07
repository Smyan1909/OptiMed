import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    const sessionCookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || sessionCookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    // Forward locale to backend for multilingual support
    try {
      const cookieStore = await cookies();
      const localeCookie = cookieStore.get('NEXT_LOCALE')?.value;
      const acceptLang = request.headers.get('accept-language') || localeCookie || undefined;
      if (acceptLang) {
        headers['Accept-Language'] = acceptLang;
      }
    } catch {}

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(
      `${baseUrl}/journal/autocomplete`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    );

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Autocomplete API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}