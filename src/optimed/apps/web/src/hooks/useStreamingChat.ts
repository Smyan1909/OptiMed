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
  type: 'status' | 'reasoning' | 'reasoning_complete' | 'completion' | 'error';
  step?: string;
  description?: string;
  message?: string;
  reasoning?: string;
  content?: string;
  error?: string;
  timestamp?: string;
  estimated_time?: string;
  is_long_running?: boolean;
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
              if (line.startsWith('data: ')) {
                const data = line.slice(6).trim();
                if (data && data !== '[DONE]') {
                  try {
                    const update = JSON.parse(data);
                    console.log('📥 Received update:', update);
                    handleStreamUpdate(update);
                  } catch (e) {
                    console.error('Failed to parse SSE data:', e, 'Data:', data);
                  }
                }
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
  }, []);

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
            finalResponse: update.content || '',
            generatedImage: update.generated_image || null,
            reasoning: finalReasoning,
            progress: 100,
            currentStep: 'Complete',
            currentDescription: 'Analysis finished',
            currentReasoning: '',
            updates: newUpdates
          };

        case 'error':
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }
          
          return {
            ...prev,
            isStreaming: false,
            error: update.error || 'Unknown error',
            progress: 0,
            currentReasoning: '',
            updates: newUpdates
          };

        default:
          console.log('🔄 Unknown update type:', update.type);
          return { ...prev, updates: newUpdates };
      }
    });
  }, []);

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

  // Debug effect to monitor differential diagnoses changes
  useEffect(() => {
    console.log('🩺 streamDifferentialDiagnoses state changed:', streamDifferentialDiagnoses);
  }, [streamDifferentialDiagnoses]);

  // Debug effect to monitor reasoning changes
  useEffect(() => {
    console.log('🧠 reasoning state changed:', state.reasoning);
  }, [state.reasoning]);

  return {
    // State properties
    isStreaming: state.isStreaming,
    currentStep: state.currentStep,
    currentDescription: state.currentDescription,
    reasoning: state.reasoning,
    finalResponse: state.finalResponse,
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