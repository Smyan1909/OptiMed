import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { imageId: string } }
) {
  try {
    const sessionId = request.headers.get('x-session-id');
    const { searchParams } = new URL(request.url);
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    // Build query string for windowing parameters
    const queryParams = new URLSearchParams();
    if (searchParams.get('window_center')) {
      queryParams.set('window_center', searchParams.get('window_center')!);
    }
    if (searchParams.get('window_width')) {
      queryParams.set('window_width', searchParams.get('window_width')!);
    }
    
    const queryString = queryParams.toString();
    const url = `${process.env.API_BASE_URL || 'http://localhost:8000'}/dicom/images/${params.imageId}/pixel-data${queryString ? '?' + queryString : ''}`;
    
    const response = await fetch(url, { headers });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('DICOM pixel data API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}