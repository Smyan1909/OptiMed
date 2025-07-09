import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    // Get session ID from request headers
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {};
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }
    
    console.log(`[API Route] Fetching generated image: ${params.id}`);
    console.log(`[API Route] Session ID: ${sessionId}`);
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/images/generated/${params.id}`, {
      headers
    });
    
    console.log(`[API Route] Backend response status: ${response.status}`);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[API Route] Backend error: ${response.status} - ${errorText}`);
      return NextResponse.json({ error: errorText }, { status: response.status });
    }
    
    // Forward the image data directly
    const imageData = await response.blob();
    const contentType = response.headers.get('content-type') || 'image/png';
    const contentDisposition = response.headers.get('content-disposition') || 'inline; filename=generated_image.png';
    
    console.log(`[API Route] Successfully retrieved image, size: ${imageData.size} bytes`);
    
    return new NextResponse(imageData, {
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': contentDisposition,
        'Cache-Control': 'public, max-age=31536000'
      }
    });
    
  } catch (error) {
    console.error('[API Route] Image retrieval error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}