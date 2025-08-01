'use client';

import { useState } from 'react';
import { JournalEntryType, JournalEntryCreate, createJournalEntry } from '@/lib/api';

interface CreateJournalEntryModalProps {
  patientId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const ENTRY_TYPE_OPTIONS = [
  { value: JournalEntryType.NOTE, label: 'Progress Note', color: 'bg-blue-100 text-blue-800' },
  { value: JournalEntryType.OBSERVATION, label: 'Clinical Observation', color: 'bg-green-100 text-green-800' },
  { value: JournalEntryType.TREATMENT, label: 'Treatment Note', color: 'bg-purple-100 text-purple-800' },
  { value: JournalEntryType.DIAGNOSIS, label: 'Diagnostic Assessment', color: 'bg-red-100 text-red-800' },
  { value: JournalEntryType.ASSESSMENT, label: 'Clinical Assessment', color: 'bg-yellow-100 text-yellow-800' },
  { value: JournalEntryType.PLAN, label: 'Care Plan', color: 'bg-indigo-100 text-indigo-800' }
];

const TEMPLATES = {
  [JournalEntryType.NOTE]: {
    title: 'Progress Note - [Date]',
    content: `SUBJECTIVE:
Patient reports...

OBJECTIVE:
Vital Signs: 
Physical Exam:
- General: 
- HEENT: 
- Cardiovascular: 
- Respiratory: 
- Abdomen: 
- Neurological: 

ASSESSMENT:
1. 
2. 

PLAN:
1. 
2. 
3. 

Follow-up: `
  },
  [JournalEntryType.OBSERVATION]: {
    title: 'Clinical Observation - [Date]',
    content: `OBSERVATION:
Date/Time: 
Location: 

FINDINGS:
- 
- 
- 

CLINICAL SIGNIFICANCE:


RECOMMENDATIONS:
- 
- `
  },
  [JournalEntryType.TREATMENT]: {
    title: 'Treatment Note - [Date]',
    content: `TREATMENT PROVIDED:
Date/Time: 
Provider: 

INTERVENTION:
- Procedure/Treatment: 
- Indication: 
- Technique: 

PATIENT RESPONSE:
- Immediate: 
- Complications: None/[specify]

POST-TREATMENT ASSESSMENT:
- 
- 

PLAN:
- Follow-up: 
- Monitoring: 
- Next steps: `
  },
  [JournalEntryType.DIAGNOSIS]: {
    title: 'Diagnostic Assessment - [Date]',
    content: `PRESENTING COMPLAINT:


HISTORY OF PRESENT ILLNESS:


RELEVANT PAST MEDICAL HISTORY:


EXAMINATION FINDINGS:


DIAGNOSTIC WORKUP:
- Laboratory: 
- Imaging: 
- Other studies: 

DIFFERENTIAL DIAGNOSIS:
1. 
2. 
3. 

WORKING DIAGNOSIS:


CONFIDENCE LEVEL: 

PLAN FOR FURTHER EVALUATION:
- 
- `
  },
  [JournalEntryType.ASSESSMENT]: {
    title: 'Clinical Assessment - [Date]',
    content: `PATIENT STATUS:
- Current condition: 
- Changes since last assessment: 

REVIEW OF SYSTEMS:
- Constitutional: 
- Cardiovascular: 
- Respiratory: 
- GI: 
- GU: 
- Musculoskeletal: 
- Neurological: 
- Psychiatric: 

CLINICAL IMPRESSION:
1. 
2. 

RISK FACTORS:
- 
- 

RECOMMENDATIONS:
- 
- `
  },
  [JournalEntryType.PLAN]: {
    title: 'Care Plan - [Date]',
    content: `CARE GOALS:
1. 
2. 
3. 

INTERVENTIONS:
- Medications: 
- Procedures: 
- Therapies: 
- Lifestyle modifications: 

MONITORING PLAN:
- Parameters to monitor: 
- Frequency: 
- Responsible provider: 

PATIENT EDUCATION:
- Topics covered: 
- Resources provided: 
- Understanding confirmed: 

FOLLOW-UP:
- Next appointment: 
- Emergency contact criteria: 
- Patient instructions: 

COORDINATION OF CARE:
- Other providers involved: 
- Communication plan: `
  }
};

export default function CreateJournalEntryModal({ 
  patientId, 
  isOpen, 
  onClose, 
  onSuccess 
}: CreateJournalEntryModalProps) {
  const [selectedType, setSelectedType] = useState<JournalEntryType>(JournalEntryType.NOTE);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTypeChange = (type: JournalEntryType) => {
    setSelectedType(type);
    const template = TEMPLATES[type];
    const currentDate = new Date().toLocaleDateString('en-US');
    setTitle(template.title.replace('[Date]', currentDate));
    setContent(template.content);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!title.trim() || !content.trim()) {
      setError('Title and content are required');
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
          <h2 className="text-xl font-semibold text-gray-900">Create New Journal Entry</h2>
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
                Entry Type
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
                Title
              </label>
              <input
                id="title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="Enter journal entry title..."
                disabled={isSubmitting}
                required
              />
            </div>

            {/* Content */}
            <div>
              <label htmlFor="content" className="block text-sm font-medium text-gray-700 mb-2">
                Content
              </label>
              <textarea
                id="content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={16}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono text-sm"
                placeholder="Enter journal entry content..."
                disabled={isSubmitting}
                required
              />
              <p className="mt-1 text-xs text-gray-500">
                Tip: Use the entry type buttons above to load different templates
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
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !title.trim() || !content.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
            >
              {isSubmitting && (
                <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
              )}
              <span>{isSubmitting ? 'Creating...' : 'Create Entry'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}