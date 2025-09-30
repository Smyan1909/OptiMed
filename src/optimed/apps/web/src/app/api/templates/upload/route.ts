import { NextRequest, NextResponse } from 'next/server';

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

    console.log('🔄 [TEMPLATES API] Uploading template:', {
      name: formData.get('name'),
      language: formData.get('language'),
      templateType: formData.get('template_type'),
      sessionId
    });

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/upload`;
    console.log('🎯 [TEMPLATES API] Backend URL:', backendUrl);

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body: formData
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ [TEMPLATES API] Upload error:', response.status, errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    console.log('✅ [TEMPLATES API] Template uploaded:', data.template_id);
    return NextResponse.json(data);
  } catch (error) {
    console.error('❌ [TEMPLATES API] Upload API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}