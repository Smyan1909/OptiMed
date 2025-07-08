import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { patientId: string } }
) {
  try {
    const { patientId } = params;
    
    // Get session ID from request headers or cookies (following your existing pattern)
    const sessionId = request.headers.get('x-session-id') || 
                     request.cookies.get('session_id')?.value;
    
    const headers: Record<string, string> = {};
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    console.log(`Fetching journal entries for patient ${patientId}`);
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(
      `${baseUrl}/patients/${patientId}/journal`,
      { headers }
    );

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend journal API error:', response.status, errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    console.log('Journal entries from backend:', data);
    return NextResponse.json(data);
  } catch (error) {
    console.error('Journal entries API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: { patientId: string } }
) {
  try {
    const { patientId } = params;
    const body = await request.json();
    
    const sessionId = request.headers.get('x-session-id') || 
                     request.cookies.get('session_id')?.value;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const response = await fetch(
      `${process.env.API_BASE_URL || 'http://localhost:8000'}/patients/${patientId}/journal`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    );

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