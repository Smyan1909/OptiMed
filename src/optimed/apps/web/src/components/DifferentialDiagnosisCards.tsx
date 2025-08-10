import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertCircle, CheckCircle, Info, Brain } from 'lucide-react';
import { useTranslations } from 'next-intl';

// Function to format numbers to 2 decimal places in text
const formatNumbersInText = (text: string): string => {
  return text.replace(/\b\d+\.\d{3,}\b/g, (match) => {
    const num = parseFloat(match);
    return num.toFixed(2);
  });
};

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

// Custom markdown components for diagnosis cards
const DiagnosisMarkdownComponents = {
  // Style headings
  h1: ({ children }: any) => <h1 className="text-sm font-bold text-gray-900 mt-2 mb-1">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-sm font-semibold text-gray-900 mt-2 mb-1">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-xs font-medium text-gray-900 mt-1 mb-1">{children}</h3>,
  
  // Style paragraphs
  p: ({ children }: any) => <p className="text-sm text-gray-600 leading-relaxed mb-1">{children}</p>,
  
  // Style lists
  ul: ({ children }: any) => <ul className="list-disc list-outside ml-4 space-y-0.5 mb-1">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-outside ml-4 space-y-0.5 mb-1">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-600">{children}</li>,
  
  // Style code blocks
  code: ({ inline, children }: any) => {
    if (inline) {
      return <code className="bg-gray-100 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
    }
    return (
      <pre className="bg-gray-100 text-gray-800 p-2 rounded text-xs font-mono overflow-x-auto mb-1">
        <code>{children}</code>
      </pre>
    );
  },
  
  // Style blockquotes
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-2 border-gray-300 pl-2 italic text-gray-700 mb-1">
      {children}
    </blockquote>
  ),
  
  // Style strong/bold text
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
  
  // Style emphasis/italic text
  em: ({ children }: any) => <em className="italic text-gray-700">{children}</em>,
  
  // Style links
  a: ({ href, children }: any) => (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer" 
      className="text-blue-600 hover:text-blue-800 underline"
    >
      {children}
    </a>
  ),
  
  // Style tables
  table: ({ children }: any) => (
    <div className="overflow-x-auto mb-1">
      <table className="min-w-full border-collapse border border-gray-200">{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th className="border border-gray-200 bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-gray-200 px-2 py-1 text-xs text-gray-600">{children}</td>
  ),
};

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
  const t = useTranslations('diffDx');
  if (!diagnoses || diagnoses.length === 0) {
    return null;
  }

  // Sort by confidence (highest first)
  const sortedDiagnoses = [...diagnoses].sort((a, b) => b.confidence - a.confidence);

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-2 mb-2">
        <Brain className="h-4 w-4 text-blue-600" />
        <h3 className="text-sm font-semibold text-gray-900">{t('title')}</h3>
        <Badge variant="secondary" className="text-xs">
          {t('considerations', { count: diagnoses.length })}
        </Badge>
      </div>
      
      <div className="grid gap-2 md:grid-cols-1 lg:grid-cols-2">
        {sortedDiagnoses.map((diagnosis, index) => (
          <Card 
            key={`${diagnosis.icd_code}-${index}`} 
            className={`border-2 hover:shadow-md transition-all duration-200 ${getConfidenceBorderColor(diagnosis.confidence)}`}
          >
            <CardHeader className="pb-1">
              <CardTitle className="text-xs flex items-center justify-between">
                <div className="flex items-center gap-1 flex-1 min-w-0">
                  {getConfidenceIcon(diagnosis.confidence)}
                  <div className="font-extrabold text-gray-900 truncate flex-1 min-w-0 text-sm" style={{ fontFamily: 'Segoe UI, Arial, sans-serif' }}>
                    <ReactMarkdown
                      components={DiagnosisMarkdownComponents}
                      remarkPlugins={[remarkGfm]}
                    >
                      {formatNumbersInText(diagnosis.diagnosis_name)}
                    </ReactMarkdown>
                  </div>
                  {diagnosis.icd_code && (
                    <div className="ml-1 min-w-0 max-w-xs truncate">
                      <ReactMarkdown
                        components={DiagnosisMarkdownComponents}
                        remarkPlugins={[remarkGfm]}
                      >
                        {diagnosis.icd_code}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
                <Badge 
                  className={`text-xs font-semibold ml-1 flex-shrink-0 ${getConfidenceColor(diagnosis.confidence)}`}
                >
                  {(diagnosis.confidence * 100).toFixed(2)}%
                </Badge>
              </CardTitle>
            </CardHeader>
            
            <CardContent className="pt-0 space-y-1">
              {diagnosis.reasoning && (
                <div>
                  <h4 className="text-xs font-medium text-gray-700 mb-1 flex items-center">
                    <Info className="h-3 w-3 mr-1" />
                    <span>
                      <ReactMarkdown
                        components={DiagnosisMarkdownComponents}
                        remarkPlugins={[remarkGfm]}
                      >
                        {t('clinicalReasoning')}
                      </ReactMarkdown>
                    </span>
                  </h4>
                  <div className="text-xs text-gray-600 leading-relaxed bg-gray-50 p-1.5 rounded border-l-4 border-blue-300">
                    <ReactMarkdown
                      components={DiagnosisMarkdownComponents}
                      remarkPlugins={[remarkGfm]}
                    >
                      {formatNumbersInText(diagnosis.reasoning)}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
              
              {diagnosis.supporting_evidence && diagnosis.supporting_evidence.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-gray-700 mb-1 flex items-center">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    <span>
                      <ReactMarkdown
                        components={DiagnosisMarkdownComponents}
                        remarkPlugins={[remarkGfm]}
                      >
                        {t('supportingEvidence')}
                      </ReactMarkdown>
                    </span>
                  </h4>
                  <div className="space-y-1">
                    {diagnosis.supporting_evidence.map((evidence, evidenceIndex) => (
                      <div 
                        key={evidenceIndex} 
                        className="text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded p-1"
                      >
                        <ReactMarkdown
                          components={DiagnosisMarkdownComponents}
                          remarkPlugins={[remarkGfm]}
                        >
                          {formatNumbersInText(evidence)}
                        </ReactMarkdown>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      
      <div className="mt-2 p-2 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-xs text-blue-700 flex items-center">
          <Info className="h-3 w-3 inline mr-2 flex-shrink-0" />
          {t('disclaimer')}
        </p>
      </div>
    </div>
  );
};