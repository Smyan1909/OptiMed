import { useState, useCallback, useRef, useEffect } from 'react';

interface DifferentialDiagnosis {
  icd_code: string;
  diagnosis_name: string;
  confidence: number;
  reasoning: string;
  supporting_evidence: string[];
}

interface GeneratedImage {
  image_id: string;
  prompt: string;
  created_at?: string;
  metadata?: any;
}

interface StreamingUpdate {
  type: 'status' | 'reasoning' | 'reasoning_complete' | 'response_chunk' | 'completion' | 'error';
  step?: string;
  description?: string;
  message?: string;
  reasoning?: string;
  content?: string;
  error?: string;
  timestamp?: string;
  estimated_time?: string;
  is_long_running?: boolean;
  accumulated_content?: string;
  generated_image?: GeneratedImage;
  differential_diagnoses?: DifferentialDiagnosis[];
  reasoning_steps?: string[];
}

interface StreamingState {
  isStreaming: boolean;
  currentStep: string;
  currentDescription: string;
  reasoning: string[];
  finalResponse: string;
  streamingResponse: string;
  error: string | null;
  progress: number;
  updates: StreamingUpdate[];
  currentReasoning: string;
  generatedImage: GeneratedImage | null;
}

export const useStreamingChat = () => {
  const [state, setState] = useState<StreamingState>({
    isStreaming: false,
    currentStep: '',
    currentDescription: '',
    reasoning: [],
    finalResponse: '',
    streamingResponse: '',
    error: null,
    progress: 0,
    updates: [],
    currentReasoning: '',
    generatedImage: null
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const stepCountRef = useRef(0);
  const reasoningTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [streamDifferentialDiagnoses, setStreamDifferentialDiagnoses] = useState<DifferentialDiagnosis[]>([]);

  // Handle streaming updates
  const handleStreamUpdate = useCallback((update: StreamingUpdate) => {
    console.log('🔄 Processing update:', update.type, update);
    
    setState(prev => {
      const newUpdates = [...prev.updates, update];
      
      switch (update.type) {
        case 'status':
          stepCountRef.current += 1;
          return {
            ...prev,
            currentStep: update.step || 'Processing...',
            currentDescription: update.description || '',
            progress: Math.min((stepCountRef.current / 12) * 100, 95),
            updates: newUpdates,
            currentReasoning: update.step?.toLowerCase().includes('reason') ? prev.currentReasoning : ''
          };

        case 'reasoning':
          const newReasoning = [...prev.reasoning, update.reasoning || ''];
          console.log('🧠 Adding reasoning step:', update.reasoning, 'Total steps:', newReasoning.length);
          
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }
          
          const newState = {
            ...prev,
            reasoning: newReasoning,
            currentReasoning: update.reasoning || '',
            currentStep: 'AI Reasoning',
            currentDescription: 'Analyzing and thinking through the problem...',
            updates: newUpdates
          };
          
          reasoningTimeoutRef.current = setTimeout(() => {
            setState(currentState => ({
              ...currentState,
              currentReasoning: ''
            }));
          }, 3000);
          
          return newState;

        case 'reasoning_complete':
          console.log('🧠 Reasoning complete, total steps:', prev.reasoning.length);
          
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }
          
          return {
            ...prev,
            currentStep: 'Analysis Complete',
            currentDescription: 'Generating final response...',
            currentReasoning: '',
            progress: 90,
            updates: newUpdates
          };

        case 'response_chunk':
          console.log('📝 Streaming response chunk received:', {
            content: update.content,
            accumulated: update.accumulated_content,
            currentLength: prev.streamingResponse.length,
            contentLength: update.content?.length || 0,
            accumulatedLength: update.accumulated_content?.length || 0
          });
          
          // CRITICAL: Make sure we actually update the streamingResponse
          const newStreamingResponse = update.accumulated_content || prev.streamingResponse + (update.content || '');
          
          return {
            ...prev,
            streamingResponse: newStreamingResponse,
            currentStep: 'Generating Response',
            currentDescription: 'Streaming response...',
            progress: 85,
            updates: newUpdates
          };

        case 'completion':
          console.log('✅ Completion received with content:', update.content);
          console.log('🖼️ Generated image:', update.generated_image);
          console.log('🩺 Differential diagnoses received:', update.differential_diagnoses);
          console.log('🧠 Reasoning steps received:', update.reasoning_steps);
          
          // Handle differential diagnoses - set them immediately
          if (update.differential_diagnoses && Array.isArray(update.differential_diagnoses) && update.differential_diagnoses.length > 0) {
            console.log('🩺 Setting differential diagnoses state:', update.differential_diagnoses);
            setStreamDifferentialDiagnoses(update.differential_diagnoses);
          } else {
            console.log('🩺 No differential diagnoses in completion or empty array');
            setStreamDifferentialDiagnoses([]);
          }
          
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }

          // CRITICAL FIX: Prioritize reasoning from completion, but preserve streaming reasoning if completion has none
          let finalReasoning = prev.reasoning;
          if (update.reasoning_steps && Array.isArray(update.reasoning_steps) && update.reasoning_steps.length > 0) {
            console.log('🧠 Using reasoning from completion:', update.reasoning_steps);
            finalReasoning = update.reasoning_steps;
          } else if (prev.reasoning.length > 0) {
            console.log('🧠 Using reasoning from streaming:', prev.reasoning);
            finalReasoning = prev.reasoning;
          } else {
            console.log('🧠 No reasoning available from either source');
            finalReasoning = prev.reasoning;
          }
          
          return {
            ...prev,
            isStreaming: false,
            finalResponse: update.content || prev.streamingResponse || '', // Use streamed content if available
            generatedImage: update.generated_image || null,
            reasoning: finalReasoning,
            progress: 100,
            currentStep: 'Complete',
            currentDescription: 'Analysis finished',
            currentReasoning: '',
            streamingResponse: '', // Clear streaming response
            updates: newUpdates
          };

        case 'error':
          console.error('❌ Stream error:', update.error);
          
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }
          
          return {
            ...prev,
            isStreaming: false,
            error: update.error || 'An error occurred',
            progress: 0,
            currentStep: 'Error',
            currentDescription: 'Stream failed',
            currentReasoning: '',
            streamingResponse: '', // Clear streaming response
            updates: newUpdates
          };

        default:
          console.log('🔄 Unknown update type:', update.type);
          return { ...prev, updates: newUpdates };
      }
    });
  }, []);

  const startStream = useCallback(async (
    endpoint: string,
    payload: any,
    sessionId?: string
  ) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    if (reasoningTimeoutRef.current) {
      clearTimeout(reasoningTimeoutRef.current);
    }

    // Reset all state
    setState({
      isStreaming: true,
      currentStep: 'Initializing...',
      currentDescription: 'Starting analysis',
      reasoning: [],
      finalResponse: '',
      streamingResponse: '',
      error: null,
      progress: 0,
      updates: [],
      currentReasoning: '',
      generatedImage: null
    });

    // Reset differential diagnoses
    setStreamDifferentialDiagnoses([]);
    stepCountRef.current = 0;

    try {
      console.log('🚀 Starting stream with payload:', payload);
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionId && { 'X-Session-ID': sessionId })
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      
      if (!reader) {
        throw new Error('No response body');
      }

      let buffer = '';

      const processStream = async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              console.log('📡 Stream ended');
              break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            
            buffer = lines.pop() || '';

            for (const line of lines) {
              console.log('🔍 Processing SSE line:', line.slice(0, 100) + '...');
              if (line.startsWith('data: ')) {
                const data = line.slice(6).trim();
                if (data && data !== '[DONE]') {
                  try {
                    const update = JSON.parse(data);
                    handleStreamUpdate(update);
                  } catch (e) {
                    console.error('❌ Failed to parse SSE data:', e, 'Raw data:', data.slice(0, 200));
                  }
                }
              } else if (line.trim()) {
                console.log('⚠️ Non-data SSE line:', line);
              }
            }
          }
        } catch (error) {
          console.error('Stream processing error:', error);
          setState(prev => ({
            ...prev,
            isStreaming: false,
            error: 'Stream processing failed',
          }));
        }
      };

      await processStream();

    } catch (error) {
      console.error('Streaming error:', error);
      setState(prev => ({
        ...prev,
        isStreaming: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      }));
    }
  }, [handleStreamUpdate]);

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    
    if (reasoningTimeoutRef.current) {
      clearTimeout(reasoningTimeoutRef.current);
    }
    
    setState(prev => ({
      ...prev,
      isStreaming: false,
    }));
  }, []);

  // Cleanup effect
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reasoningTimeoutRef.current) {
        clearTimeout(reasoningTimeoutRef.current);
      }
    };
  }, []);

  return {
    // State properties
    isStreaming: state.isStreaming,
    currentStep: state.currentStep,
    currentDescription: state.currentDescription,
    reasoning: state.reasoning,
    finalResponse: state.finalResponse,
    streamingResponse: state.streamingResponse, // This is now properly returned
    error: state.error,
    progress: state.progress,
    updates: state.updates,
    currentReasoning: state.currentReasoning,
    generatedImage: state.generatedImage,
    
    // Additional state
    streamDifferentialDiagnoses,
    
    // Functions
    startStream,
    stopStream,
  };
};