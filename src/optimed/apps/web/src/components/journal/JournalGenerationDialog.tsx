'use client';

import { useState } from 'react';
import { JournalEntryType, generateJournalEntry } from '@/lib/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { 
  Sparkles,
  Send,
  X,
  FileText,
  Loader2
} from 'lucide-react';

interface JournalGenerationDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onGenerate: (title: string, content: string) => void;
  entryType: JournalEntryType;
  patientId?: string;
}

export default function JournalGenerationDialog({ 
  isOpen, 
  onClose, 
  onGenerate, 
  entryType, 
  patientId 
}: JournalGenerationDialogProps) {
  const [prompt, setPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getEntryTypeLabel = (type: JournalEntryType): string => {
    const labels = {
      [JournalEntryType.NOTE]: 'Progress Note',
      [JournalEntryType.OBSERVATION]: 'Clinical Observation',
      [JournalEntryType.TREATMENT]: 'Treatment Note',
      [JournalEntryType.DIAGNOSIS]: 'Diagnostic Assessment',
      [JournalEntryType.ASSESSMENT]: 'Clinical Assessment',
      [JournalEntryType.PLAN]: 'Care Plan'
    };
    return labels[type] || type;
  };

  const getPromptExamples = (type: JournalEntryType): string[] => {
    const examples = {
      [JournalEntryType.NOTE]: [
        "Patient reports improved pain levels after starting new medication",
        "Follow-up visit for diabetes management, blood sugars have been stable",
        "Post-operative day 3 following appendectomy, patient recovering well"
      ],
      [JournalEntryType.OBSERVATION]: [
        "Patient appears anxious during examination",
        "Notable improvement in mobility since last visit",
        "Unusual heart sounds detected during routine examination"
      ],
      [JournalEntryType.TREATMENT]: [
        "Administered IV antibiotics for suspected infection",
        "Physical therapy session focused on knee rehabilitation",
        "Changed wound dressing and assessed healing progress"
      ],
      [JournalEntryType.DIAGNOSIS]: [
        "Patient presents with chest pain and shortness of breath",
        "Evaluate patient for possible urinary tract infection",
        "Assessment of recurring headaches and visual disturbances"
      ],
      [JournalEntryType.ASSESSMENT]: [
        "Comprehensive evaluation of patient's overall health status",
        "Review of multiple chronic conditions and medication effectiveness",
        "Assessment of patient's mental health and coping strategies"
      ],
      [JournalEntryType.PLAN]: [
        "Develop discharge plan for elderly patient with multiple comorbidities",
        "Create long-term management plan for newly diagnosed diabetes",
        "Coordinate care team for complex medical case"
      ]
    };
    return examples[type] || [];
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      setError('Please enter a prompt to generate the journal entry');
      return;
    }

    setIsGenerating(true);
    setError(null);

    try {
      const response = await generateJournalEntry({
        prompt: prompt.trim(),
        entry_type: entryType,
        patient_id: patientId
      });

      onGenerate(response.title, response.content);
      setPrompt('');
      onClose();
    } catch (err) {
      console.error('Failed to generate journal entry:', err);
      setError(err instanceof Error ? err.message : 'Failed to generate journal entry');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleClose = () => {
    if (!isGenerating) {
      setPrompt('');
      setError(null);
      onClose();
    }
  };

  const handleExampleClick = (example: string) => {
    setPrompt(example);
  };

  const examples = getPromptExamples(entryType);

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader className="border-b border-gray-200 pb-4">
          <DialogTitle className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-purple-600" />
            Generate Journal Entry
            <Badge variant="secondary" className="ml-2 text-xs">
              AI Powered
            </Badge>
          </DialogTitle>
          <DialogDescription className="text-gray-600">
            Describe what you want to document and AI will generate a complete {getEntryTypeLabel(entryType).toLowerCase()} for you
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Error Display */}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Entry Type Info */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="h-4 w-4 text-blue-600" />
              <span className="font-medium text-blue-900">Generating: {getEntryTypeLabel(entryType)}</span>
            </div>
            <p className="text-sm text-blue-700">
              The AI will create a structured {getEntryTypeLabel(entryType).toLowerCase()} following medical documentation standards.
            </p>
          </div>

          {/* Prompt Input */}
          <div className="space-y-2">
            <Label htmlFor="prompt" className="text-sm font-medium text-gray-900">
              Describe what to document
            </Label>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={`Describe the clinical situation you want to document in this ${getEntryTypeLabel(entryType).toLowerCase()}...`}
              rows={6}
              disabled={isGenerating}
              className="resize-none"
            />
            <p className="text-xs text-gray-500">
              Be as specific as possible. Include patient symptoms, findings, treatments, or observations.
            </p>
          </div>

          {/* Example Prompts */}
          {examples.length > 0 && (
            <div className="space-y-3">
              <Label className="text-sm font-medium text-gray-900">
                Example prompts for {getEntryTypeLabel(entryType)}:
              </Label>
              <div className="space-y-2">
                {examples.map((example, index) => (
                  <button
                    key={index}
                    onClick={() => handleExampleClick(example)}
                    disabled={isGenerating}
                    className="w-full text-left p-3 text-sm bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <span className="text-gray-600">💡</span> {example}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <DialogFooter className="border-t border-gray-200 pt-4 bg-gray-50">
          <div className="flex items-center gap-3 w-full justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={isGenerating}
            >
              <X className="h-4 w-4 mr-2" />
              Cancel
            </Button>
            <Button
              onClick={handleGenerate}
              disabled={isGenerating || !prompt.trim()}
              className="min-w-[140px] bg-purple-600 hover:bg-purple-700"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-2" />
                  Generate Entry
                </>
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}