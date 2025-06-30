"use client";
import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { completeEHRLogin } from '@/lib/api';

export default function EHRCallbackPage() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser, setIsAuthenticated } = useUser();

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const connectionId = localStorage.getItem('ehr_login_connection_id');

      if (!code || !state || !connectionId) {
        setStatus('error');
        setMessage('Missing required parameters for EHR authentication');
        return;
      }

      try {
        const data = await completeEHRLogin(connectionId, code, state);

        setStatus('success');
        setMessage(data.message);
        
        // Set user context
        setUser(data.user);
        setIsAuthenticated(true);
        
        // Store session
        localStorage.setItem('session_id', data.session_id);
        localStorage.removeItem('ehr_login_connection_id');
        
        // Redirect after success
        setTimeout(() => {
          router.push('/patients');
        }, 2000);
      } catch (error: any) {
        setStatus('error');
        setMessage(error.message || 'EHR authentication failed');
      }
    };

    handleCallback();
  }, [searchParams, router, setUser, setIsAuthenticated]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow-md text-center max-w-md">
        {status === 'loading' && (
          <>
            <div className="animate-spin h-8 w-8 border-4 border-green-500 border-t-transparent rounded-full mx-auto mb-4"></div>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Completing EHR Authentication</h2>
            <p className="text-gray-600">Setting up your account with EHR credentials...</p>
          </>
        )}
        
        {status === 'success' && (
          <>
            <div className="text-green-500 text-4xl mb-4">✅</div>
            <h2 className="text-lg font-semibold text-green-700 mb-2">EHR Authentication Successful!</h2>
            <p className="text-green-600 mb-4">{message}</p>
            <p className="text-sm text-gray-600">Redirecting to the patient dashboard...</p>
          </>
        )}
        
        {status === 'error' && (
          <>
            <div className="text-red-500 text-4xl mb-4">❌</div>
            <h2 className="text-lg font-semibold text-red-700 mb-2">Authentication Failed</h2>
            <p className="text-red-600 mb-4">{message}</p>
            <button 
              onClick={() => router.push('/login')} 
              className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              Return to Login
            </button>
          </>
        )}
      </div>
    </div>
  );
}