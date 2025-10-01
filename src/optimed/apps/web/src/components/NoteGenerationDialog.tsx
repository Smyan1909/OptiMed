'use client';

import { useState, useEffect } from 'react';
import { useUser } from '@/contexts/UserContext';
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

export function NoteGenerationDialog({
  open,
  onOpenChange,
  patientId,
  sessionId,
  onNoteGenerated,
  initialNote,
}: NoteGenerationDialogProps) {
  const { user } = useUser();
  const [step, setStep] = useState<'template' | 'context' | 'generating' | 'editing'>('template');
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<NoteTemplate | null>(null);
  const [contextPrompt, setContextPrompt] = useState('');
  const [generatedNote, setGeneratedNote] = useState('');
  const [editedNote, setEditedNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generationProgress, setGenerationProgress] = useState<string>('');
  const [filterLanguage, setFilterLanguage] = useState<string>('all');

  // Handle auto-generated note (from natural language prompt)
  useEffect(() => {
    if (open && initialNote) {
      console.log('📝 Auto-generated note detected, skipping to editing step');
      setGeneratedNote(initialNote);
      setEditedNote(initialNote);
      setStep('editing');
    }
  }, [open, initialNote]);

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
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    } finally {
      setLoading(false);
    }
  };

  const generateNote = async () => {
    if (!user || !selectedTemplate) return;

    try {
      setStep('generating');
      setLoading(true);
      setError(null);
      setGenerationProgress('Starting note generation...');

      const request: NoteGenerationRequest = {
        template_id: selectedTemplate.template_id,
        patient_id: patientId,
        session_id: sessionId,
        context_prompt: contextPrompt || undefined,
      };

      await generateNoteStreaming(
        request,
        (progressEvent) => {
          setGenerationProgress(progressEvent.message || 'Generating...');
        },
        (finalNote) => {
          setGeneratedNote(finalNote);
          setEditedNote(finalNote);
          setGenerationProgress('Note generated successfully!');
          setStep('editing');
          setLoading(false);
        },
        (errorMessage) => {
          setError(errorMessage);
          setStep('context');
          setLoading(false);
        }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate note');
      setStep('context');
      setLoading(false);
    }
  };

  const handleCopyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(editedNote);
      if (onNoteGenerated) {
        onNoteGenerated(editedNote);
      }
      onOpenChange(false);
      resetDialog();
    } catch (err) {
      setError('Failed to copy to clipboard');
    }
  };

  const resetDialog = () => {
    setStep('template');
    setSelectedTemplate(null);
    setContextPrompt('');
    setGeneratedNote('');
    setEditedNote('');
    setError(null);
    setGenerationProgress('');
    setFilterLanguage('all');
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
          <DialogTitle>Generate Clinical Note</DialogTitle>
          <DialogDescription>
            {step === 'template' && 'Select a template for your note'}
            {step === 'context' && 'Add context for note generation'}
            {step === 'generating' && 'Generating your note...'}
            {step === 'editing' && 'Review and edit your note'}
          </DialogDescription>
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
              <Label>Filter by Language</Label>
              <Select value={filterLanguage} onValueChange={setFilterLanguage}>
                <SelectTrigger className="bg-white opacity-100 border-gray-300">
                  <SelectValue placeholder="All Languages" />
                </SelectTrigger>
                <SelectContent className="bg-white opacity-100">
                  <SelectItem value="all">All Languages</SelectItem>
                  <SelectItem value="en">EN - English</SelectItem>
                  <SelectItem value="sv">SV - Swedish</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-1 gap-3 max-h-[400px] overflow-y-auto">
              {loading ? (
                <div className="text-center py-8">
                  <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                  <p className="text-gray-600">Loading templates...</p>
                </div>
              ) : templates.length === 0 ? (
                <p className="text-center text-gray-500 py-8">No templates available</p>
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
                Cancel
              </Button>
              <Button
                onClick={() => setStep('context')}
                disabled={!selectedTemplate}
                className="bg-blue-600 hover:bg-blue-700"
              >
                Next
              </Button>
            </div>
          </div>
        )}

        {/* Step 2: Context Input */}
        {step === 'context' && (
          <div className="space-y-4 py-4">
            <div>
              <Label>Selected Template</Label>
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
                Context Prompt (Optional)
              </Label>
              <p className="text-xs text-gray-500 mb-2">
                Add specific context or instructions for note generation
              </p>
              <Textarea
                id="context-prompt"
                value={contextPrompt}
                onChange={(e) => setContextPrompt(e.target.value)}
                placeholder="e.g., Focus on cardiovascular findings, Include medication changes, Emphasize patient's main concerns..."
                rows={5}
                className="resize-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button variant="outline" onClick={() => setStep('template')}>
                Back
              </Button>
              <Button
                onClick={generateNote}
                className="bg-blue-600 hover:bg-blue-700"
              >
                Generate Note
              </Button>
            </div>
          </div>
        )}

        {/* Step 3: Generating */}
        {step === 'generating' && (
          <div className="space-y-4 py-8">
            <div className="text-center">
              <div className="animate-spin h-12 w-12 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
              <p className="text-gray-900 font-medium mb-2">Generating your note...</p>
              <p className="text-sm text-gray-600">{generationProgress}</p>
            </div>
          </div>
        )}

        {/* Step 4: Editing */}
        {step === 'editing' && (
          <div className="space-y-4 py-4">
            <div>
              <Label>Review and Edit Note</Label>
              <p className="text-xs text-gray-500 mb-2">
                Switch between Edit and Preview modes
              </p>

              <Tabs defaultValue="edit" className="w-full">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="edit">Edit</TabsTrigger>
                  <TabsTrigger value="preview">Preview</TabsTrigger>
                </TabsList>

                <TabsContent value="edit" className="mt-4">
                  <Textarea
                    id="note-editor"
                    value={editedNote}
                    onChange={(e) => setEditedNote(e.target.value)}
                    rows={15}
                    className="resize-none font-mono text-sm"
                  />
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
                      {editedNote}
                    </ReactMarkdown>
                  </div>
                </TabsContent>
              </Tabs>
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button variant="outline" onClick={() => {
                setStep('context');
                setGeneratedNote('');
                setEditedNote('');
              }}>
                Regenerate
              </Button>
              <Button
                onClick={handleCopyToClipboard}
                className="bg-blue-600 hover:bg-blue-700"
              >
                Copy to Clipboard
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}