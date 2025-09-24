/**
 * React hook for E2E encryption management
 */

import { useState, useEffect, useCallback } from 'react';
import { getEncryptionClient, E2EEncryptionClient } from '@/lib/encryption';

export interface UseEncryptionReturn {
  encryptionClient: E2EEncryptionClient;
  isEncryptionReady: boolean;
  setupSessionEncryption: (sessionId: string) => Promise<boolean>;
  hasSessionKey: (sessionId: string) => boolean;
  clearSessionKey: (sessionId: string) => void;
  encryptData: (data: any, sessionId: string) => Promise<any>;
  decryptData: (encryptedData: any, sessionId: string) => Promise<any>;
  error: string | null;
}

export function useEncryption(): UseEncryptionReturn {
  const [encryptionClient] = useState(() => getEncryptionClient());
  const [isEncryptionReady, setIsEncryptionReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Check if Web Crypto API is available
    if (typeof window !== 'undefined' && window.crypto && window.crypto.subtle) {
      setIsEncryptionReady(true);
    } else {
      setError('Web Crypto API not available. E2E encryption is disabled.');
      console.warn('Web Crypto API not available');
    }
  }, []);

  const setupSessionEncryption = useCallback(async (sessionId: string): Promise<boolean> => {
    if (!isEncryptionReady) {
      console.warn('Encryption not ready, skipping session setup');
      return false;
    }

    try {
      setError(null);
      const success = await encryptionClient.setupSessionEncryption(sessionId);

      if (!success) {
        setError('Failed to setup session encryption');
      }

      return success;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown encryption error';
      setError(errorMessage);
      console.error('Session encryption setup failed:', err);
      return false;
    }
  }, [encryptionClient, isEncryptionReady]);

  const hasSessionKey = useCallback((sessionId: string): boolean => {
    return encryptionClient.hasSessionKey(sessionId);
  }, [encryptionClient]);

  const clearSessionKey = useCallback((sessionId: string): void => {
    encryptionClient.clearSessionKey(sessionId);
  }, [encryptionClient]);

  const encryptData = useCallback(async (data: any, sessionId: string) => {
    if (!isEncryptionReady || !hasSessionKey(sessionId)) {
      console.warn('Encryption not available, returning unencrypted data');
      return data;
    }

    try {
      return await encryptionClient.encryptData(data, sessionId);
    } catch (err) {
      console.error('Data encryption failed:', err);
      setError(err instanceof Error ? err.message : 'Encryption failed');
      return data; // Fallback to unencrypted data
    }
  }, [encryptionClient, isEncryptionReady, hasSessionKey]);

  const decryptData = useCallback(async (encryptedData: any, sessionId: string) => {
    if (!isEncryptionReady || !hasSessionKey(sessionId)) {
      console.warn('Decryption not available, returning data as-is');
      return encryptedData;
    }

    // Check if data is actually encrypted
    if (!encryptedData?.encrypted) {
      return encryptedData;
    }

    try {
      return await encryptionClient.decryptData(encryptedData, sessionId);
    } catch (err) {
      console.error('Data decryption failed:', err);
      setError(err instanceof Error ? err.message : 'Decryption failed');
      return encryptedData; // Fallback to original data
    }
  }, [encryptionClient, isEncryptionReady, hasSessionKey]);

  return {
    encryptionClient,
    isEncryptionReady,
    setupSessionEncryption,
    hasSessionKey,
    clearSessionKey,
    encryptData,
    decryptData,
    error,
  };
}

/**
 * Hook for streaming response decryption
 */
export function useStreamDecryption(sessionId: string | null) {
  const { encryptionClient, isEncryptionReady, hasSessionKey } = useEncryption();

  const decryptStreamChunk = useCallback(async (chunk: string): Promise<string> => {
    if (!sessionId || !isEncryptionReady || !hasSessionKey(sessionId)) {
      return chunk;
    }

    try {
      return await encryptionClient.decryptStreamChunk(chunk, sessionId);
    } catch (error) {
      console.error('Stream chunk decryption failed:', error);
      return chunk; // Return original chunk on error
    }
  }, [encryptionClient, sessionId, isEncryptionReady, hasSessionKey]);

  return {
    decryptStreamChunk,
    isDecryptionReady: isEncryptionReady && sessionId ? hasSessionKey(sessionId) : false,
  };
}