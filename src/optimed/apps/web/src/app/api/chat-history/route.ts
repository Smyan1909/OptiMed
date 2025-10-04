import { NextRequest, NextResponse } from 'next/server';
import { logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    // Get session ID from incoming request headers
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/chat-history`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError(`Chat history API error: ${error}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}