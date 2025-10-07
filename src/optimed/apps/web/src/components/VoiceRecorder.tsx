"use client";

import { useState, useEffect } from 'react';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import { useCortiDictation } from '@/hooks/useCortiDictation';
import { logInfo, logError } from '@/lib/logger';

interface VoiceRecorderProps {
  onTranscriptComplete: (text: string) => void;
  onInterimTranscript?: (text: string) => void;  // Real-time interim results
  disabled?: boolean;
  language?: string;
}

const getAuthHeaders = () => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const authToken = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
  if (authToken) {
    headers['X-Session-ID'] = authToken;
  }
  return headers;
};

export function VoiceRecorder({ onTranscriptComplete, onInterimTranscript, disabled = false, language = 'en' }: VoiceRecorderProps) {
  const {
    isRecording,
    isReady,
    transcript,
    interimTranscript,
    error,
    startRecording,
    stopRecording,
    reset
  } = useCortiDictation();

  const [isFetching, setIsFetching] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  // Log when SDK becomes ready
  useEffect(() => {
    if (isReady) {
      logInfo('[VoiceRecorder] Corti SDK is ready');
    }
  }, [isReady]);

  useEffect(() => {
    if (error) {
      logError(`[VoiceRecorder] Transcription error: ${error}`);
    }
  }, [error]);

  // Pass interim transcript to parent in real-time
  useEffect(() => {
    if (isRecording && onInterimTranscript) {
      const fullText = transcript + (interimTranscript ? ' ' + interimTranscript : '');
      onInterimTranscript(fullText.trim());
    }
  }, [transcript, interimTranscript, isRecording, onInterimTranscript]);

  const handleToggle = async () => {
    if (isRecording) {
      // Stop recording
      logInfo('[VoiceRecorder] Stopping recording...');
      const finalTranscript = await stopRecording();

      if (finalTranscript) {
        logInfo(`[VoiceRecorder] Final transcript: ${finalTranscript.substring(0, 100)}...`);
        onTranscriptComplete(finalTranscript);
        reset();
      } else {
        logInfo('[VoiceRecorder] No transcript received');
      }
    } else {
      // Start recording - fetch token first
      try {
        setIsFetching(true);
        setTokenError(null);

        logInfo('[VoiceRecorder] Fetching Corti token...');
        const response = await fetch('/api/transcribe/token', {
          headers: getAuthHeaders()
        });

        if (!response.ok) {
          throw new Error(`Failed to get token: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.token || !data.tenant_name) {
          throw new Error('Invalid token response - missing token or tenant_name');
        }

        logInfo(`[VoiceRecorder] Token received, starting recording (env: ${data.environment})`);

        await startRecording({
          token: data.token,
          tenantName: data.tenant_name,
          environment: data.environment || 'eu',
          language: language
        });

      } catch (err: any) {
        logError(`[VoiceRecorder] Failed to start recording: ${err.message}`);
        setTokenError(err.message || 'Failed to start voice recording');
      } finally {
        setIsFetching(false);
      }
    }
  };

  return (
    <div className="relative">
      <button
        onClick={handleToggle}
        disabled={disabled || isFetching || !isReady}
        className={`p-2 rounded-full transition-all ${
          isRecording
            ? 'bg-red-500 hover:bg-red-600 animate-pulse'
            : 'bg-blue-500 hover:bg-blue-600'
        } text-white disabled:opacity-50 disabled:cursor-not-allowed`}
        title={!isReady ? 'Loading...' : (isRecording ? 'Stop recording' : 'Start voice input')}
        type="button"
      >
        {!isReady || isFetching ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : isRecording ? (
          <MicOff className="w-5 h-5" />
        ) : (
          <Mic className="w-5 h-5" />
        )}
      </button>

      {/* Interim transcript preview */}
      {(interimTranscript || transcript) && (
        <div className="absolute bottom-full mb-2 right-0 bg-gray-100 border border-gray-300 p-3 rounded-lg shadow-lg text-sm text-gray-700 max-w-xs z-50">
          <div className="font-semibold text-xs text-gray-500 mb-1">
            {isRecording ? 'Listening...' : 'Transcript'}
          </div>
          <div className="max-h-32 overflow-y-auto">
            {transcript && <span className="text-gray-900">{transcript} </span>}
            {interimTranscript && (
              <span className="text-gray-500 italic">{interimTranscript}</span>
            )}
          </div>
        </div>
      )}

      {/* Error display */}
      {(error || tokenError) && (
        <div className="absolute bottom-full mb-2 right-0 bg-red-50 border border-red-300 p-3 rounded-lg shadow-lg text-sm text-red-700 max-w-xs z-50">
          <div className="font-semibold text-xs mb-1">Error</div>
          <div>{error || tokenError}</div>
        </div>
      )}
    </div>
  );
}
