import { NextResponse } from 'next/server';

export async function GET(
  request: Request,
  context: any
) {
  try {
    const { id } = context.params;
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/dicom/images/${id}`, { headers });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('DICOM image API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function DELETE(
  request: Request,
  context: any
) {
  try {
    const { id } = context.params;
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/dicom/images/${id}`,
      { method: 'DELETE', headers }
    );
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('DICOM delete API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}