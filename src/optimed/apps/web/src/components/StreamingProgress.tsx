import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Loader2, Clock, Search, FileText, Database, Globe, Brain } from 'lucide-react';

interface StreamingProgressProps {
  isStreaming: boolean;
  currentStep: string;
  currentDescription: string;
  progress: number;
  reasoning: string[];
  currentReasoning: string;
  estimatedTime?: string;
  isLongRunning?: boolean;
}

const getStepIcon = (step: string) => {
  const stepLower = step.toLowerCase();
  if (stepLower.includes('search') || stepLower.includes('web')) return <Globe className="h-4 w-4" />;
  if (stepLower.includes('reason') || stepLower.includes('analyz') || stepLower.includes('diagnos')) return <Brain className="h-4 w-4" />;
  if (stepLower.includes('retrieve') || stepLower.includes('chunk')) return <Search className="h-4 w-4" />;
  if (stepLower.includes('generate') || stepLower.includes('image')) return <FileText className="h-4 w-4" />;
  if (stepLower.includes('load') || stepLower.includes('fetch')) return <Database className="h-4 w-4" />;
  return <Loader2 className="h-4 w-4 animate-spin" />;
};

export const StreamingProgress: React.FC<StreamingProgressProps> = ({
  isStreaming,
  currentStep,
  currentDescription,
  progress,
  reasoning,
  currentReasoning,
  estimatedTime,
  isLongRunning
}) => {
  if (!isStreaming) return null;
  
  if (currentStep.toLowerCase().includes('generating response')) {
    return (
      <div className="flex items-center gap-2 text-sm text-blue-600 mb-4 px-4 py-2 bg-blue-50 rounded-lg">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Generating response...</span>
      </div>
    );
  }

  return (
    <Card className="mb-4 border-blue-200 bg-blue-50">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
          <span className="text-blue-900">CLARA is thinking...</span>
          {isLongRunning && (
            <Badge variant="secondary" className="text-xs">
              <Clock className="h-3 w-3 mr-1" />
              {estimatedTime || 'Complex analysis'}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Progress bar with current step */}
        <div>
          <div className="flex justify-between items-center text-sm mb-2">
            <div className="flex items-center gap-2">
              {getStepIcon(currentStep)}
              <span className="font-medium text-blue-900">{currentStep}</span>
            </div>
            <span className="text-blue-600">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
          {currentDescription && (
            <p className="text-sm text-blue-700 mt-2">{currentDescription}</p>
          )}
        </div>

        {/* Show a simple indicator when AI is actively reasoning */}
        {(currentStep.toLowerCase().includes('diagnos') || currentStep.toLowerCase().includes('analyz')) && (
          <div className="border-t pt-3">
            <div className="flex items-center gap-2 text-sm text-blue-800">
              <Brain className="h-4 w-4 animate-pulse text-blue-600" />
              <span className="italic">AI is analyzing the medical information...</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};