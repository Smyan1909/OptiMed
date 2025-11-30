'use client';

import { useState, useEffect } from 'react';
import { useUser } from '@/contexts/UserContext';
import { logInfo } from '@/lib/logger';
import { useTranslations, useLocale } from 'next-intl';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import {
  NoteTemplate,
  listNoteTemplates,
  generateNoteStreaming,
  NoteGenerationRequest
} from '@/lib/api';

interface NoteGenerationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  patientId?: string;
  sessionId: string;
  onNoteGenerated?: (noteContent: string) => void;
  initialNote?: string | null;
}

interface NoteSection {
  header: string;
  content: string;
}

export function NoteGenerationDialog({
  open,
  onOpenChange,
  patientId,
  sessionId,
  onNoteGenerated,
  initialNote,
}: NoteGenerationDialogProps) {
  const { user } = useUser();
  const locale = useLocale();
  const t = useTranslations('noteGeneration');
  const [step, setStep] = useState<'template' | 'context' | 'generating' | 'editing' | 'regenerating'>('template');
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<NoteTemplate | null>(null);
  const [contextPrompt, setContextPrompt] = useState('');
  const [regeneratePrompt, setRegeneratePrompt] = useState('');
  const [generatedNote, setGeneratedNote] = useState('');
  const [noteSections, setNoteSections] = useState<NoteSection[]>([]);
  const [noteMainTitle, setNoteMainTitle] = useState<string>('');  // Main title (# Title) if present
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generationProgress, setGenerationProgress] = useState<string>('');
  const [filterLanguage, setFilterLanguage] = useState<string>('all');
  const [copiedSectionIndex, setCopiedSectionIndex] = useState<number | null>(null);

  // Parse markdown note into sections
  const parseNoteIntoSections = (note: string): { sections: NoteSection[]; mainTitle: string } => {
    if (!note) return { sections: [], mainTitle: '' };
    
    // Extract main title (# Title) if present - we don't want to show it as an editable section
    let noteContent = note;
    let mainTitle = '';
    const mainTitleMatch = noteContent.match(/^#\s+(.+)$/m);
    if (mainTitleMatch) {
      mainTitle = mainTitleMatch[1].trim();
      // Remove the main title line and any following blank lines
      noteContent = noteContent.replace(/^#\s+.+$/m, '').replace(/^\n+/, '');
    }
    
    // Split by markdown headers (##)
    const headerRegex = /^##\s+(.+)$/gm;
    const sections: NoteSection[] = [];
    let lastIndex = 0;
    let match;
    
    // Find all headers
    const headers: Array<{ index: number; header: string }> = [];
    while ((match = headerRegex.exec(noteContent)) !== null) {
      headers.push({ index: match.index, header: match[1].trim() });
    }
    
    // Extract sections
    if (headers.length === 0) {
      // No headers found, treat entire note as one section
      sections.push({ header: '', content: noteContent.trim() });
    } else {
      // Extract content between headers
      for (let i = 0; i < headers.length; i++) {
        const startIndex = headers[i].index;
        const endIndex = i < headers.length - 1 ? headers[i + 1].index : noteContent.length;
        
        // Extract header
        const headerMatch = noteContent.substring(startIndex).match(/^##\s+(.+)$/m);
        const header = headerMatch ? headerMatch[1].trim() : '';
        
        // Extract content (skip the header line itself)
        const contentStart = noteContent.indexOf('\n', startIndex) + 1;
        const content = noteContent.substring(contentStart, endIndex).trim();
        
        sections.push({ header, content });
      }
    }
    
    return { sections, mainTitle };
  };

  // Reconstruct note from sections (with main title if it exists)
  const reconstructNoteFromSections = (sections: NoteSection[], mainTitle?: string): string => {
    const sectionsText = sections
      .map(section => {
        if (section.header) {
          return `## ${section.header}\n${section.content}`;
        }
        return section.content;
      })
      .join('\n\n');
    
    // Add main title back if it exists
    if (mainTitle) {
      return `# ${mainTitle}\n\n${sectionsText}`;
    }
    
    return sectionsText;
  };

  // Handle auto-generated note (from natural language prompt)
  useEffect(() => {
    if (open && initialNote) {
      logInfo('Note Generation Dialog: Auto-generated note detected, skipping to editing step');
      setGeneratedNote(initialNote);
      const { sections, mainTitle } = parseNoteIntoSections(initialNote);
      setNoteSections(sections);
      setNoteMainTitle(mainTitle);
      setStep('editing');
    }
  }, [open, initialNote]);

  // Update sections when generated note changes
  useEffect(() => {
    if (generatedNote && step === 'editing') {
      const { sections, mainTitle } = parseNoteIntoSections(generatedNote);
      setNoteSections(sections);
      setNoteMainTitle(mainTitle);
    }
  }, [generatedNote, step]);

  useEffect(() => {
    if (open && step === 'template') {
      fetchTemplates();
    }
  }, [open, step, filterLanguage]);

  const fetchTemplates = async () => {
    if (!user) return;

    try {
      setLoading(true);
      const data = await listNoteTemplates(
        true,
        filterLanguage !== 'all' ? (filterLanguage as 'en' | 'sv') : undefined
      );

      setTemplates(data.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('noTemplates'));
    } finally {
      setLoading(false);
    }
  };

  const generateNote = async (isRegeneration = false) => {
    if (!user) return;
    
    // For regeneration, template is optional (works for referrals/certificates)
    // For new generation, template is required
    if (!isRegeneration && !selectedTemplate) return;

    try {
      setStep(isRegeneration ? 'regenerating' : 'generating');
      setLoading(true);
      setError(null);
      setGenerationProgress(isRegeneration ? t('regenerateNote') : t('generateNote'));

      // For regeneration, pass existing note content separately
      // Use the current edited note (reconstructed from sections with main title)
      const existingNote = isRegeneration && (generatedNote || noteSections.length > 0)
        ? reconstructNoteFromSections(noteSections, noteMainTitle)  // Use current edited version
        : undefined;

      const request: NoteGenerationRequest = {
        template_id: selectedTemplate?.template_id,  // Optional for regeneration
        patient_id: patientId,
        session_id: sessionId,
        context_prompt: isRegeneration ? regeneratePrompt : (contextPrompt || undefined),
        existing_note_content: existingNote,
      };

      await generateNoteStreaming(
        request,
        (progressEvent) => {
          setGenerationProgress(progressEvent.message || (isRegeneration ? t('regenerateNote') : t('generateNote')));
        },
        (finalNote) => {
          setGeneratedNote(finalNote);
          const { sections, mainTitle } = parseNoteIntoSections(finalNote);
          setNoteSections(sections);
          setNoteMainTitle(mainTitle);
          setGenerationProgress(isRegeneration ? t('regenerateNote') : t('generateNote'));
          setStep('editing');
          setLoading(false);
          setRegeneratePrompt(''); // Clear regenerate prompt after successful regeneration
        },
        (errorMessage) => {
          setError(errorMessage);
          setStep(isRegeneration ? 'editing' : 'context');
          setLoading(false);
        }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : (isRegeneration ? t('regenerateNote') : t('generateNote')));
      setStep(isRegeneration ? 'editing' : 'context');
      setLoading(false);
    }
  };

  const handleCopyToClipboard = async () => {
    try {
      const fullNote = reconstructNoteFromSections(noteSections, noteMainTitle);
      await navigator.clipboard.writeText(fullNote);
      if (onNoteGenerated) {
        onNoteGenerated(fullNote);
      }
      onOpenChange(false);
      resetDialog();
    } catch (err) {
      setError('Failed to copy to clipboard');
    }
  };

  const handleCopySection = async (index: number) => {
    try {
      const section = noteSections[index];
      const sectionText = section.header ? `## ${section.header}\n${section.content}` : section.content;
      await navigator.clipboard.writeText(sectionText);
      setCopiedSectionIndex(index);
      setTimeout(() => setCopiedSectionIndex(null), 2000);
    } catch (err) {
      setError('Failed to copy section');
    }
  };

  const handleSectionContentChange = (index: number, content: string) => {
    const updatedSections = [...noteSections];
    updatedSections[index].content = content;
    setNoteSections(updatedSections);
  };

  const resetDialog = () => {
    setStep('template');
    setSelectedTemplate(null);
    setContextPrompt('');
    setRegeneratePrompt('');
    setGeneratedNote('');
    setNoteSections([]);
    setNoteMainTitle('');
    setError(null);
    setGenerationProgress('');
    setFilterLanguage('all');
    setCopiedSectionIndex(null);
  };

  const getTemplateIcon = (type: string) => {
    const icons: Record<string, string> = {
      journal_entry: '📝',
      referral: '📋',
      soap: '🩺',
      progress_note: '📊',
      sbar: '📢',
      consultation: '👨‍⚕️',
      custom: '📄',
      medical_certificate: '🏥',
    };
    return icons[type] || '📄';
  };

  const getLanguageBadge = (lang: string) => {
    return lang === 'sv' ? 'SV' : 'EN';
  };

  const getLanguageColor = (lang: string) => {
    return lang === 'sv' ? 'bg-blue-100 text-blue-700 border-blue-300' : 'bg-green-100 text-green-700 border-green-300';
  };

  return (
    <Dialog open={open} onOpenChange={(newOpen) => {
      onOpenChange(newOpen);
      if (!newOpen) resetDialog();
    }}>
      <DialogContent className="sm:max-w-[700px] max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          {step !== 'editing' && (
            <DialogDescription>
              {step === 'template' && t('steps.template')}
              {step === 'context' && t('steps.context')}
              {(step === 'generating' || step === 'regenerating') && t('steps.generating')}
            </DialogDescription>
          )}
        </DialogHeader>

        {error && (
          <Alert className="bg-red-50 border-red-200">
            <AlertDescription className="text-red-800">{error}</AlertDescription>
          </Alert>
        )}

        {/* Step 1: Template Selection */}
        {step === 'template' && (
          <div className="space-y-4 py-4">
            <div>
              <Label>{t('filterLanguage')}</Label>
              <Select value={filterLanguage} onValueChange={setFilterLanguage}>
                <SelectTrigger className="bg-white opacity-100 border-gray-300">
                  <SelectValue placeholder={t('allLanguages')} />
                </SelectTrigger>
                <SelectContent className="bg-white opacity-100">
                  <SelectItem value="all">{t('allLanguages')}</SelectItem>
                  <SelectItem value="en">EN - English</SelectItem>
                  <SelectItem value="sv">SV - Swedish</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-1 gap-3 max-h-[400px] overflow-y-auto">
              {loading ? (
                <div className="text-center py-8">
                  <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                  <p className="text-gray-600">{t('loadingTemplates')}</p>
                </div>
              ) : templates.length === 0 ? (
                <p className="text-center text-gray-500 py-8">{t('noTemplates')}</p>
              ) : (
                templates.map((template) => (
                  <Card
                    key={template.template_id}
                    className={`cursor-pointer transition-all ${
                      selectedTemplate?.template_id === template.template_id
                        ? 'border-blue-500 bg-blue-50'
                        : 'hover:border-gray-400'
                    }`}
                    onClick={() => setSelectedTemplate(template)}
                  >
                    <CardHeader className="py-3 px-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className="text-2xl">{getTemplateIcon(template.template_type)}</span>
                          <div>
                            <div className="flex items-center gap-2">
                              <Badge className={`text-xs font-semibold ${getLanguageColor(template.language)}`}>
                                {getLanguageBadge(template.language)}
                              </Badge>
                              <CardTitle className="text-sm">
                                {template.name}
                              </CardTitle>
                            </div>
                            <CardDescription className="text-xs mt-1">
                              {template.template_type.replace('_', ' ')}
                            </CardDescription>
                          </div>
                        </div>
                        {template.is_system_template && (
                          <Badge variant="outline" className="text-xs">System</Badge>
                        )}
                      </div>
                    </CardHeader>
                  </Card>
                ))
              )}
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t('cancel')}
              </Button>
              <Button
                onClick={() => setStep('context')}
                disabled={!selectedTemplate}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {t('next')}
              </Button>
            </div>
          </div>
        )}

        {/* Step 2: Context Input */}
        {step === 'context' && (
          <div className="space-y-4 py-4">
            <div>
              <Label>{t('selectedTemplate')}</Label>
              <Card className="mt-2">
                <CardContent className="py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{getTemplateIcon(selectedTemplate!.template_type)}</span>
                    <Badge className={`text-xs font-semibold ${getLanguageColor(selectedTemplate!.language)}`}>
                      {getLanguageBadge(selectedTemplate!.language)}
                    </Badge>
                    <span className="font-medium">
                      {selectedTemplate!.name}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div>
              <Label htmlFor="context-prompt">
                {t('contextPrompt')}
              </Label>
              <p className="text-xs text-gray-500 mb-2">
                {t('contextPromptDescription')}
              </p>
              <Textarea
                id="context-prompt"
                value={contextPrompt}
                onChange={(e) => setContextPrompt(e.target.value)}
                placeholder={t('contextPromptPlaceholder')}
                rows={5}
                className="resize-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button variant="outline" onClick={() => setStep('template')}>
                {t('back')}
              </Button>
              <Button
                onClick={() => generateNote(false)}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {t('generateNote')}
              </Button>
            </div>
          </div>
        )}

        {/* Step 3: Generating */}
        {(step === 'generating' || step === 'regenerating') && (
          <div className="space-y-4 py-8">
            <div className="text-center">
              <div className="animate-spin h-12 w-12 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
              <p className="text-gray-900 font-medium mb-2">
                {step === 'regenerating' ? t('regenerateNote') : t('generateNote')}
              </p>
              <p className="text-sm text-gray-600">{generationProgress}</p>
            </div>
          </div>
        )}

        {/* Step 4: Editing */}
        {step === 'editing' && (
          <div className="space-y-4 py-4">
            <div>
              <Label>{t('reviewAndEdit')}</Label>
              <p className="text-xs text-gray-500 mb-2">
                {t('reviewDescription')}
              </p>

              <Tabs defaultValue="edit" className="w-full">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="edit">{t('edit')}</TabsTrigger>
                  <TabsTrigger value="preview">{t('preview')}</TabsTrigger>
                </TabsList>

                <TabsContent value="edit" className="mt-4 space-y-4">
                  {noteSections.length === 0 ? (
                    <p className="text-center text-gray-500 py-8">{t('noSections')}</p>
                  ) : (
                    noteSections.map((section, index) => (
                      <div key={index} className="space-y-2">
                        <div className="flex items-center justify-between">
                          {section.header ? (
                            <Label className="text-base font-semibold text-gray-900">
                              {section.header}
                            </Label>
                          ) : (
                            <Label className="text-base font-semibold text-gray-900">
                              {t('noSections')}
                            </Label>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleCopySection(index)}
                            className="h-8 w-8 p-0"
                            title={t('copySection')}
                          >
                            {copiedSectionIndex === index ? (
                              <Check className="h-4 w-4 text-green-600" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </Button>
                        </div>
                        <Textarea
                          value={section.content}
                          onChange={(e) => handleSectionContentChange(index, e.target.value)}
                          rows={section.content.split('\n').length + 2}
                          className="resize-none font-mono text-sm"
                          placeholder={section.header ? `${section.header} content...` : 'Note content...'}
                        />
                      </div>
                    ))
                  )}
                </TabsContent>

                <TabsContent value="preview" className="mt-4">
                  <div className="border rounded-md p-4 max-h-[400px] overflow-y-auto bg-white">
                    <ReactMarkdown
                      components={{
                        h1: ({ node, ...props }) => <h1 className="text-2xl font-semibold text-gray-900 mb-4 pb-2 border-b" {...props} />,
                        h2: ({ node, ...props }) => <h2 className="text-xl font-semibold text-gray-900 mb-3 mt-6" {...props} />,
                        h3: ({ node, ...props }) => <h3 className="text-lg font-semibold text-gray-900 mb-2 mt-4" {...props} />,
                        p: ({ node, ...props }) => <p className="text-gray-700 mb-3 leading-relaxed" {...props} />,
                        ul: ({ node, ...props }) => <ul className="list-disc ml-6 mb-3 text-gray-700" {...props} />,
                        ol: ({ node, ...props }) => <ol className="list-decimal ml-6 mb-3 text-gray-700" {...props} />,
                        li: ({ node, ...props }) => <li className="mb-1" {...props} />,
                        strong: ({ node, ...props }) => <strong className="font-semibold text-gray-900" {...props} />,
                        em: ({ node, ...props }) => <em className="italic text-gray-700" {...props} />,
                        code: ({ node, ...props }) => <code className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono" {...props} />,
                        pre: ({ node, ...props }) => <pre className="bg-gray-100 p-3 rounded overflow-x-auto mb-3" {...props} />,
                        blockquote: ({ node, ...props }) => <blockquote className="border-l-4 border-blue-500 pl-4 italic text-gray-700 mb-3" {...props} />,
                      }}
                    >
                      {reconstructNoteFromSections(noteSections, noteMainTitle)}
                    </ReactMarkdown>
                  </div>
                </TabsContent>
              </Tabs>
            </div>

            {/* Regenerate prompt section - moved to bottom */}
            <div className="border rounded-lg p-4 bg-gray-50">
              <Label htmlFor="regenerate-prompt" className="text-sm font-semibold mb-2 block">
                {t('regenerate')}
              </Label>
              <p className="text-xs text-gray-500 mb-2">
                {t('regeneratePrompt')}
              </p>
              <Textarea
                id="regenerate-prompt"
                value={regeneratePrompt}
                onChange={(e) => setRegeneratePrompt(e.target.value)}
                placeholder={t('regeneratePlaceholder')}
                rows={3}
                className="resize-none mb-2"
              />
              <Button
                onClick={() => generateNote(true)}
                disabled={loading || !regeneratePrompt.trim() || noteSections.length === 0}
                variant="outline"
                size="sm"
                className="w-full"
              >
                {t('regenerateNote')}
              </Button>
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button
                onClick={handleCopyToClipboard}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {t('copyToClipboard')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
