'use client';

import { useState, useEffect } from 'react';
import { JournalEntry, JournalEntryType, fetchPatientJournalEntries } from '@/lib/api';
import { formatDistanceToNow } from 'date-fns';
import { enUS } from 'date-fns/locale';

interface JournalListProps {
  patientId: string;
}

export default function JournalList({ patientId }: JournalListProps) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);

  useEffect(() => {
    fetchJournalEntries();
  }, [patientId]);

  const fetchJournalEntries = async () => {
    try {
      setLoading(true);
      setError(null);
      console.log('Fetching journal entries for patient:', patientId);
      
      // Use the API function instead of direct fetch
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

  const getEntryTypeLabel = (type: JournalEntryType): string => {
    const labels = {
      [JournalEntryType.NOTE]: 'Note',
      [JournalEntryType.OBSERVATION]: 'Observation',
      [JournalEntryType.TREATMENT]: 'Treatment',
      [JournalEntryType.DIAGNOSIS]: 'Diagnosis',
      [JournalEntryType.ASSESSMENT]: 'Assessment',
      [JournalEntryType.PLAN]: 'Plan'
    };
    return labels[type] || type;
  };

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
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-gray-200 rounded w-1/4"></div>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-20 bg-gray-200 rounded"></div>
            ))}
          </div>
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
            Try Again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow border border-gray-200">
      <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900">Journal Entries</h2>
        <button className="flex items-center space-x-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors">
          <span>+</span>
          <span>New Entry</span>
        </button>
      </div>

      <div className="divide-y divide-gray-200">
        {entries.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <p>No journal entries to display</p>
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
                  <div className="flex items-center space-x-3 mb-2">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getEntryTypeColor(entry.entry_type)}`}>
                      {getEntryTypeLabel(entry.entry_type)}
                    </span>
                    <span className="text-sm text-gray-500">
                      {formatDistanceToNow(new Date(entry.created_at), { addSuffix: true, locale: enUS })}
                    </span>
                  </div>
                  <h3 className="text-base font-medium text-gray-900 mb-2 truncate">
                    {entry.title}
                  </h3>
                  <p className="text-sm text-gray-600 line-clamp-2 mb-3">
                    {entry.content}
                  </p>
                  <div className="flex items-center space-x-4 text-sm text-gray-500">
                    <span className="font-medium">{entry.author_name}</span>
                    <span>•</span>
                    <span>{entry.author_role}</span>
                  </div>
                </div>
                <div className="ml-4 flex-shrink-0">
                  <span className="text-gray-400">→</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Journal Entry Modal */}
      {selectedEntry && (
        <JournalEntryModal
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
        />
      )}
    </div>
  );
}

// Journal Entry Modal Component
interface JournalEntryModalProps {
  entry: JournalEntry;
  onClose: () => void;
}

function JournalEntryModal({ entry, onClose }: JournalEntryModalProps) {
  const getEntryTypeLabel = (type: JournalEntryType): string => {
    const labels = {
      [JournalEntryType.NOTE]: 'Note',
      [JournalEntryType.OBSERVATION]: 'Observation',
      [JournalEntryType.TREATMENT]: 'Treatment',
      [JournalEntryType.DIAGNOSIS]: 'Diagnosis',
      [JournalEntryType.ASSESSMENT]: 'Assessment',
      [JournalEntryType.PLAN]: 'Plan'
    };
    return labels[type] || type;
  };

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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900">Journal Entry</h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors text-xl"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="p-6 space-y-4">
          <div className="flex items-center space-x-3">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getEntryTypeColor(entry.entry_type)}`}>
              {getEntryTypeLabel(entry.entry_type)}
            </span>
            <span className="text-sm text-gray-500">
              {new Date(entry.created_at).toLocaleString('en-US')}
            </span>
          </div>

          <h3 className="text-lg font-medium text-gray-900">{entry.title}</h3>

          <div className="prose prose-sm max-w-none">
            <p className="text-gray-700 whitespace-pre-wrap">{entry.content}</p>
          </div>

          <div className="pt-4 border-t border-gray-200">
            <div className="flex items-center space-x-4 text-sm text-gray-500">
              <span className="font-medium">{entry.author_name}</span>
              <span>•</span>
              <span>{entry.author_role}</span>
              <span>•</span>
              <span>Updated: {new Date(entry.updated_at).toLocaleString('en-US')}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}