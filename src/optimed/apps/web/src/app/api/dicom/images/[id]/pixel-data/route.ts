import { NextResponse } from 'next/server';
import { logError } from '@/lib/logger';

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const sessionId = req.headers.get('x-session-id');
    const { searchParams } = new URL(req.url);
    
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
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const url = `${baseUrl}/dicom/images/${id}/pixel-data${queryString ? '?' + queryString : ''}`;
    
    const response = await fetch(url, { headers });
    
    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError('DICOM pixel data API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}