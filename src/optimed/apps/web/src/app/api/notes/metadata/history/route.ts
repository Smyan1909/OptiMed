import { NextRequest } from 'next/server';
import { sanitizePatientId, sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function GET(request: NextRequest) {
  try {
    // Get query parameters
    const searchParams = request.nextUrl.searchParams;
    const patientId = searchParams.get('patient_id');
    const limit = searchParams.get('limit');

    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo(`[NOTES METADATA API] Fetching generation history: patientId=${sanitizePatientId(patientId)}, limit=${limit}, session=${sanitizeSessionId(sessionId)}`);

    // Build query string
    const queryParams = new URLSearchParams();
    if (patientId) queryParams.set('patient_id', patientId);
    if (limit) queryParams.set('limit', limit);

    // Make request to backend
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/notes/metadata/history?${queryParams.toString()}`;
    logInfo(`[NOTES METADATA API] Backend URL: ${backendUrl}`);

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers
    });

    if (!response.ok) {
      logError(`[NOTES METADATA API] Backend error: ${response.status} ${response.statusText}`);
      const errorText = await response.text();
      return new Response(errorText, {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const data = await response.json();
    logInfo(`[NOTES METADATA API] Retrieved ${data.history?.length || 0} records`);

    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    logError(`[NOTES METADATA API] History error: ${error}`);
    return new Response(JSON.stringify({ error: 'Failed to get generation history' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}