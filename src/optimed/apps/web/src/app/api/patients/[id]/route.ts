import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    // Get session ID from request headers or cookies
    const sessionId = request.headers.get('x-session-id') || 
                     request.cookies.get('session_id')?.value;
    
    const headers: Record<string, string> = {};
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const response = await fetch(`${process.env.API_BASE_URL || 'http://localhost:8000'}/patients/${params.id}`, {
      headers
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Patient API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}