'use client';

import { useState, useEffect } from 'react';
import { JournalEntry, JournalEntryType, fetchPatientJournalEntries } from '@/lib/api';
import { formatDistanceToNow } from 'date-fns';
import { useLocale, useTranslations } from 'next-intl';
import CreateJournalEntryDialog from './CreateJournalEntryDialog';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';

interface JournalListProps {
  patientId: string;
}

export default function JournalList({ patientId }: JournalListProps) {
  const t = useTranslations('journal');
  const locale = useLocale();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    fetchJournalEntries();
  }, [patientId]);

  const fetchJournalEntries = async () => {
    try {
      setLoading(true);
      setError(null);
      console.log('Fetching journal entries for patient:', patientId);
      
      const data = await fetchPatientJournalEntries(patientId);
      console.log('Journal entries received:', data);
      setEntries(data);
    } catch (err) {
      console.error('Failed to fetch journal entries:', err);
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSuccess = () => {
    // Refresh the journal entries after successful creation
    setIsRefreshing(true);
    fetchJournalEntries().finally(() => {
      setIsRefreshing(false);
    });
  };

  const getEntryTypeLabel = (type: JournalEntryType): string => t(`types.${type.toLowerCase()}` as any);

  const getEntryTypeColor = (type: JournalEntryType): string => {
    const colors = {
      [JournalEntryType.NOTE]: 'bg-blue-100 text-blue-800',
      [JournalEntryType.OBSERVATION]: 'bg-green-100 text-green-800',
      [JournalEntryType.TREATMENT]: 'bg-purple-100 text-purple-800',
      [JournalEntryType.DIAGNOSIS]: 'bg-red-100 text-red-800',
      [JournalEntryType.ASSESSMENT]: 'bg-yellow-100 text-yellow-800',
      [JournalEntryType.PLAN]: 'bg-indigo-100 text-indigo-800'
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow border border-gray-200 p-6">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow border border-gray-200 p-6">
        <div className="text-center py-8">
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={fetchJournalEntries}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            {t('actions.tryAgain')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow border border-gray-200">
      <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{t('list.title')}</h2>
          <p className="text-sm text-gray-600 mt-1">
            {t('list.subtitle')}
            {isRefreshing && (
              <span className="ml-2 text-blue-600 animate-pulse">
                • {t('list.updating')}
              </span>
            )}
          </p>
        </div>
        <button 
          onClick={() => setShowCreateModal(true)}
          className="flex items-center space-x-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors font-medium"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
          </svg>
          <span>{t('actions.newEntry')}</span>
        </button>
      </div>

      <div className="divide-y divide-gray-200">
        {entries.length === 0 ? (
          <div className="p-12 text-center">
            <div className="w-12 h-12 bg-gray-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h3 className="text-lg font-medium text-gray-900 mb-2">{t('empty.title')}</h3>
            <p className="text-gray-600 mb-6 max-w-sm mx-auto">{t('empty.subtitle')}</p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 transition-colors font-medium"
            >
              {t('actions.createFirst')}
            </button>
          </div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.entry_id}
              onClick={() => setSelectedEntry(entry)}
              className="p-6 hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center space-x-3 mb-3">
                    <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getEntryTypeColor(entry.entry_type)}`}>
                      {getEntryTypeLabel(entry.entry_type)}
                    </span>
                    <span className="text-sm text-gray-500 font-medium">
                      {formatDistanceToNow(new Date(entry.created_at), { addSuffix: true, locale: undefined })}
                    </span>
                  </div>
                  <h3 className="text-base font-semibold text-gray-900 mb-2 line-clamp-1">
                    {entry.title}
                  </h3>
                  <p className="text-sm text-gray-600 line-clamp-2 mb-3 leading-relaxed">
                    {entry.content}
                  </p>
                  <div className="flex items-center space-x-4 text-sm">
                    <span className="font-medium text-gray-900">{entry.author_name}</span>
                    <span className="text-gray-400">•</span>
                    <span className="text-gray-600">{entry.author_role}</span>
                  </div>
                </div>
                <div className="ml-4 flex-shrink-0">
                  <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Create Journal Entry Modal */}
      <CreateJournalEntryDialog
        patientId={patientId}
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSuccess={handleCreateSuccess}
      />

      {/* Journal Entry Modal */}
      {selectedEntry && (
        <JournalEntryModal 
          entry={selectedEntry}
          open={!!selectedEntry}
          onOpenChange={(open: boolean) => !open && setSelectedEntry(null)}
        />
      )}
    </div>
  );
}

// Journal Entry Modal Component
interface JournalEntryModalProps {
  entry: JournalEntry;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function JournalEntryModal({ entry, open, onOpenChange }: JournalEntryModalProps) {
  const t = useTranslations('journal');
  const getEntryTypeLabel = (type: JournalEntryType): string => t(`types.${type.toLowerCase()}` as any);

  const getEntryTypeColor = (type: JournalEntryType): string => {
    const colors = {
      [JournalEntryType.NOTE]: 'bg-blue-100 text-blue-800',
      [JournalEntryType.OBSERVATION]: 'bg-green-100 text-green-800',
      [JournalEntryType.TREATMENT]: 'bg-purple-100 text-purple-800',
      [JournalEntryType.DIAGNOSIS]: 'bg-red-100 text-red-800',
      [JournalEntryType.ASSESSMENT]: 'bg-yellow-100 text-yellow-800',
      [JournalEntryType.PLAN]: 'bg-indigo-100 text-indigo-800'
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('detail.title')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Entry Type Badge and Timestamp */}
          <div className="flex items-center justify-between">
            <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${getEntryTypeColor(entry.entry_type)}`}>
              {getEntryTypeLabel(entry.entry_type)}
            </span>
            <div className="text-sm text-gray-500">
              {t('detail.created')}: {new Date(entry.created_at).toLocaleString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
              })}
            </div>
          </div>

          {/* Title */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">{entry.title}</h3>
          </div>

          {/* Content */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">{t('detail.content')}</h4>
            <div className="prose prose-sm max-w-none">
              <pre className="whitespace-pre-wrap text-gray-900 font-mono text-sm leading-relaxed">
                {entry.content}
              </pre>
            </div>
          </div>

          {/* Author Information */}
          <div className="border-t border-gray-200 pt-4">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center space-x-4 text-gray-600">
                <span>
                  <span className="font-medium text-gray-900">{t('detail.author')}:</span> {entry.author_name}
                </span>
                <span>•</span>
                <span>
                  <span className="font-medium text-gray-900">{t('detail.role')}:</span> {entry.author_role}
                </span>
              </div>
              <div className="text-gray-500">
                {t('detail.updated')}: {new Date(entry.updated_at).toLocaleString(undefined)}
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}