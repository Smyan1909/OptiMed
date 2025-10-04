import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (sessionId) headers['X-Session-ID'] = sessionId;

    await fetch(`${baseUrl}/auth/logout`, { method: 'POST', headers });

    // Clear cookie client-side context: return Set-Cookie header
    cookieStore.set('session_id', '', { httpOnly: true, secure: true, sameSite: 'lax', path: '/', maxAge: 0 });

    return NextResponse.json({ ok: true });
  } catch (err) {
    logError(`Auth logout route error: ${err}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
