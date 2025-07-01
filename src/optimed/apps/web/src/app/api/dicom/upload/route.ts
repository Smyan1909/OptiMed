import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    // Get session ID from request headers
    const sessionId = request.headers.get('x-session-id');
    
    // Get form data (multipart/form-data for file upload)
    const formData = await request.formData();
    
    const headers: Record<string, string> = {};
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const response = await fetch(`${process.env.API_BASE_URL || 'http://localhost:8000'}/dicom/upload`, {
      method: 'POST',
      headers,
      body: formData // Forward the form data directly
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('DICOM upload API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}