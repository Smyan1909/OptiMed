import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { patientId: string; entryId: string } }
) {
  try {
    const { patientId, entryId } = params;
    
    const response = await fetch(
      `${process.env.API_BASE_URL || 'http://localhost:8000'}/patients/${patientId}/journal/${entryId}`,
      {
        headers: {
          'X-Session-ID': request.cookies.get('session-id')?.value || '',
        },
      }
    );

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Journal entry API error:', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}