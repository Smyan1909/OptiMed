import { NextRequest, NextResponse } from 'next/server';

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const url = new URL(request.url);
    const searchParams = url.searchParams;

    // Get session ID from incoming request headers
    const sessionId = request.headers.get('x-session-id');

    const headers: Record<string, string> = {};

    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    const resolvedParams = await params;
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const backendUrl = `${baseUrl}/documents/${encodeURIComponent(resolvedParams.id)}${searchParams.toString() ? '?' + searchParams.toString() : ''}`;

    const response = await fetch(backendUrl, {
      method: 'DELETE',
      headers
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Document delete API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}