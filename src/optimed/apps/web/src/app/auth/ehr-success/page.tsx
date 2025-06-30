'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { Loader2, CheckCircle, XCircle, Hospital } from 'lucide-react';

export default function EHRSuccessPage() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('Processing EHR authentication...');
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser, setIsAuthenticated } = useUser();

  useEffect(() => {
    const handleSuccess = async () => {
      const sessionId = searchParams.get('session_id');
      const userId = searchParams.get('user_id');

      if (!sessionId || !userId) {
        setStatus('error');
        setMessage('Missing session data from EHR authentication');
        return;
      }

      try {
        // Store session data
        localStorage.setItem('session_id', sessionId);
        localStorage.setItem('user_id', userId);
        
        // Fetch user details using the API proxy
        const response = await fetch('/api/auth/me', {
          headers: {
            'X-Session-ID': sessionId
          }
        });

        if (response.ok) {
          const userData = await response.json();
          setUser(userData);
          setIsAuthenticated(true);
          
          setStatus('success');
          setMessage('EHR authentication successful! Redirecting to patients...');
          
          // Redirect to patients page after 2 seconds
          setTimeout(() => {
            router.push('/patients');
          }, 2000);
        } else {
          throw new Error('Failed to fetch user data');
        }
      } catch (error: any) {
        console.error('EHR success handling error:', error);
        setStatus('error');
        setMessage(`Authentication error: ${error.message}`);
      }
    };

    handleSuccess();
  }, [searchParams, router, setUser, setIsAuthenticated]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-green-50 to-white p-4">
      <div className="bg-white p-8 rounded-lg shadow-lg text-center max-w-md w-full">
        {status === 'loading' && (
          <>
            <div className="flex justify-center mb-4">
              <Loader2 className="h-12 w-12 animate-spin text-green-500" />
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              🏥 Completing EHR Authentication
            </h2>
            <p className="text-gray-600">{message}</p>
            <div className="mt-4 p-3 bg-blue-50 rounded-lg">
              <p className="text-sm text-blue-700">
                🔐 Securely linking your EHR credentials...
              </p>
            </div>
          </>
        )}
        
        {status === 'success' && (
          <>
            <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-green-700 mb-2">
              ✅ Authentication Successful!
            </h2>
            <p className="text-green-600 mb-4">{message}</p>
            <div className="bg-green-50 p-3 rounded-lg">
              <p className="text-sm text-green-700 font-medium mb-1">
                🔐 Your EHR credentials have been securely linked
              </p>
              <p className="text-xs text-green-600">
                You can now access patient data from your EHR system
              </p>
            </div>
            <div className="mt-4 flex items-center justify-center text-sm text-gray-500">
              <Hospital className="h-4 w-4 mr-1" />
              <span>Redirecting to Patient Dashboard...</span>
            </div>
          </>
        )}
        
        {status === 'error' && (
          <>
            <XCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-red-700 mb-2">
              ❌ Authentication Failed
            </h2>
            <p className="text-red-600 mb-4">{message}</p>
            <div className="space-y-2">
              <button 
                onClick={() => router.push('/login')} 
                className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
              >
                Try Again
              </button>
              <button 
                onClick={() => router.push('/patients')} 
                className="w-full bg-gray-200 hover:bg-gray-300 text-gray-700 px-4 py-2 rounded-lg transition-colors"
              >
                Continue Without EHR
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}