import { NextRequest, NextResponse } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    // Get the form data from the request
    const formData = await request.formData();

    // Get session ID from incoming request headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo('Templates Upload API: Uploading template', {
      name: formData.get('name'),
      language: formData.get('language'),
      templateType: formData.get('template_type'),
      sessionId: sessionId ? sanitizeSessionId(sessionId) : null
    });

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/upload`;
    logInfo('Templates Upload API: Backend URL configured', { url: backendUrl });

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body: formData
    });

    if (!response.ok) {
      const errorText = await response.text();
      logError('Templates Upload API: Upload error', { status: response.status, error: errorText });
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    logInfo('Templates Upload API: Template uploaded', { templateId: data.template_id });
    return NextResponse.json(data);
  } catch (error) {
    logError('Templates Upload API: Upload API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}