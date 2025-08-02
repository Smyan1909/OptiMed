import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Loader2, Clock, Search, FileText, Database, Globe, Brain, Stethoscope, CheckCircle } from 'lucide-react';

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
  if (stepLower.includes('differential') || stepLower.includes('diagnos')) return <Stethoscope className="h-4 w-4" />;
  if (stepLower.includes('search') || stepLower.includes('web')) return <Globe className="h-4 w-4" />;
  if (stepLower.includes('reason') || stepLower.includes('analyz')) return <Brain className="h-4 w-4" />;
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
  isLongRunning,
  differentialDiagnosisProgress
}) => {
  // Debug logging
  console.log('🔍 StreamingProgress render:', {
    isStreaming,
    currentStep,
    differentialDiagnosisProgress
  });
  
  // Show immediately if streaming OR differential diagnosis is computing OR has any data
  const shouldShow = isStreaming || 
                     differentialDiagnosisProgress?.isComputing || 
                     (differentialDiagnosisProgress?.currentDiagnosis && differentialDiagnosisProgress.currentDiagnosis.trim() !== '');
  
  console.log('🔍 StreamingProgress shouldShow:', shouldShow);
  
  if (!shouldShow) return null;
  
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

        {/* Enhanced differential diagnosis progress indicator */}
        {differentialDiagnosisProgress?.isComputing && (
          <div className="border-t pt-3">
            <div className="bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg p-4 border border-purple-200">
              <div className="flex items-center gap-2 mb-3">
                <div className="relative">
                  <Stethoscope className="h-5 w-5 text-purple-600" />
                  <div className="absolute -top-1 -right-1 w-3 h-3">
                    <div className="w-3 h-3 bg-purple-400 rounded-full animate-ping"></div>
                    <div className="absolute inset-0 w-3 h-3 bg-purple-500 rounded-full animate-pulse"></div>
                  </div>
                </div>
                <span className="font-semibold text-purple-900">Computing Differential Diagnoses</span>
                <Badge variant="secondary" className="text-xs bg-purple-100 text-purple-700">
                  <Brain className="h-3 w-3 mr-1" />
                  Bayesian Analysis
                </Badge>
              </div>
              
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce"></div>
                    <span className="text-purple-800 font-medium">
                      {differentialDiagnosisProgress.currentDiagnosis}
                    </span>
                  </div>
                  {differentialDiagnosisProgress.currentDiagnosis.includes("System") && (
                    <Badge variant="outline" className="text-xs bg-blue-50 text-blue-600 border-blue-200">
                      System
                    </Badge>
                  )}
                </div>
                
                <div className="bg-white/70 rounded-md p-2 border border-purple-100">
                  <div className="flex items-center gap-2 text-xs text-purple-700">
                    <div className="flex items-center gap-1">
                      <div className="w-1.5 h-1.5 bg-purple-500 rounded-full animate-pulse"></div>
                      <span className="font-medium">{differentialDiagnosisProgress.currentStep}</span>
                    </div>
                    {differentialDiagnosisProgress.details && (
                      <span className="text-purple-600 bg-purple-50 px-2 py-0.5 rounded text-xs font-mono border border-purple-200">
                        {differentialDiagnosisProgress.details}
                      </span>
                    )}
                  </div>
                </div>
                
                {/* Visual progress indicators */}
                <div className="flex items-center gap-1 mt-2">
                  {[...Array(4)].map((_, i) => (
                    <div 
                      key={i}
                      className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                        i === 0 ? 'bg-purple-500 animate-pulse' : 
                        i === 1 ? 'bg-purple-300' : 
                        'bg-purple-200'
                      }`}
                      style={{
                        animationDelay: `${i * 150}ms`
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Show completion message for differential diagnosis */}
        {!differentialDiagnosisProgress?.isComputing && 
         differentialDiagnosisProgress?.currentDiagnosis && 
         differentialDiagnosisProgress.currentDiagnosis.toLowerCase().includes('complete') && (
          <div className="border-t pt-3">
            <div className="bg-gradient-to-r from-green-50 to-blue-50 rounded-lg p-3 border border-green-200">
              <div className="flex items-center gap-2 text-sm text-green-800">
                <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                <span className="font-medium">Differential Diagnoses Generated</span>
                {differentialDiagnosisProgress.details && (
                  <span className="text-xs text-green-600 bg-green-100 px-2 py-0.5 rounded border border-green-200">
                    {differentialDiagnosisProgress.details}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Show a simple indicator when AI is actively reasoning */}
        {(currentStep.toLowerCase().includes('diagnos') || currentStep.toLowerCase().includes('analyz')) && 
         !differentialDiagnosisProgress?.isComputing && (
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