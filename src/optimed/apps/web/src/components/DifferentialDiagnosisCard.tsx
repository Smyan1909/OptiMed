import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertCircle, CheckCircle, Info, Brain } from 'lucide-react';

interface DifferentialDiagnosis {
  icd_code: string;
  diagnosis_name: string;
  confidence: number;
  reasoning: string;
  supporting_evidence: string[];
}

interface DifferentialDiagnosisCardsProps {
  diagnoses: DifferentialDiagnosis[];
}

const getConfidenceColor = (confidence: number) => {
  if (confidence >= 0.8) return 'bg-green-100 text-green-800 border-green-200';
  if (confidence >= 0.6) return 'bg-yellow-100 text-yellow-800 border-yellow-200';
  if (confidence >= 0.4) return 'bg-orange-100 text-orange-800 border-orange-200';
  return 'bg-red-100 text-red-800 border-red-200';
};

const getConfidenceIcon = (confidence: number) => {
  if (confidence >= 0.7) return <CheckCircle className="h-4 w-4 text-green-600" />;
  if (confidence >= 0.5) return <AlertCircle className="h-4 w-4 text-orange-600" />;
  return <Info className="h-4 w-4 text-red-600" />;
};

const getConfidenceBorderColor = (confidence: number) => {
  if (confidence >= 0.8) return 'border-green-300';
  if (confidence >= 0.6) return 'border-yellow-300';
  if (confidence >= 0.4) return 'border-orange-300';
  return 'border-red-300';
};

export const DifferentialDiagnosisCards: React.FC<DifferentialDiagnosisCardsProps> = ({ 
  diagnoses 
}) => {
  if (!diagnoses || diagnoses.length === 0) {
    return null;
  }

  // Sort by confidence (highest first)
  const sortedDiagnoses = [...diagnoses].sort((a, b) => b.confidence - a.confidence);

  return (
    <div className="mt-4 space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <Brain className="h-5 w-5 text-blue-600" />
        <h3 className="text-lg font-semibold text-gray-900">Differential Diagnoses</h3>
        <Badge variant="secondary" className="text-xs">
          {diagnoses.length} consideration{diagnoses.length !== 1 ? 's' : ''}
        </Badge>
      </div>
      
      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-2">
        {sortedDiagnoses.map((diagnosis, index) => (
          <Card 
            key={`${diagnosis.icd_code}-${index}`} 
            className={`border-2 hover:shadow-md transition-all duration-200 ${getConfidenceBorderColor(diagnosis.confidence)}`}
          >
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center justify-between">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {getConfidenceIcon(diagnosis.confidence)}
                  <span className="font-medium text-gray-900 truncate">
                    {diagnosis.diagnosis_name}
                  </span>
                  {diagnosis.icd_code && (
                    <Badge variant="outline" className="text-xs font-mono flex-shrink-0">
                      {diagnosis.icd_code}
                    </Badge>
                  )}
                </div>
                <Badge 
                  className={`text-sm font-semibold ml-2 flex-shrink-0 ${getConfidenceColor(diagnosis.confidence)}`}
                >
                  {Math.round(diagnosis.confidence * 100)}%
                </Badge>
              </CardTitle>
            </CardHeader>
            
            <CardContent className="pt-0 space-y-3">
              {diagnosis.reasoning && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2 flex items-center">
                    <Info className="h-3 w-3 mr-1" />
                    Clinical Reasoning:
                  </h4>
                  <p className="text-sm text-gray-600 leading-relaxed bg-gray-50 p-3 rounded border-l-4 border-blue-300">
                    {diagnosis.reasoning}
                  </p>
                </div>
              )}
              
              {diagnosis.supporting_evidence && diagnosis.supporting_evidence.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2 flex items-center">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    Supporting Evidence:
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    {diagnosis.supporting_evidence.map((evidence, evidenceIndex) => (
                      <Badge 
                        key={evidenceIndex} 
                        variant="secondary" 
                        className="text-xs bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 transition-colors"
                      >
                        {evidence}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      
      <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-xs text-blue-700 flex items-center">
          <Info className="h-3 w-3 inline mr-2 flex-shrink-0" />
          These differential diagnoses are AI-generated suggestions based on available clinical data. 
          Always correlate with clinical judgment and additional testing as appropriate.
        </p>
      </div>
    </div>
  );
};