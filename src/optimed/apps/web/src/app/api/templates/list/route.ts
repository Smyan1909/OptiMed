import { NextRequest } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    // Get query parameters
    const searchParams = request.nextUrl.searchParams;
    const includeSystem = searchParams.get('include_system');
    const language = searchParams.get('language');
    const templateType = searchParams.get('template_type');

    // Get session ID from headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    console.log('🔄 [TEMPLATES API] Fetching templates:', {
      includeSystem,
      language,
      templateType,
      sessionId
    });

    // Build query string
    const queryParams = new URLSearchParams();
    if (includeSystem !== null) queryParams.set('include_system', includeSystem);
    if (language) queryParams.set('language', language);
    if (templateType) queryParams.set('template_type', templateType);

    // Make request to backend
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/list?${queryParams.toString()}`;
    console.log('🎯 [TEMPLATES API] Backend URL:', backendUrl);

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers
    });

    if (!response.ok) {
      console.error('❌ [TEMPLATES API] Backend error:', response.status, response.statusText);
      const errorText = await response.text();
      return new Response(errorText, {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const data = await response.json();
    console.log('✅ [TEMPLATES API] Retrieved', data.templates?.length || 0, 'templates');

    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('❌ [TEMPLATES API] List error:', error);
    return new Response(JSON.stringify({ error: 'Failed to list templates' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}