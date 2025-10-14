import React from 'react';
import { logInfo } from '@/lib/logger';
import { Badge } from '@/components/ui/badge';
import { Clock, Search, FileText, Database, Globe, Brain, Stethoscope } from 'lucide-react';

interface DifferentialDiagnosisProgress {
  isComputing: boolean;
  currentDiagnosis: string;
  currentStep: string;
  details: string;
}

interface StreamingProgressProps {
  isStreaming: boolean;
  currentStep: string;
  currentDescription: string;
  progress: number;
  reasoning: string[];
  currentReasoning: string;
  estimatedTime?: string;
  isLongRunning?: boolean;
  differentialDiagnosisProgress?: DifferentialDiagnosisProgress;
}

const getStepIcon = (step: string) => {
  const stepLower = step.toLowerCase();
  if (stepLower.includes('differential') || stepLower.includes('diagnos')) return <Stethoscope className="h-3.5 w-3.5" />;
  if (stepLower.includes('search') || stepLower.includes('web')) return <Globe className="h-3.5 w-3.5" />;
  if (stepLower.includes('reason') || stepLower.includes('analyz')) return <Brain className="h-3.5 w-3.5" />;
  if (stepLower.includes('retrieve') || stepLower.includes('chunk') || stepLower.includes('search')) return <Search className="h-3.5 w-3.5" />;
  if (stepLower.includes('generate') || stepLower.includes('format')) return <FileText className="h-3.5 w-3.5" />;
  if (stepLower.includes('load') || stepLower.includes('fetch')) return <Database className="h-3.5 w-3.5" />;
  return <Database className="h-3.5 w-3.5" />;
};

// Pulsing dots animation component
const PulsingDots = () => (
  <div className="flex items-center gap-1">
    <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '0ms' }}></div>
    <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '150ms' }}></div>
    <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '300ms' }}></div>
  </div>
);

export const StreamingProgress: React.FC<StreamingProgressProps> = ({
  isStreaming,
  currentStep,
  currentDescription,
  progress,
  reasoning,
  currentReasoning,
  estimatedTime,
  isLongRunning,
  differentialDiagnosisProgress
}) => {
  // Debug logging
  logInfo('Streaming Progress: Render state', {
    isStreaming,
    currentStep,
    differentialDiagnosisProgress
  });

  // Show if streaming OR differential diagnosis is computing OR has any data
  const shouldShow = isStreaming ||
                     differentialDiagnosisProgress?.isComputing ||
                     (differentialDiagnosisProgress?.currentDiagnosis && differentialDiagnosisProgress.currentDiagnosis.trim() !== '');

  logInfo('Streaming Progress: Should show', { shouldShow });

  if (!shouldShow) return null;

  // Simple status for response generation
  if (currentStep.toLowerCase().includes('generating response')) {
    return (
      <div className="flex items-center gap-2.5 text-sm text-gray-600 mb-3 px-3 py-2">
        <PulsingDots />
        <span className="font-medium">Generating response...</span>
      </div>
    );
  }

  return (
    <div className="mb-3">
      {/* Main status indicator - ChatGPT/Cursor style */}
      <div className="flex items-center gap-2.5 text-sm text-gray-700 px-3 py-2">
        <div className="flex items-center gap-2">
          {getStepIcon(currentStep)}
          <PulsingDots />
        </div>
        <span className="font-medium">{currentDescription || currentStep}</span>
        {isLongRunning && estimatedTime && (
          <Badge variant="secondary" className="text-xs ml-auto">
            <Clock className="h-3 w-3 mr-1" />
            {estimatedTime}
          </Badge>
        )}
      </div>

      {/* Differential diagnosis progress - streamlined version */}
      {differentialDiagnosisProgress?.isComputing && (
        <div className="mt-2 px-3 py-2 bg-purple-50/50 rounded-md border border-purple-100">
          <div className="flex items-center gap-2.5 text-sm">
            <div className="relative">
              <Stethoscope className="h-3.5 w-3.5 text-purple-600" />
              <div className="absolute -top-0.5 -right-0.5 w-2 h-2">
                <div className="w-2 h-2 bg-purple-400 rounded-full animate-ping"></div>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <PulsingDots />
              <span className="font-medium text-purple-900">
                Computing: {differentialDiagnosisProgress.currentDiagnosis}
              </span>
            </div>
            {differentialDiagnosisProgress.details && (
              <span className="text-xs text-purple-600 ml-auto">
                {differentialDiagnosisProgress.details}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Completion message for differential diagnosis */}
      {!differentialDiagnosisProgress?.isComputing &&
       differentialDiagnosisProgress?.currentDiagnosis &&
       differentialDiagnosisProgress.currentDiagnosis.toLowerCase().includes('complete') && (
        <div className="mt-2 px-3 py-2 bg-green-50/50 rounded-md border border-green-100">
          <div className="flex items-center gap-2 text-sm text-green-800">
            <div className="w-2 h-2 bg-green-500 rounded-full"></div>
            <span className="font-medium">Differential Diagnoses Generated</span>
            {differentialDiagnosisProgress.details && (
              <span className="text-xs text-green-600 ml-auto">
                {differentialDiagnosisProgress.details}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};