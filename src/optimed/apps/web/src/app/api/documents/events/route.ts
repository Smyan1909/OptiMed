import { NextRequest } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  // Get session ID from query parameter
  const url = new URL(request.url);
  const sessionId = url.searchParams.get('session_id');

  logInfo('Documents Events: Session ID from query', { sessionId: sessionId ? sanitizeSessionId(sessionId) : null });

  if (!sessionId) {
    logError('Documents Events: No session ID in query parameter');
    return new Response('Unauthorized - No session', { status: 401 });
  }

  const backendUrl = `${BACKEND_URL}/documents/events`;
  logInfo('Documents Events: SSE connecting to backend', { sessionId: sanitizeSessionId(sessionId) });

  try {
    const response = await fetch(backendUrl, {
      headers: {
        'X-Session-ID': sessionId,
        'Accept': 'text/event-stream',
      },
    });

    if (!response.ok) {
      logError('Documents Events: SSE failed', { status: response.status });
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
    logError('Documents Events: SSE error', error);
    return new Response(error.message || 'Internal server error', { status: 500 });
  }
}
