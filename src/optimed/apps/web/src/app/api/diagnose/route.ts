import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    // Get session ID from incoming request headers (sent by frontend)
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
      console.log(`[API Route] Forwarding session header: ${sessionId}`);
    } else {
      console.log(`[API Route] No session header found in request`);
    }
    
    console.log(`[API Route] Making request to backend with headers:`, headers);
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/diagnose`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[API Route] Backend error: ${response.status} - ${errorText}`);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Diagnose API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}