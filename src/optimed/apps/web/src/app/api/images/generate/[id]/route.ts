import { NextResponse } from 'next/server';
import { sanitizeSessionId, logInfo, logError } from '@/lib/logger';

export async function GET(
  request: Request,
  context: any
) {
  try {
    const { id } = context.params;
    // Get session ID from request headers
    const sessionId = request.headers.get('x-session-id');
    
    const headers: Record<string, string> = {};
    
    // Forward the session header to the backend
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    logInfo('Generated image: Fetching image', { imageId: id, sessionId: sessionId ? sanitizeSessionId(sessionId) : null });
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/images/generated/${id}`, {
      headers
    });

    logInfo('Generated image: Backend response received', { status: response.status });

    if (!response.ok) {
      const errorText = await response.text();
      logError('Generated image: Backend error', { status: response.status, error: errorText });
      return NextResponse.json({ error: errorText }, { status: response.status });
    }

    // Forward the image data directly
    const imageData = await response.blob();
    const contentType = response.headers.get('content-type') || 'image/png';
    const contentDisposition = response.headers.get('content-disposition') || 'inline; filename=generated_image.png';

    logInfo('Generated image: Successfully retrieved image', { size: imageData.size });
    
    return new NextResponse(imageData, {
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': contentDisposition,
        'Cache-Control': 'public, max-age=31536000'
      }
    });

  } catch (error) {
    logError('Generated image: Image retrieval error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}