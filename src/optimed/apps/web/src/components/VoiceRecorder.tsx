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
  const interimTranscriptRef = useRef('');
  const wasRecordingRef = useRef(false);
  const justStoppedRef = useRef(false);
  const finalTranscriptTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Keep refs updated with latest transcripts
  useEffect(() => {
    transcriptRef.current = transcript;
  }, [transcript]);

  useEffect(() => {
    interimTranscriptRef.current = interimTranscript;
  }, [interimTranscript]);

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
    if (justStoppedRef.current && !isRecording) {
      // Capture the current values BEFORE any state changes
      const currentFinal = transcript;
      const currentInterim = interimTranscript;
      const hasContent = currentFinal || currentInterim;

      if (hasContent) {
        // Clear any pending timeout
        if (finalTranscriptTimeoutRef.current) {
          clearTimeout(finalTranscriptTimeoutRef.current);
          finalTranscriptTimeoutRef.current = null;
        }

        // Combine final + interim transcript
        const fullTranscript = (currentFinal + (currentInterim ? ' ' + currentInterim : '')).trim();

        logInfo(`[VoiceRecorder] Final transcript received: ${fullTranscript.substring(0, 100)}...`);

        // Store the combined result before reset
        transcriptRef.current = fullTranscript;

        setIsProcessing(false);  // Clear processing state

        if (fullTranscript) {
          onTranscriptComplete(fullTranscript);
        }

        reset();
        justStoppedRef.current = false;
        wasRecordingRef.current = false;
      }
    }
  }, [transcript, interimTranscript, isRecording, onTranscriptComplete, reset]);

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
      logInfo(`[VoiceRecorder] Stopping recording...`);

      wasRecordingRef.current = true;
      justStoppedRef.current = true;
      setIsProcessing(true);  // Start processing state
      await stopRecording();

      // Set a longer timeout that only clears processing state but doesn't reset
      // This allows late-arriving transcripts to still be captured
      finalTranscriptTimeoutRef.current = setTimeout(() => {
        if (justStoppedRef.current) {
          // Check one final time if we got any transcript
          const finalText = transcriptRef.current;
          const interimText = interimTranscriptRef.current;
          const fullTranscript = (finalText + (interimText ? ' ' + interimText : '')).trim();

          logInfo(`[VoiceRecorder] Timeout check - transcript: "${fullTranscript}"`);

          if (fullTranscript) {
            // We got something, deliver it
            setIsProcessing(false);
            onTranscriptComplete(fullTranscript);
            reset();
            justStoppedRef.current = false;
            wasRecordingRef.current = false;
          } else {
            // Still nothing after extended wait - just clear processing
            logInfo('[VoiceRecorder] No transcript after extended timeout, clearing processing state but keeping listener active');
            setIsProcessing(false);
            // DON'T reset or clear justStoppedRef - keep waiting for transcript
          }
        }
      }, 5000); // Extended to 5 seconds to give Corti plenty of time
    } else {
      // Start recording - fetch token first
      try {
        setIsFetching(true);
        setTokenError(null);

        // Clear any previous transcripts
        transcriptRef.current = '';
        interimTranscriptRef.current = '';

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
