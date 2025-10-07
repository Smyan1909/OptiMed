import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { sanitizePatientId, logInfo, logError } from '@/lib/logger';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: patientId } = await params;
    
    // Get session ID from request headers or cookies (following your existing pattern)
    const cookieStore = await cookies();
    const sessionId = request.headers.get('x-session-id') || cookieStore.get('session_id')?.value;
    
    const headers: Record<string, string> = {};
    
    // Add session header if available
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo('Patient journal: Fetching journal entries', { patientId: sanitizePatientId(patientId) });
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/patients/${patientId}/journal`, { headers });

    if (!response.ok) {
      const errorText = await response.text();
      logError('Patient journal: Backend journal API error', { status: response.status, error: errorText });
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    logInfo('Patient journal: Journal entries retrieved', { count: data.length });
    return NextResponse.json(data);
  } catch (error) {
    logError('Patient journal: Journal entries API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: patientId } = await params;
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
    logError('Create journal entry API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}