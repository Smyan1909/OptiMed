"use client";

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { FileText, ExternalLink, Copy, Check, AlertCircle } from 'lucide-react';
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
    if (citation && citation.excerpt) {
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

  // Check if this is a placeholder citation (missing data)
  const isMissingData = !citation.document || !citation.excerpt;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <FileText className={`h-5 w-5 ${isMissingData ? 'text-gray-500' : 'text-blue-600'}`} />
            Citation [{citation.id}]
          </DialogTitle>
          <DialogDescription>
            {isMissingData ? 'Citation source data not available' : 'Source information for this clinical data'}
          </DialogDescription>
        </DialogHeader>

        {isMissingData ? (
          // Show message when citation data is missing
          <div className="space-y-4 py-4">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-semibold text-yellow-900 mb-1">Citation Data Unavailable</h4>
                  <p className="text-sm text-yellow-800">
                    This citation reference [{citation.id}] appears in the text, but the source document
                    information was not included in the response. This may occur when:
                  </p>
                  <ul className="list-disc list-inside text-sm text-yellow-800 mt-2 space-y-1">
                    <li>The citation was generated but source tracking failed</li>
                    <li>The source document is no longer available</li>
                    <li>There was an error retrieving the citation metadata</li>
                  </ul>
                  <p className="text-sm text-yellow-800 mt-3">
                    <strong>Recommendation:</strong> Please verify this information independently in the patient's
                    EHR record before making clinical decisions.
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          // Show normal citation data
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
        )}

        {/* Footer Note */}
        <div className={`text-xs text-gray-500 ${isMissingData ? 'bg-yellow-50 border-yellow-100' : 'bg-blue-50 border-blue-100'} px-3 py-2 rounded border`}>
          <strong>Note:</strong> {isMissingData
            ? 'This citation reference could not be fully resolved. Always verify clinical information independently.'
            : 'This citation shows the source of clinical information used in the response. Always verify important clinical details in the original EHR record.'}
        </div>
      </DialogContent>
    </Dialog>
  );
};
