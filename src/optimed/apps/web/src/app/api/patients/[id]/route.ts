import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function GET(
  request: Request,
  context: any
) {
  try {
    // Get session ID from request headers or cookies
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {};
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    // Correct: fetch patient detail, not journal list
    const response = await fetch(`${baseUrl}/patients/${context.params.id}`, {
      headers
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Patient detail API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  context: any
) {
  try {
    const body = await (request as any).json();
    
    // Get session ID from request headers or cookies
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/patients/${context.params.id}/journal`, {
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
    console.error('Journal creation API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}