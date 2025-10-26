import { NextRequest, NextResponse } from 'next/server';
import { logError } from '@/lib/logger';

export async function POST(request: NextRequest) {
  try {
    const baseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
    const res = await fetch(`${baseUrl}/auth/siths-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });

    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json(
        { error: text || 'Failed to initiate SITHS login' },
        { status: res.status }
      );
    }

    const data = JSON.parse(text);

    // Return redirect_url and state to frontend
    // Frontend will redirect user to GrandID
    return NextResponse.json({
      redirect_url: data.redirect_url,
      state: data.state,
      message: data.message
    });
  } catch (err) {
    logError('SITHS login route error', err);
    return NextResponse.json(
      { error: 'Server error during SITHS login initiation' },
      { status: 500 }
    );
  }
}
