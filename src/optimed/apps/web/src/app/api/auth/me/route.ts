import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const sessionId = request.headers.get('x-session-id');
  
  if (!sessionId) {
    return NextResponse.json({ error: 'No session ID provided' }, { status: 401 });
  }
  
  try {
    const response = await fetch(`${process.env.API_BASE_URL || 'http://localhost:8000'}/auth/me`, {
      headers: {
        'X-Session-ID': sessionId,
      }
    });
    
    if (!response.ok) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Auth me API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}