import { useState, useCallback, useRef, useEffect } from 'react';
import { useStreamDecryption } from './useEncryption';
import { sanitizeUserId, sanitizePatientId, sanitizeSessionId, sanitizeDocumentId, logInfo, logError, logWarning } from '@/lib/logger';

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
  type: 'status' | 'reasoning' | 'reasoning_complete' | 'response_chunk' | 'completion' | 'error' | 'differential_diagnosis_progress' | 'note_generation_progress';
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
  // New fields for differential diagnosis progress
  diagnosis_name?: string;
  details?: string;
  // New fields for note generation progress
  template_type?: string;
  template_name?: string;
  note_generation_step?: string;
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
  // New fields for differential diagnosis progress
  differentialDiagnosisProgress: {
    isComputing: boolean;
    currentDiagnosis: string;
    currentStep: string;
    details: string;
  };
  // New fields for note generation progress
  noteGenerationProgress: {
    isGenerating: boolean;
    templateType: string;
    templateName: string;
    currentStep: string;
  };
}

export const useStreamingChat = (sessionId?: string) => {
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
    generatedImage: null,
    differentialDiagnosisProgress: {
      isComputing: false,
      currentDiagnosis: '',
      currentStep: '',
      details: ''
    },
    noteGenerationProgress: {
      isGenerating: false,
      templateType: '',
      templateName: '',
      currentStep: ''
    }
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const stepCountRef = useRef(0);
  const reasoningTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [streamDifferentialDiagnoses, setStreamDifferentialDiagnoses] = useState<DifferentialDiagnosis[]>([]);

  // Get decryption function for session
  const { decryptStreamChunk } = useStreamDecryption(sessionId || null);

  // Handle streaming updates
  const handleStreamUpdate = useCallback((update: StreamingUpdate) => {
    logInfo(`Processing update: ${update.type}`);
    
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
          logInfo(`Adding reasoning step, total steps: ${newReasoning.length}`);
          
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
          logInfo(`Reasoning complete, total steps: ${prev.reasoning.length}`);
          
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
          logInfo(`Streaming response chunk received - current: ${prev.streamingResponse.length}, content: ${update.content?.length || 0}, accumulated: ${update.accumulated_content?.length || 0}`);
          
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
          logInfo(`Completion received with content length: ${update.content?.length || 0}`);
          logInfo(`Generated image present: ${!!update.generated_image}`);
          logInfo(`Differential diagnoses count: ${update.differential_diagnoses?.length || 0}`);
          logInfo(`Reasoning steps count: ${update.reasoning_steps?.length || 0}`);
          
          // Handle differential diagnoses - set them immediately
          if (update.differential_diagnoses && Array.isArray(update.differential_diagnoses) && update.differential_diagnoses.length > 0) {
            logInfo(`Setting differential diagnoses state with ${update.differential_diagnoses.length} items`);
            setStreamDifferentialDiagnoses(update.differential_diagnoses);
          } else {
            logInfo('No differential diagnoses in completion or empty array');
            setStreamDifferentialDiagnoses([]);
          }
          
          if (reasoningTimeoutRef.current) {
            clearTimeout(reasoningTimeoutRef.current);
          }

          // CRITICAL FIX: Prioritize reasoning from completion, but preserve streaming reasoning if completion has none
          let finalReasoning = prev.reasoning;
          if (update.reasoning_steps && Array.isArray(update.reasoning_steps) && update.reasoning_steps.length > 0) {
            logInfo(`Using reasoning from completion: ${update.reasoning_steps.length} steps`);
            finalReasoning = update.reasoning_steps;
          } else if (prev.reasoning.length > 0) {
            logInfo(`Using reasoning from streaming: ${prev.reasoning.length} steps`);
            finalReasoning = prev.reasoning;
          } else {
            logInfo('No reasoning available from either source');
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
            differentialDiagnosisProgress: {
              isComputing: false,
              currentDiagnosis: '',
              currentStep: '',
              details: ''
            },
            noteGenerationProgress: {
              isGenerating: false,
              templateType: '',
              templateName: '',
              currentStep: ''
            },
            updates: newUpdates
          };

        case 'differential_diagnosis_progress':
          logInfo(`Differential diagnosis progress - diagnosis: ${update.diagnosis_name}, step: ${update.step}`);

          // Check if this is a completion update
          const isCompleting = update.step?.toLowerCase().includes('complete') ||
                              update.step?.toLowerCase().includes('finished') ||
                              update.diagnosis_name?.toLowerCase().includes('complete');

          logInfo(`Differential diagnosis is completing: ${isCompleting}`);

          return {
            ...prev,
            differentialDiagnosisProgress: {
              isComputing: !isCompleting,
              currentDiagnosis: update.diagnosis_name || '',
              currentStep: update.step || '',
              details: update.details || ''
            },
            currentStep: isCompleting ? 'Differential Diagnoses Complete' : 'Computing Differential Diagnoses',
            currentDescription: `${isCompleting ? 'Completed: ' : 'Analyzing '}${update.diagnosis_name}: ${update.step}${update.details ? ' - ' + update.details : ''}`,
            updates: newUpdates
          };

        case 'note_generation_progress':
          logInfo(`Note generation progress - template: ${update.template_name}, type: ${update.template_type}, step: ${update.note_generation_step}`);

          // Check if note generation is complete
          const isNoteComplete = update.note_generation_step?.toLowerCase().includes('complete') ||
                                 update.note_generation_step?.toLowerCase().includes('finished');

          logInfo(`Note generation is complete: ${isNoteComplete}`);

          return {
            ...prev,
            noteGenerationProgress: {
              isGenerating: !isNoteComplete,
              templateType: update.template_type || prev.noteGenerationProgress.templateType,
              templateName: update.template_name || prev.noteGenerationProgress.templateName,
              currentStep: update.note_generation_step || update.step || ''
            },
            currentStep: isNoteComplete ? 'Note Generation Complete' : 'Generating Clinical Note',
            currentDescription: update.description || `Generating ${update.template_type || 'clinical'} note...`,
            updates: newUpdates
          };

        case 'error':
          logError(`Stream error: ${update.error || 'Unknown error'}`);
          
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
          logInfo(`Unknown update type: ${update.type}`);
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
      generatedImage: null,
      differentialDiagnosisProgress: {
        isComputing: false,
        currentDiagnosis: '',
        currentStep: '',
        details: ''
      },
      noteGenerationProgress: {
        isGenerating: false,
        templateType: '',
        templateName: '',
        currentStep: ''
      }
    });

    // Reset differential diagnoses
    setStreamDifferentialDiagnoses([]);
    stepCountRef.current = 0;

    try {
      logInfo('Starting stream with payload');
      
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
              logInfo('Stream ended');
              break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            
            buffer = lines.pop() || '';

            for (const line of lines) {
              logInfo(`Processing SSE line: ${line.slice(0, 100)}...`);
              if (line.startsWith('data: ')) {
                const data = line.slice(6).trim();
                if (data && data !== '[DONE]') {
                  try {
                    // Try to decrypt the chunk if encrypted
                    const decryptedData = await decryptStreamChunk(data);
                    const update = JSON.parse(decryptedData);
                    handleStreamUpdate(update);
                  } catch (e) {
                    logError(`Failed to parse SSE data: ${data.slice(0, 200)}`, e instanceof Error ? e : new Error(String(e)));
                  }
                }
              } else if (line.trim()) {
                logInfo(`Non-data SSE line: ${line}`);
              }
            }
          }
        } catch (error) {
          logError('Stream processing error', error instanceof Error ? error : new Error(String(error)));
          setState(prev => ({
            ...prev,
            isStreaming: false,
            error: 'Stream processing failed',
          }));
        }
      };

      await processStream();

    } catch (error) {
      logError('Streaming error', error instanceof Error ? error : new Error(String(error)));
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
    differentialDiagnosisProgress: state.differentialDiagnosisProgress,
    noteGenerationProgress: state.noteGenerationProgress,

    // Additional state
    streamDifferentialDiagnoses,

    // Functions
    startStream,
    stopStream,
  };
};