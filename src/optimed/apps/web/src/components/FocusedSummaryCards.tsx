import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Heart,
  FileText,
  Activity,
  Droplet,
  Brain,
  TrendingUp,
  AlertCircle,
  Hexagon
} from 'lucide-react';
import { useLookup } from '@/hooks/useLookup';
import { LookupPanel } from '@/components/LookupPanel';

// Function to format numbers to 2 decimal places in text
const formatNumbersInText = (text: string): string => {
  return text.replace(/\b\d+\.\d{3,}\b/g, (match) => {
    const num = parseFloat(match);
    return num.toFixed(2);
  });
};

interface FocusedSummaryResults {
  diagnoses?: string;
  events?: string;
  medications?: string;
  objective_data?: string;
  assessment?: string;
  next_steps?: string;
}

interface FocusedSummaryCardsProps {
  summaryResults: FocusedSummaryResults;
  aspect: string;  // e.g., "Heart Disease"
  aspectIcon: string;  // e.g., "heart"
  isLoading?: boolean;
  patientId?: string;
  sessionId?: string | null;
}

// Custom markdown components for focused summary
const FocusedSummaryMarkdownComponents = {
  h1: ({ children }: any) => <h1 className="text-base font-bold text-gray-900 mt-3 mb-2">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-sm font-semibold text-gray-900 mt-2 mb-1">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-sm font-medium text-gray-900 mt-2 mb-1">{children}</h3>,
  p: ({ children }: any) => <p className="text-sm text-gray-700 leading-relaxed mb-2">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-outside ml-4 space-y-3 mb-3">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-outside ml-4 space-y-3 mb-3">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 leading-relaxed mb-2">{children}</li>,
  code: ({ inline, children }: any) => {
    if (inline) {
      return <code className="bg-gray-100 text-gray-800 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>;
    }
    return (
      <pre className="bg-gray-100 text-gray-800 p-3 rounded text-xs font-mono overflow-x-auto mb-2">
        <code>{children}</code>
      </pre>
    );
  },
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-3 border-blue-400 pl-3 italic text-gray-700 my-2">
      {children}
    </blockquote>
  ),
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em: ({ children }: any) => <em className="italic text-gray-700">{children}</em>,
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
  table: ({ children }: any) => (
    <div className="overflow-x-auto mb-4 mt-2">
      <table className="min-w-full border-collapse border-2 border-gray-300 bg-white shadow-sm">{children}</table>
    </div>
  ),
  thead: ({ children }: any) => (
    <thead className="bg-gray-100">{children}</thead>
  ),
  tbody: ({ children }: any) => (
    <tbody>{children}</tbody>
  ),
  th: ({ children }: any) => (
    <th className="border border-gray-300 bg-gray-100 px-4 py-3 text-sm font-bold text-gray-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-gray-300 px-4 py-3 text-sm text-gray-700">{children}</td>
  ),
  tr: ({ children }: any) => (
    <tr className="hover:bg-gray-50">{children}</tr>
  ),
  hr: () => <hr className="my-4 border-t border-gray-300" />,
};

// Component for section content with lookup functionality
const SectionContent: React.FC<{
  content: string;
  lookup: any;
  sectionName: string;
  patientId?: string;
  sessionId?: string | null;
}> = ({ content, lookup, sectionName, patientId, sessionId }) => {
  return (
    <div
      ref={lookup.contentRef}
      className="text-sm leading-relaxed select-text"
      onTouchEnd={lookup.handleTouchEnd}
      onMouseUp={lookup.handleMouseUp}
      onKeyUp={lookup.handleKeyUp}
    >
      <ReactMarkdown
        components={FocusedSummaryMarkdownComponents}
        remarkPlugins={[remarkGfm]}
      >
        {formatNumbersInText(content)}
      </ReactMarkdown>
      <lookup.LookupButton />
      {lookup.showLookup && lookup.lookupTerm && (
        <LookupPanel
          term={lookup.lookupTerm}
          onClose={lookup.closeLookup}
          patientId={patientId}
          sessionId={sessionId}
        />
      )}
    </div>
  );
};

// Icon mapper
const getIconComponent = (iconName: string) => {
  const icons: { [key: string]: any } = {
    heart: Heart,
    activity: Activity,
    droplet: Droplet,
    hexagon: Hexagon,
    brain: Brain,
    'trending-up': TrendingUp,
    'alert-circle': AlertCircle,
    'file-text': FileText,
  };
  return icons[iconName] || FileText;
};

