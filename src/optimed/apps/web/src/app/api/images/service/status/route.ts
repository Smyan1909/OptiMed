import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    // Get session ID from request headers
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {};
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const response = await fetch(`${process.env.API_BASE_URL || 'http://localhost:8000'}/images/service/status`, {
      headers
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('[API Route] Image service status error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}