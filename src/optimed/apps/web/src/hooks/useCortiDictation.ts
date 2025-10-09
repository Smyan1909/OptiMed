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
    if (!sdkLoaded || typeof window === 'undefined') {
      return;
    }

    // Check if component already exists in DOM (from previous mount)
    let container = containerRef.current;
    let dictationEl = container?.querySelector('corti-dictation') ||
                      document.querySelector('#corti-dictation-element');

    if (!dictationEl) {
      // Create new component
      console.log('[Corti SDK] Initializing web component');
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

    // Wait a bit for custom element to be defined
    setTimeout(() => {
      if (dictationEl) {
        dictationRef.current = dictationEl;
        console.log('[Corti SDK] Component element found:', dictationEl);

        // Listen for ready event
        dictationEl.addEventListener('ready', () => {
          console.log('[Corti SDK] Component ready event fired');
          setState(prev => ({ ...prev, isReady: true }));
        });

        // Check if component is already ready (doesn't always fire 'ready' event)
        // Trigger our own ready check after a short delay
        setTimeout(() => {
          console.log('[Corti SDK] Checking if component is already ready...');
          // If we have the element and it has methods, it's ready
          if (dictationEl && typeof (dictationEl as any).setAccessToken === 'function') {
            console.log('[Corti SDK] Component is already ready');
            setState(prev => ({ ...prev, isReady: true }));
          }
        }, 200);

        // Listen for transcript events
        dictationEl.addEventListener('transcript', ((e: CustomEvent) => {
          console.log('[Corti SDK] Transcript received:', e.detail);
          console.log('[Corti SDK] Full event:', e);

          // Try different paths to get the text
          let text = '';
          let isFinal = true;

          if (e.detail) {
            text = e.detail.data?.text || e.detail.text || '';
            isFinal = e.detail.data?.isFinal ?? e.detail.isFinal ?? true;
          }

          console.log('[Corti SDK] Extracted - text:', text, 'isFinal:', isFinal);

          if (text) {
            if (isFinal) {
              console.log('[Corti SDK] Adding final transcript to state');
              setState(prev => {
                const newTranscript = prev.transcript + (prev.transcript ? ' ' : '') + text;
                console.log('[Corti SDK] New transcript state:', newTranscript);
                return {
                  ...prev,
                  transcript: newTranscript,
                  interimTranscript: '',
                };
              });
            } else {
              console.log('[Corti SDK] Setting interim transcript');
              setState(prev => ({
                ...prev,
                interimTranscript: text,
              }));
            }
          } else {
            console.warn('[Corti SDK] No text found in transcript event');
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

    // Cleanup - DON'T remove the component on unmount since it can be reused
    // Only clean up on full page unload
    return () => {
      // Keep the component in DOM for reuse across session changes
      console.log('[Corti SDK] Hook unmounting - keeping component for reuse');
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

      // Set configuration FIRST for fastest interim results
      dictationRef.current.dictationConfig = {
        primaryLanguage: config.language || 'en',
        interimResults: true,  // Enable interim results for real-time streaming
        automaticPunctuation: true,
        spokenPunctuation: false,
      };

      console.log('[Corti SDK] Configuration set:', dictationRef.current.dictationConfig);

      // Set access token AFTER configuration
      await dictationRef.current.setAccessToken(config.token);

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
