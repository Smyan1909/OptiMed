import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Activity, Clock, Stethoscope, Lightbulb } from 'lucide-react';
import { useTranslations } from 'next-intl';

// Function to format numbers to 2 decimal places in text
const formatNumbersInText = (text: string): string => {
  return text.replace(/\b\d+\.\d{3,}\b/g, (match) => {
    const num = parseFloat(match);
    return num.toFixed(2);
  });
};

interface SBARResults {
  situation?: string;
  background?: string;
  assessment?: string;
  recommendation?: string;
}

interface SBARSummaryCardsProps {
  sbarResults: SBARResults;
  isLoading?: boolean;
  reasoning?: string;
  reasoningSteps?: string[];
}

// Custom markdown components for SBAR cards
const SBARMarkdownComponents = {
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

const getSBARConfig = (component: keyof SBARResults, t: any) => {
  const configs = {
    situation: {
      title: t('situation'),
      icon: Activity,
      color: 'bg-red-50 border-red-200',
      iconColor: 'text-red-600',
      badgeColor: 'bg-red-100 text-red-800',
      description: t('situationDescription')
    },
    background: {
      title: t('background'),
      icon: Clock,
      color: 'bg-blue-50 border-blue-200',
      iconColor: 'text-blue-600',
      badgeColor: 'bg-blue-100 text-blue-800',
      description: t('backgroundDescription')
    },
    assessment: {
      title: t('assessment'),
      icon: Stethoscope,
      color: 'bg-green-50 border-green-200',
      iconColor: 'text-green-600',
      badgeColor: 'bg-green-100 text-green-800',
      description: t('assessmentDescription')
    },
    recommendation: {
      title: t('recommendation'),
      icon: Lightbulb,
      color: 'bg-yellow-50 border-yellow-200',
      iconColor: 'text-yellow-600',
      badgeColor: 'bg-yellow-100 text-yellow-800',
      description: t('recommendationDescription')
    }
  };
  return configs[component];
};

export const SBARSummaryCards: React.FC<SBARSummaryCardsProps> = ({
  sbarResults,
  isLoading = false,
  reasoning,
  reasoningSteps
}) => {
  const t = useTranslations('sbar');

  if (!sbarResults || Object.keys(sbarResults).length === 0) {
    return null;
  }

  const components: (keyof SBARResults)[] = ['situation', 'background', 'assessment', 'recommendation'];

  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <Stethoscope className="h-6 w-6 text-blue-600" />
        <h3 className="text-xl font-semibold text-gray-900">{t('sbarSummary')}</h3>
        <Badge variant="secondary" className="text-sm px-3 py-1">
          {t('healthcareModel')}
        </Badge>
      </div>

      <div className="grid gap-6 grid-cols-1 xl:grid-cols-2">
        {components.map((component) => {
          const config = getSBARConfig(component, t);
          const Icon = config.icon;
          const content = sbarResults[component];
          const hasContent = content && content.trim() !== '';

          return (
            <Card
              key={component}
              className={`border-2 hover:shadow-lg transition-all duration-200 ${config.color} min-h-[400px] w-full max-w-none flex flex-col`}
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
                    {isLoading && !hasContent ? 'Loading...' : hasContent ? 'Complete' : 'Pending'}
                  </Badge>
                </CardTitle>
                <p className="text-xs text-gray-500 leading-tight">{config.description}</p>
              </CardHeader>

              <CardContent className="pt-0 flex-grow flex flex-col">
                {isLoading && !hasContent ? (
                  <div className="flex-grow flex items-center justify-center">
                    <div className="animate-pulse text-sm text-gray-500">
                      Generating {component}...
                    </div>
                  </div>
                ) : hasContent ? (
                  <div className="text-sm leading-relaxed flex-grow overflow-hidden p-2">
                    <ReactMarkdown
                      components={SBARMarkdownComponents}
                      remarkPlugins={[remarkGfm]}
                    >
                      {formatNumbersInText(content)}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="flex-grow flex items-center justify-center">
                    <div className="text-sm text-gray-400 italic">
                      {component.charAt(0).toUpperCase() + component.slice(1)} content not available
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {(reasoning || (reasoningSteps && reasoningSteps.length > 0)) && (
        <div className="mt-6">
          <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
            <h4 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-blue-600">🧠</span>
              {t('aiReasoning')}
            </h4>

            {reasoningSteps && reasoningSteps.length > 0 && (
              <div className="mb-4">
                <h5 className="text-sm font-medium text-gray-700 mb-2">{t('reasoningSteps')}:</h5>
                <ul className="space-y-2">
                  {reasoningSteps.map((step, index) => (
                    <li key={index} className="text-sm text-gray-600 bg-white p-2 rounded border-l-4 border-blue-200">
                      <span className="font-medium text-blue-600">Step {index + 1}:</span> {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {reasoning && (
              <div>
                <h5 className="text-sm font-medium text-gray-700 mb-2">{t('detailedReasoning')}:</h5>
                <div className="text-sm text-gray-600 bg-white p-3 rounded border">
                  {reasoning}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-sm text-blue-700 flex items-start leading-relaxed">
          <Stethoscope className="h-4 w-4 inline mr-3 flex-shrink-0 mt-0.5" />
          <span dangerouslySetInnerHTML={{ __html: t('sbarDescription') }} />
        </p>
      </div>
    </div>
  );
};