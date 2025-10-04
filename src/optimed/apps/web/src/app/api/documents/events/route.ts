import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  // Get session ID from query parameter
  const url = new URL(request.url);
  const sessionId = url.searchParams.get('session_id');

  console.log('[API Route] Session ID from query:', sessionId);

  if (!sessionId) {
    console.error('[API Route] No session ID in query parameter');
    return new Response('Unauthorized - No session', { status: 401 });
  }

  const backendUrl = `${BACKEND_URL}/documents/events`;
  console.log('[API Route] SSE connecting to:', backendUrl, 'with session:', sessionId.substring(0, 12));

  try {
    const response = await fetch(backendUrl, {
      headers: {
        'X-Session-ID': sessionId,
        'Accept': 'text/event-stream',
      },
    });

    if (!response.ok) {
      console.error('[API Route] SSE failed:', response.status);
      return new Response('SSE connection failed', { status: response.status });
    }

    // Forward SSE stream to client
    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error: any) {
    console.error('[API Route] SSE error:', error);
    return new Response(error.message || 'Internal server error', { status: 500 });
  }
}
