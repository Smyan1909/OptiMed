"use client";

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { FileText, ExternalLink, Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface Citation {
  id: string;
  document: string;
  page?: string | null;
  excerpt: string;
  url?: string | null;
}

interface CitationModalProps {
  citation: Citation | null;
  isOpen: boolean;
  onClose: () => void;
}

export const CitationModal: React.FC<CitationModalProps> = ({
  citation,
  isOpen,
  onClose,
}) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = () => {
    if (citation) {
      navigator.clipboard.writeText(citation.excerpt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleOpenEHR = () => {
    if (citation?.url) {
      window.open(citation.url, '_blank', 'noopener,noreferrer');
    }
  };

  if (!citation) {
    return null;
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <FileText className="h-5 w-5 text-blue-600" />
            Citation [{citation.id}]
          </DialogTitle>
          <DialogDescription>
            Source information for this clinical data
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Document Name */}
          <div>
            <div className="text-sm font-medium text-gray-700 mb-1">Document</div>
            <div className="text-base text-gray-900 bg-gray-50 px-3 py-2 rounded border border-gray-200">
              {citation.document}
            </div>
          </div>

          {/* Page Number (if available) */}
          {citation.page && (
            <div>
              <div className="text-sm font-medium text-gray-700 mb-1">Page/Section</div>
              <div className="text-base text-gray-900 bg-gray-50 px-3 py-2 rounded border border-gray-200">
                {citation.page}
              </div>
            </div>
          )}

          {/* Full Content */}
          <div>
            <div className="text-sm font-medium text-gray-700 mb-1">Source Content</div>
            <div className="text-sm text-gray-900 bg-gray-50 px-4 py-3 rounded border border-gray-200 leading-relaxed max-h-96 overflow-y-auto whitespace-pre-wrap">
              {citation.excerpt}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              className="flex items-center gap-2"
            >
              {copied ? (
                <>
                  <Check className="h-4 w-4 text-green-600" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  Copy Excerpt
                </>
              )}
            </Button>

            {citation.url && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleOpenEHR}
                className="flex items-center gap-2"
              >
                <ExternalLink className="h-4 w-4" />
                Open in EHR
              </Button>
            )}
          </div>
        </div>

        {/* Footer Note */}
        <div className="text-xs text-gray-500 bg-blue-50 px-3 py-2 rounded border border-blue-100">
          <strong>Note:</strong> This citation shows the source of clinical information used in the response.
          Always verify important clinical details in the original EHR record.
        </div>
      </DialogContent>
    </Dialog>
  );
};
