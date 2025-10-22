import React from 'react';
import { MarkdownWithCitations } from './MarkdownWithCitations';
import type { Citation } from './CitationModal';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { FileText } from 'lucide-react';
import { useTranslations } from 'next-intl';

interface EncounterDetail {
  id: string;
  date: string;
  encounter_type: string;
  category: 'major' | 'minor';
  brief: string;
  detailed: string;
}

interface EncounterDetailModalProps {
  encounter: EncounterDetail | null;
  onClose: () => void;
  citations: Record<string, Citation>;
}

const DetailMarkdownComponents = {
  p: ({ children }: any) => <p className="text-sm text-gray-700 leading-relaxed mb-3">{children}</p>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
  ul: ({ children }: any) => <ul className="list-disc list-outside ml-4 space-y-1 mb-3">{children}</ul>,
  li: ({ children }: any) => <li className="text-sm text-gray-700">{children}</li>,
};

export const EncounterDetailModal: React.FC<EncounterDetailModalProps> = ({
  encounter,
  onClose,
  citations
}) => {
  if (!encounter) return null;

  const t = useTranslations('encountersCard');

  const categoryLabel = encounter.category === 'major'
    ? t('majorEncounter')
    : t('minorEncounter');

  const categoryColor = encounter.category === 'major' ? 'text-red-600' : 'text-blue-600';

  return (
    <Dialog open={!!encounter} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <FileText className="h-5 w-5 text-indigo-600" />
            {encounter.encounter_type}
          </DialogTitle>
          <DialogDescription className="flex flex-col gap-1 mt-2">
            <span className="text-sm text-gray-600">{encounter.date}</span>
            <span className={`text-xs font-semibold ${categoryColor}`}>{categoryLabel}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
          <h4 className="text-sm font-semibold text-gray-900 mb-3">{t('detailSummary')}</h4>
          <MarkdownWithCitations
            content={encounter.detailed}
            citations={citations}
            components={DetailMarkdownComponents}
          />
        </div>

        <div className="mt-4 text-xs text-gray-500 border-t border-gray-200 pt-3">
          <p><strong>{t('note')}:</strong> {t('disclaimer')}</p>
        </div>
      </DialogContent>
    </Dialog>
  );
};
