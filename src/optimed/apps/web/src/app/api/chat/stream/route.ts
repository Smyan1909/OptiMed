import { NextRequest } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo(`[CHAT API] Forwarding streaming request to backend: endpoint=chat/stream, session=${sanitizeSessionId(sessionId)}`);

    // Make request to streaming endpoint
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/chat/stream`;
    logInfo(`[CHAT API] Backend URL: ${backendUrl}`);

    // Add timeout and abort controller for long-running requests
    const controller = new AbortController();
    const timeoutId = setTimeout(() => {
      logInfo('[CHAT API] Request timeout after 5 minutes');
      controller.abort();
    }, 300000); // 5 minute timeout
    
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);

    if (!response.ok) {
      logError(`[CHAT API] Backend error: ${response.status} ${response.statusText}`);
      throw new Error(`Backend error: ${response.status}`);
    }

    logInfo(`[CHAT API] Backend response received, content-type: ${response.headers.get('content-type')}`);
    logInfo('[CHAT API] Starting SSE forwarding');

    // Log the first chunk to debug
    if (response.body) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      return new Response(
        new ReadableStream({
          start(controller) {
            const pump = async (): Promise<void> => {
              try {
                while (true) {
                  const { done, value } = await reader.read();

                  if (done) {
                    logInfo('[CHAT API] Stream ended');
                    controller.close();
                    break;
                  }

                  const chunk = decoder.decode(value, { stream: true });
                  logInfo(`[CHAT API] Forwarding chunk: ${chunk.length} chars`);

                  controller.enqueue(value);
                }
              } catch (error) {
                logError(`[CHAT API] Stream error: ${error}`);
                if (error instanceof Error && error.name === 'AbortError') {
                  logInfo('[CHAT API] Stream aborted due to timeout');
                }
                controller.error(error);
              }
            };

            pump();
          }
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Session-ID',
          },
        }
      );
    } else {
      throw new Error('No response body from backend');
    }

  } catch (error) {
    logError(`[CHAT API] Streaming API error: ${error}`);
    return new Response(JSON.stringify({ error: 'Streaming failed' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}