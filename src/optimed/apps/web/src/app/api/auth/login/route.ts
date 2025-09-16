import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const res = await fetch(`${baseUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json({ error: text || 'Login failed' }, { status: res.status });
    }

    const data = JSON.parse(text);

    // Set session cookie if session_id present
    if (data?.session_id) {
      const cookieStore = await cookies();
      cookieStore.set('session_id', data.session_id, {
        httpOnly: true,
        secure: true,
        sameSite: 'lax',
        path: '/',
        maxAge: 60 * 60 * 24 * 7
      });
    }

    return NextResponse.json({ user: data.user, session_id: data.session_id, message: data.message });
  } catch (err) {
    console.error('Auth login route error:', err);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
