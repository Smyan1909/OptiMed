import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function GET(
  request: Request,
  context: any
) {
  try {
    const patientId = context.params.id;
    
    // Get session ID from request headers or cookies (following your existing pattern)
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {};
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    console.log(`Fetching journal entries for patient ${patientId}`);
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/patients/${patientId}/journal`, { headers });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend journal API error:', response.status, errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    console.log('Journal entries from backend:', data.length + ' entries');
    return NextResponse.json(data);
  } catch (error) {
    console.error('Journal entries API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  context: any
) {
  try {
    const patientId = context.params.id;
    const body = await (request as any).json();
    
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/patients/${patientId}/journal`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Create journal entry API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}