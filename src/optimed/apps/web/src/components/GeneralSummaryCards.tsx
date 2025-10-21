import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MarkdownWithCitations } from './MarkdownWithCitations';
import { EncountersCardContent } from './EncountersCardContent';
import { EncounterDetailModal } from './EncounterDetailModal';
import type { Citation } from './CitationModal';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  User,
  AlertCircle,
  Pill,
  TrendingUp,
  Calendar,
  AlertTriangle,
  FileText
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useLookup } from '@/hooks/useLookup';
import { LookupPanel } from '@/components/LookupPanel';

// Function to format numbers to 2 decimal places in text
const formatNumbersInText = (text: string): string => {
  return text.replace(/\b\d+\.\d{3,}\b/g, (match) => {
    const num = parseFloat(match);
    return num.toFixed(2);
  });
};

interface EncounterDetail {
  id: string;
  date: string;
  encounter_type: string;
  category: 'major' | 'minor';
  brief: string;
  detailed: string;
}

interface GeneralSummaryResults {
  snapshot?: string;
  problems?: string;
  medications?: string;
  trends?: string;
  encounters?: {
    content: string;
    structured_data?: EncounterDetail[];
  } | string;  // Support both old string format and new object format
  risks?: string;
}

interface GeneralSummaryCardsProps {
  summaryResults: GeneralSummaryResults;
  isLoading?: boolean;
  reasoning?: string;
  reasoningSteps?: string[];
  patientId?: string;
  sessionId?: string | null;
  citations?: Record<string, Citation>;
}

// Custom markdown components for summary cards
const SummaryMarkdownComponents = {
  // Style headings
  h1: ({ children }: any) => <h1 className="text-sm font-bold text-gray-900 mt-2 mb-1">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-sm font-semibold text-gray-900 mt-2 mb-1">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-xs font-medium text-gray-900 mt-1 mb-1">{children}</h3>,

  // Style paragraphs
  p: ({ children }: any) => <p className="text-sm text-gray-700 leading-snug mb-1.5">{children}</p>,

  // Style lists
  ul: ({ children }: any) => <ul className="list-disc list-outside ml-3 space-y-2 mb-3">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-outside ml-3 space-y-2 mb-3">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 leading-relaxed py-1">{children}</li>,

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
    <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-xs font-semibold text-gray-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-gray-200 px-2 py-1 text-xs text-gray-600">{children}</td>
  ),
};

