import { NextRequest, NextResponse } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function GET(request: NextRequest) {
  try {
    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    if (!sessionId) {
      logError('[TRANSCRIBE TOKEN API] No session ID provided');
      return NextResponse.json(
        { error: 'Authentication required' },
        { status: 401 }
      );
    }

    logInfo(`[TRANSCRIBE TOKEN API] Fetching token for session: ${sanitizeSessionId(sessionId)}`);

    // Forward to backend to get Corti token
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/transcribe/token`;

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        'X-Session-ID': sessionId,
        'Content-Type': 'application/json'
      }
    });

    if (!response.ok) {
      const errorText = await response.text();
      logError(`[TRANSCRIBE TOKEN API] Backend error: ${response.status} ${response.statusText} - ${errorText}`);
      throw new Error(`Backend error: ${response.status}`);
    }

    const data = await response.json();
    logInfo(`[TRANSCRIBE TOKEN API] Token received successfully for session: ${sanitizeSessionId(sessionId)}`);

    return NextResponse.json(data);

  } catch (error: any) {
    logError(`[TRANSCRIBE TOKEN API] Error: ${error.message}`);
    return NextResponse.json(
      { error: 'Failed to get transcription token' },
      { status: 500 }
    );
  }
}
