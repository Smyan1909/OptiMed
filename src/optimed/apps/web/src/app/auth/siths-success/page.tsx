'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { logError } from '@/lib/logger';
import { useTranslations } from 'next-intl';

export default function SITHSSuccessPage() {
  const t = useTranslations('sithsSuccess');
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser } = useUser();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');

  useEffect(() => {
    const sessionId = searchParams.get('session_id');

    if (!sessionId) {
      logError('SITHS Success Page: No session_id in URL', new Error('Missing session_id'));
      router.push('/login?error=Authentication session not found');
      return;
    }

    // Store session ID
    localStorage.setItem('session_id', sessionId);

    // Fetch user info
    const fetchUser = async () => {
      try {
        const res = await fetch('/api/auth/me', {
          headers: {
            'X-Session-ID': sessionId
          }
        });

        if (!res.ok) {
          throw new Error('Failed to fetch user info');
        }

        const data = await res.json();
        setUser(data.user);
        setStatus('success');

        // Redirect to chat after a brief success message
        setTimeout(() => {
          router.push('/chat');
        }, 1500);
      } catch (err: any) {
        logError('SITHS Success Page: Failed to fetch user', err);
        setStatus('error');
        setTimeout(() => {
          router.push('/login?error=Failed to complete authentication');
        }, 2000);
      }
    };

    fetchUser();
  }, [searchParams, router, setUser]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-white">
        <div className="text-center space-y-4">
          <Loader2 className="h-12 w-12 animate-spin mx-auto text-blue-600" />
          <p className="text-lg font-medium text-gray-900">{t('loading.title')}</p>
          <p className="text-sm text-gray-600">{t('loading.subtitle')}</p>
        </div>
      </div>
    );
  }

  if (status === 'success') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-green-50 to-white">
        <div className="text-center space-y-4">
          <CheckCircle2 className="h-12 w-12 mx-auto text-green-600" />
          <p className="text-lg font-medium text-green-900">{t('success.title')}</p>
          <p className="text-sm text-gray-600">{t('success.subtitle')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-white">
      <div className="text-center space-y-4">
        <p className="text-lg font-medium text-red-900">{t('error.title')}</p>
        <p className="text-sm text-gray-600">{t('error.subtitle')}</p>
      </div>
    </div>
  );
}
