import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { logError } from '@/lib/logger';

export async function GET(
  request: Request,
  context: any
) {
  try {
    const { id, entryId } = context.params;

    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;

    const headers: Record<string, string> = {};
    if (sessionId) headers['X-Session-ID'] = sessionId;

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(
      `${baseUrl}/patients/${id}/journal/${entryId}`,
      { headers }
    );

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError(`Journal entry API error: ${error}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}