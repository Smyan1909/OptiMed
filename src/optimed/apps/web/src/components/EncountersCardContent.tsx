import React from 'react';
import { MarkdownWithCitations } from './MarkdownWithCitations';
import { useTranslations } from 'next-intl';
import type { Citation } from './CitationModal';

interface EncounterDetail {
  id: string;
  date: string;
  encounter_type: string;
  category: 'major' | 'minor';
  brief: string;
  detailed: string;
}

interface EncountersCardContentProps {
  encountersData: {
    content: string;
    structured_data?: EncounterDetail[];
  } | string;
  onEncounterClick: (encounter: EncounterDetail) => void;
  citations: Record<string, Citation>;
}

const SummaryMarkdownComponents = {
  p: ({ children }: any) => <p className="text-sm text-gray-700 leading-snug mb-1.5">{children}</p>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
};

export const EncountersCardContent: React.FC<EncountersCardContentProps> = ({
  encountersData,
  onEncounterClick,
  citations
}) => {
  // Handle legacy string format

  const t = useTranslations('generalSummary');
  if (typeof encountersData === 'string') {
    return <MarkdownWithCitations content={encountersData} citations={citations} components={SummaryMarkdownComponents} />;
  }

  const { structured_data, content } = encountersData;

  // If structured data available, render clickable bullets
  if (structured_data && structured_data.length > 0) {
    const major = structured_data.filter(e => e.category === 'major');
    const minor = structured_data.filter(e => e.category === 'minor');

    return (
      <div className="space-y-4">
        {major.length > 0 && (
          <div>
            <h4 className="font-semibold text-sm mb-2 text-gray-900">{t('majorEncounters')}</h4>
            <div className="space-y-1">
              {major.map(enc => (
                <button
                  key={enc.id}
                  onClick={() => onEncounterClick(enc)}
                  className="w-full text-left hover:bg-indigo-100 p-2 rounded transition-colors duration-150 border border-transparent hover:border-indigo-300"
                >
                  <MarkdownWithCitations
                    content={`• **${enc.encounter_type}** (${enc.date}) - ${enc.brief}`}
                    citations={citations}
                    components={SummaryMarkdownComponents}
                  />
                </button>
              ))}
            </div>
          </div>
        )}

        {minor.length > 0 && (
          <div>
            <h4 className="font-semibold text-sm mb-2 text-gray-900">{t('minorEncounters')}</h4>
            <div className="space-y-1">
              {minor.map(enc => (
                <button
                  key={enc.id}
                  onClick={() => onEncounterClick(enc)}
                  className="w-full text-left hover:bg-indigo-100 p-2 rounded transition-colors duration-150 border border-transparent hover:border-indigo-300"
                >
                  <MarkdownWithCitations
                    content={`• **${enc.encounter_type}** (${enc.date}) - ${enc.brief}`}
                    citations={citations}
                    components={SummaryMarkdownComponents}
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Fallback: render markdown content
  return <MarkdownWithCitations content={content} citations={citations} components={SummaryMarkdownComponents} />;
};
