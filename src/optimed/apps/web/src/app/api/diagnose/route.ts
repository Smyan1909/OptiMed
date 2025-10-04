import { NextRequest, NextResponse } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

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
      logInfo('Diagnose API: Forwarding session header', { sessionId: sanitizeSessionId(sessionId) });
    } else {
      logInfo('Diagnose API: No session header found in request');
    }

    logInfo('Diagnose API: Making request to backend', { hasSession: !!sessionId });
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/diagnose`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      logError('Diagnose API: Backend error', { status: response.status, error: errorText });
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError('Diagnose API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}