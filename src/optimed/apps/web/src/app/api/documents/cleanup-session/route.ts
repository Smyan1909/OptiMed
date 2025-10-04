import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    const sessionId = request.headers.get('X-Session-ID');

    if (!sessionId) {
      return NextResponse.json({ error: 'Session ID required' }, { status: 401 });
    }

    const backendUrl = `${BACKEND_URL}/documents/cleanup-session`;
    console.log('[API Route] Cleanup session - Backend URL:', backendUrl);

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'X-Session-ID': sessionId,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('[API Route] Backend cleanup failed:', response.status, errorText);
      return NextResponse.json(
        { error: `Backend error: ${errorText}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    console.log('[API Route] Cleanup successful:', data);

    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[API Route] Cleanup error:', error);
    return NextResponse.json(
      { error: error.message || 'Internal server error' },
      { status: 500 }
    );
  }
}
