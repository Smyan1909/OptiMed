import { NextRequest, NextResponse } from 'next/server';
import { sanitizeDocumentId, sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const templateId = params.id;

    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string} = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo(`[TEMPLATES API] Fetching template: ${sanitizeDocumentId(templateId)}`);

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/${templateId}`;
    logInfo(`[TEMPLATES API] Backend URL: ${backendUrl}`);

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers
    });

    if (!response.ok) {
      const errorText = await response.text();
      logError(`[TEMPLATES API] Get error: ${response.status} ${errorText}`);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    logInfo(`[TEMPLATES API] Retrieved template: ${sanitizeDocumentId(templateId)}`);
    return NextResponse.json(data);
  } catch (error) {
    logError(`[TEMPLATES API] Get API error: ${error}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const templateId = params.id;

    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo(`[TEMPLATES API] Deleting template: ${sanitizeDocumentId(templateId)}`);

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/${templateId}`;
    logInfo(`[TEMPLATES API] Backend URL: ${backendUrl}`);

    const response = await fetch(backendUrl, {
      method: 'DELETE',
      headers
    });

    if (!response.ok) {
      const errorText = await response.text();
      logError(`[TEMPLATES API] Delete error: ${response.status} ${errorText}`);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    logInfo(`[TEMPLATES API] Deleted template: ${sanitizeDocumentId(templateId)}`);
    return NextResponse.json(data);
  } catch (error) {
    logError(`[TEMPLATES API] Delete API error: ${error}`);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}