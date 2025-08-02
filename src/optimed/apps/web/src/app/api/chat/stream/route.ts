import { NextRequest } from 'next/server';

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

    console.log('🔄 [CHAT API] Forwarding streaming request to backend:', {
      endpoint: 'chat/stream',
      payload: body,
      sessionId
    });

    // Make request to streaming endpoint
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/chat/stream`;
    console.log('🎯 [CHAT API] Backend URL:', backendUrl);
    
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      console.error('❌ [CHAT API] Backend error:', response.status, response.statusText);
      throw new Error(`Backend error: ${response.status}`);
    }

    console.log('✅ [CHAT API] Backend response received, content-type:', response.headers.get('content-type'));
    console.log('📡 [CHAT API] Starting SSE forwarding...');

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
                    console.log('📡 [CHAT API] Stream ended');
                    controller.close();
                    break;
                  }
                  
                  const chunk = decoder.decode(value, { stream: true });
                  console.log('📦 [CHAT API] Forwarding chunk:', chunk.slice(0, 100) + '...');
                  
                  controller.enqueue(value);
                }
              } catch (error) {
                console.error('❌ [CHAT API] Stream error:', error);
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
    console.error('❌ [CHAT API] Streaming API error:', error);
    return new Response(JSON.stringify({ error: 'Streaming failed' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}