// Component for summary card content with lookup functionality
const SummaryCardContent: React.FC<{
  content: string;
  lookup: any;
  isLoading: boolean;
  component: string;
  patientId?: string;
  sessionId?: string | null;
  citations?: Record<string, Citation>;
}> = ({ content, lookup, isLoading, component, patientId, sessionId, citations = {} }) => {
  return (
    <div
      ref={lookup.contentRef}
      className="text-sm leading-relaxed flex-grow overflow-hidden p-2 select-text"
      onTouchEnd={lookup.handleTouchEnd}
      onMouseUp={lookup.handleMouseUp}
      onKeyUp={lookup.handleKeyUp}
    >
      <MarkdownWithCitations
        content={formatNumbersInText(content)}
        citations={citations}
        components={SummaryMarkdownComponents}
      />
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

const getSummaryConfig = (component: keyof GeneralSummaryResults, t: any) => {
  const configs = {
    snapshot: {
      title: t('cards.snapshot.title'),
      icon: User,
      color: 'bg-blue-50 border-blue-200',
      iconColor: 'text-blue-600',
      badgeColor: 'bg-blue-100 text-blue-800',
      description: t('cards.snapshot.description')
    },
    problems: {
      title: t('cards.problems.title'),
      icon: AlertCircle,
      color: 'bg-red-50 border-red-200',
      iconColor: 'text-red-600',
      badgeColor: 'bg-red-100 text-red-800',
      description: t('cards.problems.description')
    },
    medications: {
      title: t('cards.medications.title'),
      icon: Pill,
      color: 'bg-purple-50 border-purple-200',
      iconColor: 'text-purple-600',
      badgeColor: 'bg-purple-100 text-purple-800',
      description: t('cards.medications.description')
    },
    trends: {
      title: t('cards.trends.title'),
      icon: TrendingUp,
      color: 'bg-green-50 border-green-200',
      iconColor: 'text-green-600',
      badgeColor: 'bg-green-100 text-green-800',
      description: t('cards.trends.description')
    },
    history: {
      title: t('cards.history.title'),
      icon: Calendar,
      color: 'bg-orange-50 border-orange-200',
      iconColor: 'text-orange-600',
      badgeColor: 'bg-orange-100 text-orange-800',
      description: t('cards.history.description')
    },
    risks: {
      title: t('cards.risks.title'),
      icon: AlertTriangle,
      color: 'bg-yellow-50 border-yellow-200',
      iconColor: 'text-yellow-600',
      badgeColor: 'bg-yellow-100 text-yellow-800',
      description: t('cards.risks.description')
    },
    encounters: {
      title: t('cards.encounters.title'),
      icon: FileText,
      color: 'bg-indigo-50 border-indigo-200',
      iconColor: 'text-indigo-600',
      badgeColor: 'bg-indigo-100 text-indigo-800',
      description: t('cards.encounters.description')
    }
  };
  return configs[component];
};

export const GeneralSummaryCards: React.FC<GeneralSummaryCardsProps> = ({
  summaryResults,
  isLoading = false,
  reasoning,
  reasoningSteps,
  patientId,
  sessionId,
  citations = {}
}) => {
  const t = useTranslations('generalSummary');
  const [selectedEncounter, setSelectedEncounter] = useState<EncounterDetail | null>(null);

  // Create separate lookup hooks for each card to avoid conflicts
  const snapshotLookup = useLookup({ patientId, sessionId });
  const problemsLookup = useLookup({ patientId, sessionId });
  const medicationsLookup = useLookup({ patientId, sessionId });
  const trendsLookup = useLookup({ patientId, sessionId });
  const encountersLookup = useLookup({ patientId, sessionId });
  const risksLookup = useLookup({ patientId, sessionId });

  const lookupMap = {
    snapshot: snapshotLookup,
    problems: problemsLookup,
    medications: medicationsLookup,
    trends: trendsLookup,
    encounters: encountersLookup,
    risks: risksLookup,
  };

  if (!summaryResults || Object.keys(summaryResults).length === 0) {
    return null;
  }

  // Grid cards (Cards 1-5)
  const gridComponents: (keyof GeneralSummaryResults)[] = [
    'snapshot', 'problems', 'medications', 'trends', 'risks'
  ];

  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <User className="h-6 w-6 text-blue-600" />
        <h3 className="text-xl font-semibold text-gray-900">{t('patientSummary')}</h3>
        <Badge variant="secondary" className="text-sm px-3 py-1">
          {t('comprehensiveView')}
        </Badge>
      </div>

      {/* Cards 1-6: Standard 2x3 grid */}
      <div className="grid gap-6 grid-cols-1 xl:grid-cols-2">
        {gridComponents.map((component) => {
          const config = getSummaryConfig(component, t);
          const Icon = config.icon;
          const content = summaryResults[component];
          const hasContent =
            typeof content === 'string'
              ? content.trim() !== ''
              : content && typeof content === 'object' && 'content' in content && content.content.trim() !== '';

          return (
            <Card
              key={component}
              className={`border-2 hover:shadow-lg transition-all duration-200 ${config.color} min-h-[350px] w-full max-w-none flex flex-col`}
            >
              <CardHeader className="pb-3 flex-shrink-0">
                <CardTitle className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <Icon className={`h-6 w-6 ${config.iconColor}`} />
                    <span className="font-bold text-gray-900 text-lg">{config.title}</span>
                  </div>
                  <Badge
                    className={`text-xs font-semibold ${config.badgeColor}`}
                  >
                    {isLoading && !hasContent ? t('loading') : hasContent ? t('complete') : t('pending')}
                  </Badge>
                </CardTitle>
                <p className="text-xs text-gray-500 leading-tight">{config.description}</p>
              </CardHeader>

              <CardContent className="pt-0 flex-grow flex flex-col">
                {isLoading && !hasContent ? (
                  <div className="flex-grow flex items-center justify-center">
                    <div className="animate-pulse text-sm text-gray-500">
                      {t('generating', { component })}
                    </div>
                  </div>
                ) : hasContent ? (
                  <SummaryCardContent
                    content={
                      typeof content === 'string'
                        ? content
                        : content && typeof content === 'object' && 'content' in content
                          ? content.content
                          : ''
                    }
                    lookup={lookupMap[component]}
                    isLoading={isLoading}
                    component={component}
                    patientId={patientId}
                    sessionId={sessionId}
                    citations={citations}
                  />
                ) : (
                  <div className="flex-grow flex items-center justify-center">
                    <div className="text-sm text-gray-400 italic">
                      {t('contentNotAvailable', { component: component.charAt(0).toUpperCase() + component.slice(1) })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Card 6: Recent Encounters (Full width, clickable) */}
      {(() => {
        const encounters = summaryResults.encounters;
        const hasEncounters = typeof encounters === 'string'
          ? encounters.trim() !== ''
          : encounters && typeof encounters === 'object' && 'content' in encounters && encounters.content.trim() !== '';

        return hasEncounters && (
        <Card className="border-2 bg-indigo-50 border-indigo-200 hover:shadow-lg transition-all duration-200 w-full">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <FileText className="h-6 w-6 text-indigo-600" />
                <span className="font-bold text-gray-900 text-lg">{t('cards.encounters.title')}</span>
              </div>
              <Badge className="text-xs font-semibold bg-indigo-100 text-indigo-800">
                {t('complete')}
              </Badge>
            </CardTitle>
            <p className="text-xs text-gray-500 leading-tight">{t('cards.encounters.description')}</p>
          </CardHeader>

          <CardContent className="pt-0 p-2">
            <EncountersCardContent
              encountersData={summaryResults.encounters}
              onEncounterClick={setSelectedEncounter}
              citations={citations}
            />
          </CardContent>
        </Card>
        );
      })()}

      {/* Encounter Detail Modal */}
      <EncounterDetailModal
        encounter={selectedEncounter}
        onClose={() => setSelectedEncounter(null)}
        citations={citations}
      />

      {(reasoning || (reasoningSteps && reasoningSteps.length > 0)) && (
        <div className="mt-6">
          <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
            <h4 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-blue-600">🧠</span>
              {t('aiReasoning')}
            </h4>

            {reasoningSteps && reasoningSteps.length > 0 && (
              <div className="mb-4">
                <h5 className="text-sm font-medium text-gray-700 mb-2">{t('reasoningSteps')}</h5>
                <ul className="space-y-2">
                  {reasoningSteps.map((step, index) => (
                    <li key={index} className="text-sm text-gray-600 bg-white p-2 rounded border-l-4 border-blue-200">
                      <span className="font-medium text-blue-600">{t('step', { step: index + 1 })}</span> {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {reasoning && (
              <div>
                <h5 className="text-sm font-medium text-gray-700 mb-2">{t('detailedReasoning')}</h5>
                <div className="text-sm text-gray-600 bg-white p-3 rounded border">
                  {reasoning}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-sm text-blue-700 flex items-start leading-relaxed mb-3">
          <User className="h-4 w-4 inline mr-3 flex-shrink-0 mt-0.5" />
          <span>
            <strong>{t('patientSummary')}</strong> {t('patientSummaryDescription')}
          </span>
        </p>
        <p className="text-xs text-gray-600 leading-relaxed border-t border-blue-200 pt-3">
          <strong>{t('disclaimer')}</strong> {t('disclaimerText')}
        </p>
      </div>
    </div>
  );
};
