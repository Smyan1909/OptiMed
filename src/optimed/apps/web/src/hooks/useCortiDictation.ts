import { useState, useEffect, useRef, useCallback } from 'react';

interface CortiDictationState {
  isRecording: boolean;
  transcript: string;
  interimTranscript: string;
  error: string | null;
  isReady: boolean;
}

interface CortiConfig {
  token: string;
  tenantName: string;
  environment?: 'eu' | 'us';
  language?: string;
}

export const useCortiDictation = () => {
  const [state, setState] = useState<CortiDictationState>({
    isRecording: false,
    transcript: '',
    interimTranscript: '',
    error: null,
    isReady: false,
  });

  const dictationRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [sdkLoaded, setSdkLoaded] = useState(false);

  // Load SDK
  useEffect(() => {
    if (typeof window !== 'undefined' && !sdkLoaded) {
      import('@corti/dictation-web').then(() => {
        console.log('[Corti SDK] Module loaded');
        setSdkLoaded(true);
      }).catch(err => {
        console.error('[Corti SDK] Failed to load module:', err);
        setState(prev => ({ ...prev, error: 'Failed to load dictation SDK' }));
      });
    }
  }, [sdkLoaded]);

  // Initialize Corti web component after SDK is loaded
  useEffect(() => {
    if (!sdkLoaded || typeof window === 'undefined' || containerRef.current) {
      return;
    }

    console.log('[Corti SDK] Initializing web component');
    const container = document.createElement('div');
    container.style.display = 'none';
    container.innerHTML = '<corti-dictation id="corti-dictation-element"></corti-dictation>';
    document.body.appendChild(container);
    containerRef.current = container;

    // Wait a bit for custom element to be defined
    setTimeout(() => {
      const dictationEl = container.querySelector('corti-dictation');
      if (dictationEl) {
        dictationRef.current = dictationEl;
        console.log('[Corti SDK] Component element found:', dictationEl);

        // Listen for ready event
        dictationEl.addEventListener('ready', () => {
          console.log('[Corti SDK] Component ready');
          setState(prev => ({ ...prev, isReady: true }));
        });

        // Listen for transcript events
        dictationEl.addEventListener('transcript', ((e: CustomEvent) => {
          console.log('[Corti SDK] Transcript received:', e.detail);
          const text = e.detail.data?.text || e.detail.text || '';
          const isFinal = e.detail.data?.isFinal ?? e.detail.isFinal ?? true;

          if (isFinal) {
            setState(prev => ({
              ...prev,
              transcript: prev.transcript + (prev.transcript ? ' ' : '') + text,
              interimTranscript: '',
            }));
          } else {
            setState(prev => ({
              ...prev,
              interimTranscript: text,
            }));
          }
        }) as EventListener);

        // Listen for recording state changes
        dictationEl.addEventListener('recording-state-changed', ((e: CustomEvent) => {
          console.log('[Corti SDK] Recording state changed:', e.detail.state);
          const recordingState = e.detail.state;
          setState(prev => ({
            ...prev,
            isRecording: recordingState === 'recording'
          }));
        }) as EventListener);

        // Listen for errors
        dictationEl.addEventListener('error', ((e: CustomEvent) => {
          console.error('[Corti SDK] Error:', e.detail);
          setState(prev => ({
            ...prev,
            error: e.detail?.message || 'Transcription error occurred'
          }));
        }) as EventListener);
      } else {
        console.error('[Corti SDK] Component element not found');
      }
    }, 100);

    // Cleanup
    return () => {
      if (containerRef.current && document.body.contains(containerRef.current)) {
        document.body.removeChild(containerRef.current);
        containerRef.current = null;
      }
    };
  }, [sdkLoaded]);

  const startRecording = useCallback(async (config: CortiConfig) => {
    if (!dictationRef.current) {
      setState(prev => ({ ...prev, error: 'Dictation component not initialized' }));
      return;
    }

    try {
      console.log('[Corti SDK] Setting access token and starting recording');

      // Clear previous transcript
      setState(prev => ({
        ...prev,
        transcript: '',
        interimTranscript: '',
        error: null
      }));

      // Set access token
      await dictationRef.current.setAccessToken(config.token);

      // Set language if provided
      if (config.language) {
        dictationRef.current.dictationConfig = {
          ...dictationRef.current.dictationConfig,
          primaryLanguage: config.language,
          interimResults: true,
          automaticPunctuation: true,
        };
      }

      // Start recording
      await dictationRef.current.toggleRecording();

    } catch (error: any) {
      console.error('[Corti SDK] Failed to start recording:', error);
      setState(prev => ({
        ...prev,
        error: error.message || 'Failed to start recording'
      }));
    }
  }, []);

  const stopRecording = useCallback(async () => {
    if (!dictationRef.current) {
      return state.transcript.trim();
    }

    try {
      console.log('[Corti SDK] Stopping recording');

      // Stop recording
      if (state.isRecording) {
        await dictationRef.current.toggleRecording();
      }

      setState(prev => ({
        ...prev,
        isRecording: false
      }));

      return state.transcript.trim();
    } catch (error) {
      console.error('[Corti SDK] Failed to stop recording:', error);
      return state.transcript.trim();
    }
  }, [state.isRecording, state.transcript]);

  const reset = useCallback(() => {
    setState({
      isRecording: false,
      transcript: '',
      interimTranscript: '',
      error: null,
      isReady: state.isReady,
    });
  }, [state.isReady]);

  return {
    isRecording: state.isRecording,
    isReady: state.isReady,
    transcript: state.transcript,
    interimTranscript: state.interimTranscript,
    error: state.error,
    startRecording,
    stopRecording,
    reset,
  };
};