export const FocusedSummaryCards: React.FC<FocusedSummaryCardsProps> = ({
  summaryResults,
  aspect,
  aspectIcon,
  isLoading = false,
  patientId,
  sessionId
}) => {
  // Create separate lookup hooks for each section
  const diagnosesLookup = useLookup({ patientId, sessionId });
  const eventsLookup = useLookup({ patientId, sessionId });
  const medicationsLookup = useLookup({ patientId, sessionId });
  const objectiveDataLookup = useLookup({ patientId, sessionId });
  const assessmentLookup = useLookup({ patientId, sessionId });
  const nextStepsLookup = useLookup({ patientId, sessionId });

  const lookupMap: { [key: string]: any } = {
    diagnoses: diagnosesLookup,
    events: eventsLookup,
    medications: medicationsLookup,
    objective_data: objectiveDataLookup,
    assessment: assessmentLookup,
    next_steps: nextStepsLookup,
  };

  if (!summaryResults || Object.keys(summaryResults).length === 0) {
    return null;
  }

  const Icon = getIconComponent(aspectIcon);

  return (
    <div className="mt-6 space-y-4">
      {/* Header with aspect name and icon */}
      <div className="flex items-center gap-3 mb-4">
        <Icon className="h-7 w-7 text-blue-600" />
        <h3 className="text-2xl font-bold text-gray-900">{aspect} Summary</h3>
        <Badge variant="secondary" className="text-sm px-3 py-1">
          Focused View
        </Badge>
      </div>

      {/* Single comprehensive card with all sections */}
      <Card className="border-2 border-blue-200 bg-gradient-to-br from-blue-50 to-white shadow-lg">
        <CardHeader className="pb-4 bg-blue-100 border-b-2 border-blue-200">
          <CardTitle className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Icon className="h-6 w-6 text-blue-700" />
              <span className="font-bold text-gray-900 text-xl">{aspect}</span>
            </div>
            <Badge className="text-xs font-semibold bg-blue-200 text-blue-900">
              {isLoading ? 'Generating...' : 'Complete'}
            </Badge>
          </CardTitle>
        </CardHeader>

        <CardContent className="pt-6 space-y-6">
          {/* Diagnoses Section */}
          {summaryResults.diagnoses && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <FileText className="h-5 w-5 text-red-600" />
                <h4 className="text-base font-bold text-gray-900">Diagnoses</h4>
              </div>
              <div className="border-l-4 border-red-300 pl-4 py-2 bg-red-50 rounded-r">
                <SectionContent
                  content={summaryResults.diagnoses}
                  lookup={lookupMap.diagnoses}
                  sectionName="diagnoses"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}

          {/* Key Events Section */}
          {summaryResults.events && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <Activity className="h-5 w-5 text-blue-600" />
                <h4 className="text-base font-bold text-gray-900">Key Events</h4>
              </div>
              <div className="border-l-4 border-blue-300 pl-4 py-2 bg-blue-50 rounded-r">
                <SectionContent
                  content={summaryResults.events}
                  lookup={lookupMap.events}
                  sectionName="events"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}

          {/* Current Medications Section */}
          {summaryResults.medications && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <Droplet className="h-5 w-5 text-purple-600" />
                <h4 className="text-base font-bold text-gray-900">Current Medications</h4>
              </div>
              <div className="border-l-4 border-purple-300 pl-4 py-2 bg-purple-50 rounded-r">
                <SectionContent
                  content={summaryResults.medications}
                  lookup={lookupMap.medications}
                  sectionName="medications"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}

          {/* Latest Objective Data Section */}
          {summaryResults.objective_data && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="h-5 w-5 text-green-600" />
                <h4 className="text-base font-bold text-gray-900">Latest Objective Data</h4>
              </div>
              <div className="border-l-4 border-green-300 pl-4 py-2 bg-green-50 rounded-r">
                <SectionContent
                  content={summaryResults.objective_data}
                  lookup={lookupMap.objective_data}
                  sectionName="objective_data"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}

          {/* Assessment Section */}
          {summaryResults.assessment && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <Brain className="h-5 w-5 text-indigo-600" />
                <h4 className="text-base font-bold text-gray-900">Assessment</h4>
              </div>
              <div className="border-l-4 border-indigo-300 pl-4 py-2 bg-indigo-50 rounded-r">
                <SectionContent
                  content={summaryResults.assessment}
                  lookup={lookupMap.assessment}
                  sectionName="assessment"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}

          {/* Next Steps Section */}
          {summaryResults.next_steps && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <AlertCircle className="h-5 w-5 text-orange-600" />
                <h4 className="text-base font-bold text-gray-900">Next Steps / Outstanding Issues</h4>
              </div>
              <div className="border-l-4 border-orange-300 pl-4 py-2 bg-orange-50 rounded-r">
                <SectionContent
                  content={summaryResults.next_steps}
                  lookup={lookupMap.next_steps}
                  sectionName="next_steps"
                  patientId={patientId}
                  sessionId={sessionId}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Disclaimer */}
      <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-sm text-blue-700 flex items-start leading-relaxed">
          <Icon className="h-4 w-4 inline mr-3 flex-shrink-0 mt-0.5" />
          <span>
            <strong>Focused Summary</strong> provides an aspect-specific deep dive into {aspect},
            including diagnoses, key events, medications, objective data, clinical assessment, and follow-up plans.
            This is an information system, not a medical device. Healthcare professionals must use their own
            clinical judgment and verify all information before making medical decisions.
          </span>
        </p>
      </div>
    </div>
  );
};
