'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { JournalEntryType, JournalEntryCreate, createJournalEntry } from '@/lib/api';

interface CreateJournalEntryModalProps {
  patientId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function useEntryTypeOptions() {
  const t = useTranslations('journal');
  return [
    { value: JournalEntryType.NOTE, label: t('types.note'), color: 'bg-blue-100 text-blue-800' },
    { value: JournalEntryType.OBSERVATION, label: t('types.observation'), color: 'bg-green-100 text-green-800' },
    { value: JournalEntryType.TREATMENT, label: t('types.treatment'), color: 'bg-purple-100 text-purple-800' },
    { value: JournalEntryType.DIAGNOSIS, label: t('types.diagnosis'), color: 'bg-red-100 text-red-800' },
    { value: JournalEntryType.ASSESSMENT, label: t('types.assessment'), color: 'bg-yellow-100 text-yellow-800' },
    { value: JournalEntryType.PLAN, label: t('types.plan'), color: 'bg-indigo-100 text-indigo-800' }
  ];
}

function getTemplates(t: ReturnType<typeof useTranslations>) {
  return {
    [JournalEntryType.NOTE]: { title: t('templates.note.title'), content: t('templates.note.content') },
    [JournalEntryType.OBSERVATION]: { title: t('templates.observation.title'), content: t('templates.observation.content') },
    [JournalEntryType.TREATMENT]: { title: t('templates.treatment.title'), content: t('templates.treatment.content') },
    [JournalEntryType.DIAGNOSIS]: { title: t('templates.diagnosis.title'), content: t('templates.diagnosis.content') },
    [JournalEntryType.ASSESSMENT]: { title: t('templates.assessment.title'), content: t('templates.assessment.content') },
    [JournalEntryType.PLAN]: { title: t('templates.plan.title'), content: t('templates.plan.content') }
  } as const;
}

export default function CreateJournalEntryModal({ 
  patientId, 
  isOpen, 
  onClose, 
  onSuccess 
}: CreateJournalEntryModalProps) {
  const t = useTranslations('journal');
  const locale = useLocale();
  const ENTRY_TYPE_OPTIONS = useEntryTypeOptions();
  const TEMPLATES = getTemplates(t);
  const [selectedType, setSelectedType] = useState<JournalEntryType>(JournalEntryType.NOTE);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTypeChange = (type: JournalEntryType) => {
    setSelectedType(type);
    const template = TEMPLATES[type];
    const currentDate = new Date().toLocaleDateString(locale);
    setTitle(template.title.replace('[Date]', currentDate));
    setContent(template.content);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!title.trim() || !content.trim()) {
      setError(t('create.error.required'));
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const entryData: JournalEntryCreate = {
        patient_id: patientId,
        title: title.trim(),
        content: content.trim(),
        entry_type: selectedType
      };

      await createJournalEntry(patientId, entryData);
      onSuccess();
      onClose();
      
      // Reset form
      setTitle('');
      setContent('');
      setSelectedType(JournalEntryType.NOTE);
    } catch (err) {
      console.error('Failed to create journal entry:', err);
      setError(err instanceof Error ? err.message : 'Failed to create journal entry');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      onClose();
      setError(null);
    }
  };

  // Initialize template when modal opens
  useState(() => {
    if (isOpen && !title && !content) {
      handleTypeChange(selectedType);
    }
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <h2 className="text-xl font-semibold text-gray-900">{t('create.header.title')}</h2>
          <button
            onClick={handleClose}
            disabled={isSubmitting}
            className="text-gray-400 hover:text-gray-600 transition-colors text-xl disabled:opacity-50"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
          {/* Content */}
          <div className="p-6 flex-1 overflow-y-auto space-y-6">
            {/* Error Display */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-md p-4">
                <div className="flex">
                  <div className="text-red-400 text-sm">⚠️</div>
                  <div className="ml-3">
                    <p className="text-sm text-red-800">{error}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Entry Type Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                {t('create.selectTypeLabel')}
              </label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {ENTRY_TYPE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleTypeChange(option.value)}
                    className={`p-3 rounded-lg border text-sm font-medium transition-all ${
                      selectedType === option.value
                        ? `${option.color} border-current`
                        : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Title */}
            <div>
              <label htmlFor="title" className="block text-sm font-medium text-gray-700 mb-2">
                {t('create.field.title')}
              </label>
              <input
                id="title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder={t('create.field.titlePlaceholder')}
                disabled={isSubmitting}
                required
              />
            </div>

            {/* Content */}
            <div>
              <label htmlFor="content" className="block text-sm font-medium text-gray-700 mb-2">
                {t('create.field.content')}
              </label>
              <textarea
                id="content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={16}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono text-sm"
                placeholder={t('create.field.contentPlaceholder')}
                disabled={isSubmitting}
                required
              />
              <p className="mt-1 text-xs text-gray-500">
                {t('create.field.templateTip')}
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end space-x-3 p-6 border-t border-gray-200 bg-gray-50">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
            >
              {t('create.buttons.cancel')}
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !title.trim() || !content.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
            >
              {isSubmitting && (
                <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
              )}
              <span>{isSubmitting ? t('create.buttons.creating') : t('create.buttons.create')}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}