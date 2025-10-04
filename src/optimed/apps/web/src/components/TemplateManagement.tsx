'use client';

import { useState, useEffect, useCallback } from 'react';
import { useUser } from '@/contexts/UserContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  NoteTemplate,
  listNoteTemplates,
  uploadNoteTemplate,
  deleteNoteTemplate
} from '@/lib/api';

export function TemplateManagement() {
  const { user } = useUser();
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<NoteTemplate | null>(null);
  const [filterLanguage, setFilterLanguage] = useState<string>('all');
  const [filterType, setFilterType] = useState<string>('all');

  // Upload form state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadLanguage, setUploadLanguage] = useState('en');
  const [uploadType, setUploadType] = useState('custom');
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const fetchTemplates = useCallback(async () => {
    if (!user) return;

    try {
      setLoading(true);
      setError(null);

      const data = await listNoteTemplates(
        true,
        filterLanguage !== 'all' ? (filterLanguage as 'en' | 'sv') : undefined,
        filterType !== 'all' ? filterType : undefined
      );

      setTemplates(data.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    } finally {
      setLoading(false);
    }
  }, [user, filterLanguage, filterType]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (isValidFileType(file)) {
        setUploadFile(file);
        if (!uploadName) {
          setUploadName(file.name.replace(/\.[^/.]+$/, ''));
        }
      }
    }
  };

  const isValidFileType = (file: File): boolean => {
    const validTypes = [
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', // .xlsx
      'text/plain',
    ];
    return validTypes.includes(file.type);
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadName || !user) return;

    try {
      setUploading(true);
      setError(null);

      await uploadNoteTemplate(
        uploadFile,
        uploadName,
        uploadLanguage as 'en' | 'sv',
        uploadType
      );

      // Reset form and close dialog
      setUploadFile(null);
      setUploadName('');
      setUploadLanguage('en');
      setUploadType('custom');
      setUploadDialogOpen(false);

      // Refresh templates
      await fetchTemplates();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload template');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedTemplate || !user) return;

    try {
      setError(null);

      await deleteNoteTemplate(selectedTemplate.template_id);

      setDeleteDialogOpen(false);
      setSelectedTemplate(null);
      await fetchTemplates();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete template');
    }
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

  if (loading && templates.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
          <p className="text-gray-600">Loading templates...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <Alert className="bg-red-50 border-red-200">
          <AlertDescription className="text-red-800">{error}</AlertDescription>
        </Alert>
      )}

      {/* Header with filters */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Note Templates</h3>
          <p className="text-sm text-gray-500 mt-1">
            Manage templates for clinical note generation
          </p>
        </div>

        <Button onClick={() => setUploadDialogOpen(true)} className="bg-blue-600 hover:bg-blue-700">
          + Upload Template
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-4">
        <div>
          <Label className="text-sm text-gray-700">Language</Label>
          <Select value={filterLanguage} onValueChange={setFilterLanguage}>
            <SelectTrigger className="w-[140px] bg-white opacity-100 border-gray-300">
              <SelectValue placeholder="All Languages" />
            </SelectTrigger>
            <SelectContent className="bg-white opacity-100">
              <SelectItem value="all">All Languages</SelectItem>
              <SelectItem value="en">EN - English</SelectItem>
              <SelectItem value="sv">SV - Swedish</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="text-sm text-gray-700">Type</Label>
          <Select value={filterType} onValueChange={setFilterType}>
            <SelectTrigger className="w-[180px] bg-white opacity-100 border-gray-300">
              <SelectValue placeholder="All Types" />
            </SelectTrigger>
            <SelectContent className="bg-white opacity-100">
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="journal_entry">Journal Entry</SelectItem>
              <SelectItem value="referral">Referral</SelectItem>
              <SelectItem value="soap">SOAP Note</SelectItem>
              <SelectItem value="progress_note">Progress Note</SelectItem>
              <SelectItem value="sbar">SBAR</SelectItem>
              <SelectItem value="consultation">Consultation</SelectItem>
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Templates Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {templates.map((template) => (
          <Card key={template.template_id} className="hover:shadow-md transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{getTemplateIcon(template.template_type)}</span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <Badge className={`text-xs font-semibold ${getLanguageColor(template.language)}`}>
                        {getLanguageBadge(template.language)}
                      </Badge>
                      <CardTitle className="text-base">
                        {template.name}
                      </CardTitle>
                    </div>
                    <CardDescription className="text-xs mt-1">
                      {template.file_format.toUpperCase()}
                    </CardDescription>
                  </div>
                </div>
                {template.is_system_template && (
                  <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200">
                    System
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex justify-between items-center">
                <span className="text-xs text-gray-500">
                  {new Date(template.created_at).toLocaleDateString()}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSelectedTemplate(template);
                      setViewDialogOpen(true);
                    }}
                    className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                  >
                    View
                  </Button>
                  {!template.is_system_template && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSelectedTemplate(template);
                        setDeleteDialogOpen(true);
                      }}
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    >
                      Delete
                    </Button>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {templates.length === 0 && (
        <div className="text-center py-12">
          <p className="text-gray-500">No templates found</p>
          <Button onClick={() => setUploadDialogOpen(true)} className="mt-4">
            Upload Your First Template
          </Button>
        </div>
      )}

      {/* Upload Dialog */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Upload Template</DialogTitle>
            <DialogDescription>
              Upload a DOCX, PDF, XLSX, or TXT file as a note template
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* File Upload Area */}
            <div
              className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                dragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300'
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              {uploadFile ? (
                <div className="space-y-2">
                  <p className="text-sm font-medium text-gray-900">{uploadFile.name}</p>
                  <p className="text-xs text-gray-500">
                    {(uploadFile.size / 1024).toFixed(2)} KB
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setUploadFile(null)}
                    className="text-red-600"
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-sm text-gray-600">
                    Drag and drop a file here, or click to select
                  </p>
                  <Input
                    type="file"
                    accept=".docx,.pdf,.xlsx,.txt"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file && isValidFileType(file)) {
                        setUploadFile(file);
                        if (!uploadName) {
                          setUploadName(file.name.replace(/\.[^/.]+$/, ''));
                        }
                      }
                    }}
                    className="hidden"
                    id="file-upload"
                  />
                  <Label htmlFor="file-upload" className="cursor-pointer text-blue-600 hover:text-blue-700">
                    Select File
                  </Label>
                </div>
              )}
            </div>

            {/* Template Name */}
            <div>
              <Label htmlFor="template-name">Template Name</Label>
              <Input
                id="template-name"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder="e.g., My Custom SOAP Note"
              />
            </div>

            {/* Language */}
            <div>
              <Label htmlFor="template-language">Language</Label>
              <Select value={uploadLanguage} onValueChange={setUploadLanguage}>
                <SelectTrigger id="template-language" className="bg-white opacity-100 border-gray-300">
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent className="bg-white opacity-100">
                  <SelectItem value="en">EN - English</SelectItem>
                  <SelectItem value="sv">SV - Swedish</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Template Type */}
            <div>
              <Label htmlFor="template-type">Template Type</Label>
              <Select value={uploadType} onValueChange={setUploadType}>
                <SelectTrigger id="template-type" className="bg-white opacity-100 border-gray-300">
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent className="bg-white opacity-100">
                  <SelectItem value="journal_entry">📝 Journal Entry</SelectItem>
                  <SelectItem value="referral">📋 Referral</SelectItem>
                  <SelectItem value="soap">🩺 SOAP Note</SelectItem>
                  <SelectItem value="progress_note">📊 Progress Note</SelectItem>
                  <SelectItem value="sbar">📢 SBAR</SelectItem>
                  <SelectItem value="consultation">👨‍⚕️ Consultation</SelectItem>
                  <SelectItem value="custom">📄 Custom</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setUploadDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleUpload}
              disabled={!uploadFile || !uploadName || uploading}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* View Template Dialog */}
      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent className="sm:max-w-[600px] max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span className="text-2xl">{getTemplateIcon(selectedTemplate?.template_type || 'custom')}</span>
              <div>
                <div className="flex items-center gap-2">
                  <Badge className={`text-xs font-semibold ${getLanguageColor(selectedTemplate?.language || 'en')}`}>
                    {getLanguageBadge(selectedTemplate?.language || 'en')}
                  </Badge>
                  <span>{selectedTemplate?.name}</span>
                </div>
              </div>
            </DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-1">
                <span className="text-sm text-gray-600">
                  <span className="font-medium">Type:</span> {selectedTemplate?.template_type}, {' '}
                  <span className="font-medium">Format:</span> {selectedTemplate?.file_format.toUpperCase()}, {' '}
                  <span className="font-medium">Created:</span> {selectedTemplate ? new Date(selectedTemplate.created_at).toLocaleDateString() : ''}
                </span>
              </div>
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <h4 className="text-sm font-semibold text-gray-900 mb-3">Template Fields</h4>
            {selectedTemplate?.template_structure?.fields && selectedTemplate.template_structure.fields.length > 0 ? (
              <div className="space-y-3">
                {selectedTemplate.template_structure.fields.map((field: any, index: number) => (
                  <div key={index} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium text-gray-900">{field.label || field.name}</span>
                          <Badge variant="outline" className="text-xs">
                            {field.type || 'text'}
                          </Badge>
                        </div>
                        <div className="text-xs text-gray-600 font-mono bg-white px-2 py-1 rounded border border-gray-200">
                          {field.name}
                        </div>
                        {field.description && (
                          <p className="text-xs text-gray-500 mt-2">{field.description}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                <p>No fields defined in this template</p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setViewDialogOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Template</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{selectedTemplate?.name}"? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleDelete}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}