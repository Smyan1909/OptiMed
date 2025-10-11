import { NextResponse } from 'next/server';
import { logError } from '@/lib/logger';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: sessionId } = await params;
    // Get session ID from incoming request headers
    const sessionIdHeader = request.headers.get('x-session-id');

    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };

    // Forward the session header to the backend
    if (sessionIdHeader) {
      headers['X-Session-ID'] = sessionIdHeader;
    }

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/sessions/${sessionId}/join`, {
      method: 'POST',
      headers
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError(`Session join API error: ${error}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}