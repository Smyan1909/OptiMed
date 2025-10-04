'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { JournalEntryType, JournalEntryCreate, createJournalEntry } from '@/lib/api';
import { logError } from '@/lib/logger';
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

function useEntryTypeOptions() {
  const t = useTranslations('journal');
  return [
    {
      value: JournalEntryType.NOTE,
      label: t('types.note'),
      description: t('typeDescriptions.note'),
      icon: FileText,
      color: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100'
    },
    {
      value: JournalEntryType.OBSERVATION,
      label: t('types.observation'),
      description: t('typeDescriptions.observation'),
      icon: Eye,
      color: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100'
    },
    {
      value: JournalEntryType.TREATMENT,
      label: t('types.treatment'),
      description: t('typeDescriptions.treatment'),
      icon: Activity,
      color: 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100'
    },
    {
      value: JournalEntryType.DIAGNOSIS,
      label: t('types.diagnosis'),
      description: t('typeDescriptions.diagnosis'),
      icon: Stethoscope,
      color: 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100'
    },
    {
      value: JournalEntryType.ASSESSMENT,
      label: t('types.assessment'),
      description: t('typeDescriptions.assessment'),
      icon: ClipboardList,
      color: 'bg-yellow-50 text-yellow-700 border-yellow-200 hover:bg-yellow-100'
    },
    {
      value: JournalEntryType.PLAN,
      label: t('types.plan'),
      description: t('typeDescriptions.plan'),
      icon: Calendar,
      color: 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
    }
  ];
}

function getTemplates(t: ReturnType<typeof useTranslations>) {
  return {
    [JournalEntryType.NOTE]: {
      title: t('templates.note.title'),
      content: t('templates.note.content')
    },
    [JournalEntryType.OBSERVATION]: {
      title: t('templates.observation.title'),
      content: t('templates.observation.content')
    },
    [JournalEntryType.TREATMENT]: {
      title: t('templates.treatment.title'),
      content: t('templates.treatment.content')
    },
    [JournalEntryType.DIAGNOSIS]: {
      title: t('templates.diagnosis.title'),
      content: t('templates.diagnosis.content')
    },
    [JournalEntryType.ASSESSMENT]: {
      title: t('templates.assessment.title'),
      content: t('templates.assessment.content')
    },
    [JournalEntryType.PLAN]: {
      title: t('templates.plan.title'),
      content: t('templates.plan.content')
    }
  } as const;
}

export default function CreateJournalEntryDialog({ 
  patientId, 
  isOpen, 
  onClose, 
  onSuccess 
}: CreateJournalEntryDialogProps) {
  const t = useTranslations('journal');
  const locale = useLocale();
  const [selectedType, setSelectedType] = useState<JournalEntryType>(JournalEntryType.NOTE);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGenerationDialog, setShowGenerationDialog] = useState(false);
  const ENTRY_TYPE_OPTIONS = useEntryTypeOptions();
  const TEMPLATES = getTemplates(t);

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
      logError('Create Journal Entry Dialog: Failed to create journal entry', err);
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
              {t('create.header.title')}
              <Badge variant="secondary" className="ml-2 text-xs flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                {t('create.header.badgeAI')}
              </Badge>
            </DialogTitle>
            <DialogDescription className="text-gray-600">
              {t('create.header.description')}
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
                    {t('create.selectTypeLabel')}
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
                    {t('create.buttons.generateAI')}
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
                      {t('create.selectedPrefix', { label: selectedOption.label })}
                    </Badge>
                  </div>
                )}
              </div>

              {/* Title */}
              <div className="space-y-2">
                <Label htmlFor="title" className="text-sm font-medium text-gray-900">
                  {t('create.field.title')}
                </Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t('create.field.titlePlaceholder')}
                  disabled={isSubmitting}
                  required
                  className="font-medium"
                />
              </div>

              {/* Content with Autocomplete */}
              <div className="space-y-2">
                <Label htmlFor="content" className="text-sm font-medium text-gray-900">
                  {t('create.field.content')}
                </Label>
                <TextareaAutocomplete
                  id="content"
                  value={content}
                  onChange={setContent}
                  entryType={selectedType}
                  rows={16}
                  placeholder={t('create.field.contentPlaceholder')}
                  disabled={isSubmitting}
                  required
                />
                <p className="text-xs text-gray-500 flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  {t('create.field.templateTip')}
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
                  {t('create.buttons.cancel')}
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !title.trim() || !content.trim()}
                  className="min-w-[120px]"
                >
                  {isSubmitting ? (
                    <>
                      <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                      {t('create.buttons.creating')}
                    </>
                  ) : (
                    <>
                      <Save className="h-4 w-4 mr-2" />
                      {t('create.buttons.create')}
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
