import { NextRequest, NextResponse } from 'next/server';
import { logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/auth/ehr-login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body)
    });
    
    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error }, { status: response.status });
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    logError('EHR login API error', error);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}