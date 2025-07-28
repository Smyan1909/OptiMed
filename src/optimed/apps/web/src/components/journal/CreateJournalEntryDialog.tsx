'use client';

import { useState, useEffect } from 'react';
import { JournalEntryType, JournalEntryCreate, createJournalEntry } from '@/lib/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { TextareaAutocomplete } from '../ui/textarea-autocomplete';
import JournalGenerationDialog from './JournalGenerationDialog';
import { 
  FileText, 
  Eye, 
  Activity, 
  Stethoscope, 
  ClipboardList, 
  Calendar,
  Save,
  X,
  Sparkles,
  Wand2
} from 'lucide-react';

interface CreateJournalEntryDialogProps {
  patientId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const ENTRY_TYPE_OPTIONS = [
  { 
    value: JournalEntryType.NOTE, 
    label: 'Progress Note', 
    description: 'Patient progress and status updates',
    icon: FileText,
    color: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100' 
  },
  { 
    value: JournalEntryType.OBSERVATION, 
    label: 'Clinical Observation', 
    description: 'Clinical findings and observations',
    icon: Eye,
    color: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100' 
  },
  { 
    value: JournalEntryType.TREATMENT, 
    label: 'Treatment Note', 
    description: 'Treatment interventions and procedures',
    icon: Activity,
    color: 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100' 
  },
  { 
    value: JournalEntryType.DIAGNOSIS, 
    label: 'Diagnostic Assessment', 
    description: 'Diagnostic evaluations and findings',
    icon: Stethoscope,
    color: 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100' 
  },
  { 
    value: JournalEntryType.ASSESSMENT, 
    label: 'Clinical Assessment', 
    description: 'Patient assessment and evaluation',
    icon: ClipboardList,
    color: 'bg-yellow-50 text-yellow-700 border-yellow-200 hover:bg-yellow-100' 
  },
  { 
    value: JournalEntryType.PLAN, 
    label: 'Care Plan', 
    description: 'Care planning and future interventions',
    icon: Calendar,
    color: 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100' 
  }
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

export default function CreateJournalEntryDialog({ 
  patientId, 
  isOpen, 
  onClose, 
  onSuccess 
}: CreateJournalEntryDialogProps) {
  const [selectedType, setSelectedType] = useState<JournalEntryType>(JournalEntryType.NOTE);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGenerationDialog, setShowGenerationDialog] = useState(false);

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
      
      // Reset form first
      setTitle('');
      setContent('');
      setSelectedType(JournalEntryType.NOTE);
      setError(null);
      
      // Call onSuccess to refresh the journal entries list
      onSuccess();
      
      // Close the dialog
      onClose();
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
  useEffect(() => {
    if (isOpen) {
      // Always initialize with template when opening
      handleTypeChange(selectedType);
    }
  }, [isOpen]);

  // Reset form when modal closes
  useEffect(() => {
    if (!isOpen) {
      setTitle('');
      setContent('');
      setSelectedType(JournalEntryType.NOTE);
      setError(null);
    }
  }, [isOpen]);

  const handleGenerate = (generatedTitle: string, generatedContent: string) => {
    setTitle(generatedTitle);
    setContent(generatedContent);
  };

  const selectedOption = ENTRY_TYPE_OPTIONS.find(option => option.value === selectedType);

  return (
    <>
      <Dialog open={isOpen} onOpenChange={handleClose}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader className="border-b border-gray-200 pb-4">
            <DialogTitle className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <FileText className="h-5 w-5 text-blue-600" />
              Create New Journal Entry
              <Badge variant="secondary" className="ml-2 text-xs flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                AI Enhanced
              </Badge>
            </DialogTitle>
            <DialogDescription className="text-gray-600">
              Document patient care with structured medical templates, AI-powered autocomplete, and automatic generation
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Error Display */}
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Entry Type Selection */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <Label className="text-base font-medium text-gray-900">
                    Select Entry Type
                  </Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setShowGenerationDialog(true)}
                    disabled={isSubmitting}
                    className="flex items-center gap-2 text-purple-600 border-purple-200 hover:bg-purple-50"
                  >
                    <Wand2 className="h-4 w-4" />
                    Generate with AI
                  </Button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {ENTRY_TYPE_OPTIONS.map((option) => {
                    const IconComponent = option.icon;
                    const isSelected = selectedType === option.value;
                    
                    return (
                      <Card
                        key={option.value}
                        className={`cursor-pointer transition-all duration-200 ${
                          isSelected 
                            ? option.color + ' ring-2 ring-offset-2 ring-blue-500' 
                            : 'hover:shadow-md border-gray-200'
                        }`}
                        onClick={() => handleTypeChange(option.value)}
                      >
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <IconComponent className="h-4 w-4" />
                            {option.label}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <CardDescription className="text-xs">
                            {option.description}
                          </CardDescription>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
                
                {selectedOption && (
                  <div className="mt-3">
                    <Badge variant="secondary" className="text-xs">
                      Selected: {selectedOption.label}
                    </Badge>
                  </div>
                )}
              </div>

              {/* Title */}
              <div className="space-y-2">
                <Label htmlFor="title" className="text-sm font-medium text-gray-900">
                  Entry Title
                </Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Enter a descriptive title for this entry..."
                  disabled={isSubmitting}
                  required
                  className="font-medium"
                />
              </div>

              {/* Content with Autocomplete */}
              <div className="space-y-2">
                <Label htmlFor="content" className="text-sm font-medium text-gray-900">
                  Entry Content
                </Label>
                <TextareaAutocomplete
                  id="content"
                  value={content}
                  onChange={setContent}
                  entryType={selectedType}
                  rows={16}
                  placeholder="Enter detailed clinical information..."
                  disabled={isSubmitting}
                  required
                />
                <p className="text-xs text-gray-500 flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  Template loaded automatically. AI suggestions available while typing.
                </p>
              </div>
            </div>

            {/* Footer */}
            <DialogFooter className="border-t border-gray-200 pt-4 bg-gray-50">
              <div className="flex items-center gap-3 w-full justify-end">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleClose}
                  disabled={isSubmitting}
                >
                  <X className="h-4 w-4 mr-2" />
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !title.trim() || !content.trim()}
                  className="min-w-[120px]"
                >
                  {isSubmitting ? (
                    <>
                      <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Save className="h-4 w-4 mr-2" />
                      Create Entry
                    </>
                  )}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Generation Dialog */}
      <JournalGenerationDialog
        isOpen={showGenerationDialog}
        onClose={() => setShowGenerationDialog(false)}
        onGenerate={handleGenerate}
        entryType={selectedType}
        patientId={patientId}
      />
    </>
  );
}
