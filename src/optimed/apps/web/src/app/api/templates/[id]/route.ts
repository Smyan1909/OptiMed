import { NextRequest, NextResponse } from 'next/server';

export async function GET(
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

    console.log('🔄 [TEMPLATES API] Fetching template:', templateId);

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/${templateId}`;
    console.log('🎯 [TEMPLATES API] Backend URL:', backendUrl);

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ [TEMPLATES API] Get error:', response.status, errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    console.log('✅ [TEMPLATES API] Retrieved template:', templateId);
    return NextResponse.json(data);
  } catch (error) {
    console.error('❌ [TEMPLATES API] Get API error:', error);
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

    console.log('🔄 [TEMPLATES API] Deleting template:', templateId);

    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/templates/${templateId}`;
    console.log('🎯 [TEMPLATES API] Backend URL:', backendUrl);

    const response = await fetch(backendUrl, {
      method: 'DELETE',
      headers
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ [TEMPLATES API] Delete error:', response.status, errorText);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    console.log('✅ [TEMPLATES API] Deleted template:', templateId);
    return NextResponse.json(data);
  } catch (error) {
    console.error('❌ [TEMPLATES API] Delete API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}