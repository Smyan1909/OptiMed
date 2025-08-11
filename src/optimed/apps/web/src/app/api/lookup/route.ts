import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const sessionId = request.headers.get('x-session-id');
    const acceptLanguage = request.headers.get('accept-language');

    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    if (sessionId) headers['X-Session-ID'] = sessionId;
    if (acceptLanguage) headers['Accept-Language'] = acceptLanguage;

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/lookup`;

    const resp = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });

    if (!resp.ok) {
      const text = await resp.text();
      return NextResponse.json({ error: text || 'Lookup failed' }, { status: resp.status });
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || 'Lookup failed' }, { status: 500 });
  }
}


