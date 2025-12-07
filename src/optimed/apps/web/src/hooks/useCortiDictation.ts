import { useState, useEffect, useRef, useCallback } from 'react';

// Set up console filtering at module level to suppress SDK internal warnings
// The SDK's ReconnectingWebSocket generates "Close received after close" errors
// which are harmless but noisy. This filter suppresses them.
if (typeof window !== 'undefined') {
  const originalWarn = console.warn;
  const originalError = console.error;
  
  if (!(console.warn as any).__cortiFiltered) {
    const filteredWarn = (...args: any[]) => {
      const msg = args.map(a => String(a)).join(' ').toLowerCase();
      if (msg.includes('unhandled message type') && 
          (msg.includes('usage') || msg.includes('ended'))) {
        return;
      }
      originalWarn.apply(console, args);
    };
    (filteredWarn as any).__cortiFiltered = true;
    console.warn = filteredWarn;

    const filteredError = (...args: any[]) => {
      const msg = args.map(a => String(a)).join(' ').toLowerCase();
      if (msg.includes('close received after close')) {
        return;
      }
      originalError.apply(console, args);
    };
    (filteredError as any).__cortiFiltered = true;
    console.error = filteredError;
  }
}

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
    if (!sdkLoaded || typeof window === 'undefined') {
      return;
    }

    // Check if component already exists in DOM
    let container = containerRef.current;
    let dictationEl = container?.querySelector('corti-dictation') ||
                      document.querySelector('#corti-dictation-element');

    if (!dictationEl) {
      console.log('[Corti SDK] Creating web component');
      container = document.createElement('div');
      container.style.display = 'none';
      container.innerHTML = '<corti-dictation id="corti-dictation-element"></corti-dictation>';
      document.body.appendChild(container);
      containerRef.current = container;
      dictationEl = container.querySelector('corti-dictation');
    } else {
      console.log('[Corti SDK] Reusing existing web component');
      if (!containerRef.current) {
        containerRef.current = dictationEl.parentElement as HTMLDivElement;
      }
    }

    // Wait for custom element to be defined
    setTimeout(() => {
      if (dictationEl) {
        dictationRef.current = dictationEl;
        console.log('[Corti SDK] Component element found');

        // Listen for ready event
        dictationEl.addEventListener('ready', () => {
          console.log('[Corti SDK] Component ready');
          setState(prev => ({ ...prev, isReady: true }));
        });

        // Check if already ready
        setTimeout(() => {
          if (dictationEl && typeof (dictationEl as any).setAccessToken === 'function') {
            console.log('[Corti SDK] Component already ready');
            setState(prev => ({ ...prev, isReady: true }));
          }
        }, 200);

        // Listen for transcript events
        dictationEl.addEventListener('transcript', ((e: CustomEvent) => {
          let text = '';
          let isFinal = true;

          if (e.detail) {
            text = e.detail.data?.text || e.detail.text || '';
            isFinal = e.detail.data?.isFinal ?? e.detail.isFinal ?? true;
          }

          if (text) {
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
          }
        }) as EventListener);

        // Listen for recording state changes
        dictationEl.addEventListener('recording-state-changed', ((e: CustomEvent) => {
          console.log('[Corti SDK] Recording state:', e.detail.state);
          setState(prev => ({
            ...prev,
            isRecording: e.detail.state === 'recording'
          }));
        }) as EventListener);

        // Listen for errors
        dictationEl.addEventListener('error', ((e: CustomEvent) => {
          console.error('[Corti SDK] Error:', e.detail);
          setState(prev => ({
            ...prev,
            error: e.detail?.message || 'Transcription error'
          }));
        }) as EventListener);
      }
    }, 100);

    return () => {
      console.log('[Corti SDK] Hook unmounting');
    };
  }, [sdkLoaded]);

  const startRecording = useCallback(async (config: CortiConfig) => {
    if (!dictationRef.current) {
      setState(prev => ({ ...prev, error: 'Dictation component not initialized' }));
      return;
    }

    try {
      console.log('[Corti SDK] Starting recording');

      // Clear previous transcript
      setState(prev => ({
        ...prev,
        transcript: '',
        interimTranscript: '',
        error: null
      }));

      // Set configuration
      dictationRef.current.dictationConfig = {
        primaryLanguage: config.language || 'en',
        interimResults: true,
        automaticPunctuation: true,
        spokenPunctuation: false,
      };

      // Set access token
      await dictationRef.current.setAccessToken(config.token);

      // Start recording
      await dictationRef.current.toggleRecording();

      console.log('[Corti SDK] Recording started');

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

      // Stop recording if currently recording
      if (state.isRecording) {
        await dictationRef.current.toggleRecording();
      }

      setState(prev => ({
        ...prev,
        isRecording: false
      }));

      console.log('[Corti SDK] Recording stopped');

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
    connectionState: state.isRecording ? 'connected' : 'idle',
    startRecording,
    stopRecording,
    reset,
  };
};
