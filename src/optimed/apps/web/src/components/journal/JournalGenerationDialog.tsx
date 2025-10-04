'use client';

import { useState } from 'react';
import { useLocale, useTranslations, useMessages } from 'next-intl';
import { JournalEntryType, generateJournalEntry } from '@/lib/api';
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
  const locale = useLocale();
  const t = useTranslations('journal');
  const messages = useMessages() as any;

  const getEntryTypeLabel = (type: JournalEntryType): string => t(`types.${type.toLowerCase()}` as any);

  const getPromptExamples = (type: JournalEntryType): string[] => {
    const root = messages?.journal?.generation?.examples?.[type.toLowerCase()];
    if (!root || typeof root !== 'object') return [];
    return Object.keys(root)
      .sort((a, b) => {
        const na = parseInt(a.replace(/\D/g, '')) || 0;
        const nb = parseInt(b.replace(/\D/g, '')) || 0;
        return na - nb;
      })
      .map((k) => String(root[k]))
      .filter(Boolean);
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      setError(t('generation.error.required'));
      return;
    }

    setIsGenerating(true);
    setError(null);

    try {
      const response = await generateJournalEntry({
        prompt: prompt.trim(),
        entry_type: entryType,
        patient_id: patientId,
        language: locale
      });

      onGenerate(response.title, response.content);
      setPrompt('');
      onClose();
    } catch (err) {
      logError('Journal Generation Dialog: Failed to generate journal entry', err);
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
            {t('generation.header.title')}
            <Badge variant="secondary" className="ml-2 text-xs">
              {t('generation.header.badgeAI')}
            </Badge>
          </DialogTitle>
            <DialogDescription className="text-gray-600">
              {t('generation.header.description', { type: getEntryTypeLabel(entryType).toLowerCase() })}
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
              <span className="font-medium text-blue-900">{t('generation.generating', { type: getEntryTypeLabel(entryType) })}</span>
            </div>
            <p className="text-sm text-blue-700">
              {t('generation.guidance', { type: getEntryTypeLabel(entryType).toLowerCase() })}
            </p>
          </div>

          {/* Prompt Input */}
          <div className="space-y-2">
            <Label htmlFor="prompt" className="text-sm font-medium text-gray-900">
              {t('generation.prompt.label')}
            </Label>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={t('generation.prompt.placeholder', { type: getEntryTypeLabel(entryType).toLowerCase() })}
              rows={6}
              disabled={isGenerating}
              className="resize-none"
            />
            <p className="text-xs text-gray-500">
              {t('generation.prompt.helper')}
            </p>
          </div>

          {/* Example Prompts */}
          {examples.length > 0 && (
            <div className="space-y-3">
              <Label className="text-sm font-medium text-gray-900">
                {t('generation.examples.label', { type: getEntryTypeLabel(entryType) })}
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
              {t('generation.buttons.cancel')}
            </Button>
            <Button
              onClick={handleGenerate}
              disabled={isGenerating || !prompt.trim()}
              className="min-w-[140px] bg-purple-600 hover:bg-purple-700"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t('generation.buttons.generating')}
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-2" />
                  {t('generation.buttons.generate')}
                </>
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}