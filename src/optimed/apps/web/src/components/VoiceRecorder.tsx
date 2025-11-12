"use client";

import { useState, useEffect, useRef } from 'react';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import { useCortiDictation } from '@/hooks/useCortiDictation';
import { logInfo, logError } from '@/lib/logger';

interface VoiceRecorderProps {
  onTranscriptComplete: (text: string) => void;
  onInterimTranscript?: (text: string) => void;  // Real-time interim results
  onRecordingStateChange?: (isRecording: boolean) => void;  // Notify parent of recording state
  onProcessingStateChange?: (isProcessing: boolean) => void;  // Notify parent of processing state
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

export function VoiceRecorder({ onTranscriptComplete, onInterimTranscript, onRecordingStateChange, onProcessingStateChange, disabled = false, language = 'en' }: VoiceRecorderProps) {
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
  const [isProcessing, setIsProcessing] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const transcriptRef = useRef('');
  const wasRecordingRef = useRef(false);
  const justStoppedRef = useRef(false);
  const finalTranscriptTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Keep ref updated with latest transcript
  useEffect(() => {
    transcriptRef.current = transcript;
  }, [transcript]);

  // Notify parent when recording state changes
  useEffect(() => {
    onRecordingStateChange?.(isRecording);
  }, [isRecording, onRecordingStateChange]);

  // Notify parent when processing state changes
  useEffect(() => {
    onProcessingStateChange?.(isProcessing);
  }, [isProcessing, onProcessingStateChange]);

  // When transcript updates after stopping, immediately call onTranscriptComplete
  useEffect(() => {
    if (justStoppedRef.current && transcript && !isRecording) {
      // Clear any pending timeout
      if (finalTranscriptTimeoutRef.current) {
        clearTimeout(finalTranscriptTimeoutRef.current);
        finalTranscriptTimeoutRef.current = null;
      }

      logInfo(`[VoiceRecorder] Final transcript received: ${transcript.substring(0, 100)}...`);
      setIsProcessing(false);  // Clear processing state
      onTranscriptComplete(transcript.trim());
      reset();
      justStoppedRef.current = false;
      wasRecordingRef.current = false;
    }
  }, [transcript, isRecording, onTranscriptComplete, reset]);

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

  // Pass interim transcript to parent in real-time - including after stopping
  useEffect(() => {
    if ((isRecording || wasRecordingRef.current) && onInterimTranscript) {
      const fullText = transcript + (interimTranscript ? ' ' + interimTranscript : '');
      if (fullText.trim()) {
        onInterimTranscript(fullText.trim());
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcript, interimTranscript, isRecording]);

  const handleToggle = async () => {
    if (isRecording) {
      // Stop recording
      logInfo('[VoiceRecorder] Stopping recording...');
      wasRecordingRef.current = true;
      justStoppedRef.current = true;
      setIsProcessing(true);  // Start processing state
      await stopRecording();

      // Fallback timeout in case no transcript arrives (shouldn't normally happen)
      finalTranscriptTimeoutRef.current = setTimeout(() => {
        if (justStoppedRef.current) {
          const fullTranscript = transcriptRef.current.trim();
          logInfo(`[VoiceRecorder] Fallback timeout - transcript: "${fullTranscript}"`);

          setIsProcessing(false);  // Clear processing state
          if (fullTranscript) {
            onTranscriptComplete(fullTranscript);
          } else {
            logInfo('[VoiceRecorder] No transcript received after timeout');
          }
          reset();
          justStoppedRef.current = false;
          wasRecordingRef.current = false;
        }
      }, 500); // Fallback timeout - should be triggered by event before this
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
        disabled={disabled || isFetching || !isReady || isProcessing}
        className={`p-2 rounded-full transition-all ${
          isRecording
            ? 'bg-red-500 hover:bg-red-600 animate-pulse'
            : isProcessing
            ? 'bg-yellow-500'
            : 'bg-blue-500 hover:bg-blue-600'
        } text-white disabled:opacity-50 disabled:cursor-not-allowed`}
        title={!isReady ? 'Loading...' : isProcessing ? 'Processing...' : (isRecording ? 'Stop recording' : 'Start voice input')}
        type="button"
      >
        {!isReady || isFetching ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : isProcessing ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : isRecording ? (
          <MicOff className="w-5 h-5" />
        ) : (
          <Mic className="w-5 h-5" />
        )}
      </button>

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
