import { useState, useCallback, useRef } from 'react';

interface VoiceTranscriptionState {
  isRecording: boolean;
  isTranscribing: boolean;
  transcript: string;
  interimTranscript: string;
  error: string | null;
}

interface CortiConfig {
  token: string;
  tenantName: string;
  environment?: 'eu' | 'us';
  language?: string;
}

export const useVoiceTranscription = () => {
  const [state, setState] = useState<VoiceTranscriptionState>({
    isRecording: false,
    isTranscribing: false,
    transcript: '',
    interimTranscript: '',
    error: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Float32Array[]>([]);

  const startRecording = useCallback(async (config: CortiConfig) => {
    try {
      setState(prev => ({ ...prev, error: null, transcript: '', interimTranscript: '' }));

      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1, // Mono audio
          sampleRate: 16000, // 16kHz
          echoCancellation: true,
          noiseSuppression: true,
        }
      });
      streamRef.current = stream;

      // Connect to Corti WebSocket
      const wsUrl = `wss://api.${config.environment || 'eu'}.corti.app/audio-bridge/v2/transcribe?tenant-name=${encodeURIComponent(config.tenantName)}&token=Bearer%20${encodeURIComponent(config.token)}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      let configAccepted = false;
      let audioStarted = false;

      ws.onopen = () => {
        console.log('[Corti] WebSocket connected, readyState:', ws.readyState);

        // Send configuration message with proper Corti format
        const configMessage = {
          type: 'config',  // REQUIRED: Corti expects type field
          configuration: {
            primaryLanguage: config.language || 'en',
            interimResults: true,
            automaticPunctuation: true,
            spokenPunctuation: false,
          }
        };

        console.log('[Corti] Sending configuration:', JSON.stringify(configMessage));
        ws.send(JSON.stringify(configMessage));

        setState(prev => ({ ...prev, isRecording: true, isTranscribing: true }));

        // Set a timeout to check if we receive CONFIG_ACCEPTED
        setTimeout(() => {
          if (!configAccepted) {
            console.warn('[Corti] No CONFIG_ACCEPTED received after 3 seconds');
          }
        }, 3000);
      };

      ws.onmessage = (event) => {
        try {
          console.log('[Corti] Raw message received:', event.data);
          const message = JSON.parse(event.data);
          console.log('[Corti] Parsed message type:', message.type, 'Full message:', message);

          if (message.type === 'CONFIG_ACCEPTED') {
            console.log('[Corti] Configuration accepted, starting audio capture');
            configAccepted = true;

            // Start capturing audio only after config is accepted
            if (!audioStarted) {
              audioStarted = true;
              startAudioCapture(stream, ws);
            }
          } else if (message.type === 'CONFIG_DENIED') {
            console.error('[Corti] Configuration denied:', message);
            setState(prev => ({
              ...prev,
              error: 'Configuration denied. Please check language settings.'
            }));
            ws.close();
          } else if (message.type === 'CONFIG_TIMEOUT') {
            console.error('[Corti] Configuration timeout');
            setState(prev => ({
              ...prev,
              error: 'Configuration timeout. Please try again.'
            }));
            ws.close();
          } else if (message.type === 'transcript') {
            if (message.isFinal) {
              // Final transcript - append to full transcript
              console.log('[Corti] Final transcript received, length:', message.text?.length || 0);
              setState(prev => ({
                ...prev,
                transcript: prev.transcript + (prev.transcript ? ' ' : '') + message.text,
                interimTranscript: '',
              }));
            } else {
              // Interim transcript - show as preview
              console.log('[Corti] Interim transcript, length:', message.text?.length || 0);
              setState(prev => ({
                ...prev,
                interimTranscript: message.text,
              }));
            }
          } else if (message.type === 'error') {
            console.error('[Corti] Error:', message);
            setState(prev => ({
              ...prev,
              error: message.message || 'Transcription error occurred'
            }));
          }
        } catch (error) {
          console.error('[Corti] Failed to parse message:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('[Corti] WebSocket error:', error);
        setState(prev => ({
          ...prev,
          error: 'Connection error. Please try again.'
        }));
      };

      ws.onclose = (event) => {
        console.log('[Corti] WebSocket closed:', {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
          configAccepted: configAccepted,
          audioStarted: audioStarted
        });

        if (!configAccepted) {
          setState(prev => ({
            ...prev,
            error: 'Connection closed before configuration was accepted. Please check credentials.'
          }));
        }
      };

    } catch (error: any) {
      console.error('[Corti] Failed to start recording:', error);
      setState(prev => ({
        ...prev,
        error: error.message || 'Failed to access microphone'
      }));
    }
  }, []);

  const createWavHeader = (dataLength: number, sampleRate: number, numChannels: number, bitsPerSample: number): ArrayBuffer => {
    const buffer = new ArrayBuffer(44);
    const view = new DataView(buffer);

    // "RIFF" chunk descriptor
    view.setUint32(0, 0x52494646, false); // "RIFF"
    view.setUint32(4, 36 + dataLength, true); // File size - 8
    view.setUint32(8, 0x57415645, false); // "WAVE"

    // "fmt " sub-chunk
    view.setUint32(12, 0x666d7420, false); // "fmt "
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, 1, true); // AudioFormat (1 = PCM)
    view.setUint16(22, numChannels, true); // NumChannels
    view.setUint32(24, sampleRate, true); // SampleRate
    view.setUint32(28, sampleRate * numChannels * bitsPerSample / 8, true); // ByteRate
    view.setUint16(32, numChannels * bitsPerSample / 8, true); // BlockAlign
    view.setUint16(34, bitsPerSample, true); // BitsPerSample

    // "data" sub-chunk
    view.setUint32(36, 0x64617461, false); // "data"
    view.setUint32(40, dataLength, true); // Subchunk2Size

    return buffer;
  };

  const startAudioCapture = (stream: MediaStream, ws: WebSocket) => {
    console.log('[Corti] Starting audio capture with WAV format');
    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    source.connect(processor);
    processor.connect(audioContext.destination);

    let chunkCount = 0;
    let lastLogTime = Date.now();
    let headerSent = false;

    processor.onaudioprocess = (event) => {
      if (ws.readyState === WebSocket.OPEN) {
        const audioData = event.inputBuffer.getChannelData(0);

        // Convert Float32Array to Int16Array (PCM)
        const int16Array = new Int16Array(audioData.length);
        for (let i = 0; i < audioData.length; i++) {
          const s = Math.max(-1, Math.min(1, audioData[i]));
          int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        // Send WAV header on first chunk
        if (!headerSent) {
          const header = createWavHeader(
            int16Array.byteLength * 1000, // Estimate total data length
            16000, // Sample rate
            1, // Mono
            16 // 16-bit
          );
          ws.send(header);
          console.log('[Corti] Sent WAV header (44 bytes)');
          headerSent = true;
        }

        // Send PCM audio data
        // ws.send(int16Array.buffer);
        chunkCount++;

        // Log every second
        const now = Date.now();
        if (now - lastLogTime > 1000) {
          console.log(`[Corti] Sent ${chunkCount} audio chunks, buffer size: ${int16Array.buffer.byteLength} bytes`);
          lastLogTime = now;
        }
      } else {
        console.warn('[Corti] WebSocket not open, readyState:', ws.readyState);
      }
    };

    // Store for cleanup
    (processor as any)._audioContext = audioContext;
    console.log('[Corti] Audio capture initialized, AudioContext state:', audioContext.state);
  };

  const stopRecording = useCallback(async () => {
    try {
      // Send end message to Corti
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'end' }));
        wsRef.current.close();
      }

      // Stop media stream
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }

      // Stop media recorder
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }

      setState(prev => ({
        ...prev,
        isRecording: false,
        isTranscribing: false
      }));

      return state.transcript.trim();
    } catch (error) {
      console.error('[Corti] Failed to stop recording:', error);
      return state.transcript.trim();
    }
  }, [state.transcript]);

  const reset = useCallback(() => {
    setState({
      isRecording: false,
      isTranscribing: false,
      transcript: '',
      interimTranscript: '',
      error: null,
    });
  }, []);

  return {
    isRecording: state.isRecording,
    isTranscribing: state.isTranscribing,
    transcript: state.transcript,
    interimTranscript: state.interimTranscript,
    error: state.error,
    startRecording,
    stopRecording,
    reset,
  };
};
