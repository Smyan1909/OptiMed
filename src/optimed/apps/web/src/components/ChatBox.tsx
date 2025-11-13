"use client";

import { useState, useEffect, FormEvent, useRef, useCallback } from "react";
import { useUser } from '@/contexts/UserContext';
import { Download, Image as ImageIcon, ExternalLink, Paperclip, FileText, X, FileEdit } from 'lucide-react';
import { getGeneratedImageUrl, downloadGeneratedImage, lookupTerm, LookupResponse, uploadPDFDocument, listPDFDocuments, deletePDFDocument, PDFDocument, uploadXMLDocument, listXMLDocuments, deleteXMLDocument, XMLDocument, cleanupSessionDocuments } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MarkdownWithCitations } from './MarkdownWithCitations';
import { useStreamingChat } from "@/hooks/useStreamingChat";
import { StreamingProgress } from "./StreamingProgress";
import { ReasoningViewer } from "./ReasoningViewer";
import { DifferentialDiagnosisCards } from "./DifferentialDiagnosisCards";
import { SBARSummaryCards } from "./SBARSummaryCards";
import { GeneralSummaryCards } from "./GeneralSummaryCards";
import { FocusedSummaryCards } from "./FocusedSummaryCards";
import { TimelineView } from "./TimelineView";
import { NoteGenerationDialog } from "./NoteGenerationDialog";
import { VoiceRecorder } from "./VoiceRecorder";
import { LiveWaveform } from "./ui/live-waveform";
import { useLayoutEffect } from "react";
import ModeSelector from "./ModeSelector";
import { useTranslations, useLocale } from 'next-intl';
import { sanitizeUserId, sanitizePatientId, sanitizeSessionId, sanitizeDocumentId, logInfo, logError, logWarning } from '@/lib/logger';

export interface GeneratedImageInfo {
  image_generated: boolean;
  image_id?: string;
  image_prompt?: string;
  generation_metadata?: Record<string, any>;
  model_info?: Record<string, any>;
}

export interface ImageGenerationRequest {
  prompt: string;
  width?: number;
  height?: number;
  patient_id?: string;
}

export interface GeneratedImageResponse {
  success: boolean;
  image_id: string;
  prompt: string;
  created_at: string;
  metadata: Record<string, any>;
  model_info: Record<string, any>;
}

interface InfoRetrievalMode {
  id: string;
  name: string;
  description: string;
  default_prompt: string;
}

interface DifferentialDiagnosis {
  icd_code: string;
  diagnosis_name: string;
  confidence: number;
  reasoning: string;
  supporting_evidence: string[];
}

interface SBARResults {
  situation?: string;
  background?: string;
  assessment?: string;
  recommendation?: string;
}

interface TimelineEvent {
  timestamp: string;
  title: string;
  content: string;
  icon: string;
  color: string;
}

interface TimelineResults {
  events: TimelineEvent[];
}

interface EncountersData {
  content: string;
  structured_data: any[];
}

interface GeneralSummaryResults {
  snapshot?: string;
  problems?: string;
  medications?: string;
  trends?: string;
  history?: string;
  risks?: string;
  encounters?: string | EncountersData;
  deepdive?: string;
}

interface FocusedSummaryResults {
  diagnoses?: string;
  events?: string;
  medications?: string;
  objective_data?: string;
  assessment?: string;
  next_steps?: string;
}

interface Citation {
  id: string;
  document: string;
  page?: string | null;
  excerpt: string;
  url?: string | null;
}

interface Message {
  sender: "user" | "system";
  text: string;
  loading?: boolean;
  timestamp?: string;
  generatedImage?: GeneratedImageInfo;
  reasoningSteps?: string[];
  reasoning?: string;
  differentialDiagnoses?: DifferentialDiagnosis[];
  sbarResults?: SBARResults;
  generalSummaryResults?: GeneralSummaryResults;
  focusedSummaryResults?: FocusedSummaryResults;
  focusedAspect?: string;
  focusedAspectIcon?: string;
  timelineResults?: TimelineResults;
  citations?: Record<string, Citation>;
}

interface ChatBoxProps {
  mode: "chat" | "diagnose";
  patientId?: string;
  sessionId?: string | null;
}

function useAutosizeTextArea(textAreaRef: React.RefObject<HTMLTextAreaElement | null>, value: string, maxPx = 240) {
  useLayoutEffect(() => {
    const el = textAreaRef.current;
    if (!el) return;

    // reset to shrink when deleting text
    el.style.height = 'auto';

    // grow, but clamp to maxPx
    const newHeight = Math.min(el.scrollHeight + 2, maxPx); // +2 for border
    el.style.height = `${newHeight}px`;
  }, [textAreaRef, value, maxPx]);
}

// Small fixed overlay panel to show lookup results
function LookupPanel({ term, onClose, patientId, sessionId }: { term: string; onClose: () => void; patientId?: string; sessionId?: string | null }) {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LookupResponse | null>(null);
  const t = useTranslations('chatBox');
  const tCommon = useTranslations('common');

  useEffect(() => {
    let canceled = false;
    const run = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await lookupTerm({ term, patient_id: patientId, session_id: sessionId || undefined });
        if (!canceled) setResult(data);
      } catch (e: any) {
        if (!canceled) setError(e?.message || 'Lookup failed');
      } finally {
        if (!canceled) setLoading(false);
      }
    };
    run();
    return () => { canceled = true; };
  }, [term, patientId, sessionId]);

  return (
    <div className="fixed bottom-6 right-6 z-50 w-full max-w-md shadow-2xl border border-gray-200 bg-white rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
        <div className="font-semibold text-gray-800">{t('lookup.title')}: <span className="text-blue-700">{term}</span></div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-800">✕</button>
      </div>
      <div className="p-4 max-h-96 overflow-y-auto text-sm text-gray-900">
        {loading && (<div className="text-gray-600">{tCommon('searching')}</div>)}
        {error && (<div className="text-red-600">{t('lookup.error')}</div>)}
        {!loading && !error && result && (
          <div className="space-y-3">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }: any) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-800 underline"
                    >
                      {children}
                    </a>
                  ),
                  h1: ({ children }: any) => (
                    <h1 className="text-base font-bold mb-2 text-gray-900">{children}</h1>
                  ),
                  h2: ({ children }: any) => (
                    <h2 className="text-sm font-semibold mb-1 text-gray-900">{children}</h2>
                  ),
                  h3: ({ children }: any) => (
                    <h3 className="text-sm font-medium mb-1 text-gray-900">{children}</h3>
                  ),
                  p: ({ children }: any) => (
                    <p className="mb-2 text-gray-900">{children}</p>
                  ),
                  ul: ({ children }: any) => (
                    <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>
                  ),
                  ol: ({ children }: any) => (
                    <ol className="list-decimal list-inside space-y-1 mb-2">{children}</ol>
                  ),
                  code: ({ inline, children }: any) => (
                    inline ? (
                      <code className="bg-gray-100 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>
                    ) : (
                      <pre className="bg-gray-100 text-gray-800 p-2 rounded text-xs font-mono overflow-x-auto mb-2">
                        <code>{children}</code>
                      </pre>
                    )
                  )
                }}
              >
                {result.summary}
              </ReactMarkdown>
            </div>
            {result.sources?.length ? (
              <div>
                <div className="text-xs font-semibold text-gray-700 mb-1">{t('lookup.sources')}</div>
                <ul className="list-disc list-inside space-y-1">
                  {result.sources.map((s, i) => (
                    <li key={i}>
                      <a href={s.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800 underline">
                        {s.title || s.url}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

const parseLinksInText = (text: string, isUser: boolean = false) => {
  // Escape HTML first to prevent XSS
  const escapeHtml = (unsafe: string) => {
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  };

  // Escape the text first
  let processedText = escapeHtml(text);
  
  const linkClass = isUser 
    ? "text-blue-200 hover:text-blue-100 underline font-medium transition-colors duration-200 break-words"
    : "text-blue-600 hover:text-blue-800 underline font-medium transition-colors duration-200 break-words";
  
  const externalIcon = `<svg class="w-3 h-3 inline ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>`;
  
  // Regular expressions for different link formats
  const markdownLinkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const urlRegex = /(https?:\/\/[^\s<>]+)/g;
  
  // Handle markdown-style links [text](url) first
  processedText = processedText.replace(markdownLinkRegex, (match, linkText, url) => {
    // Unescape the URL and link text for proper use in href
    const cleanUrl = url.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    const cleanLinkText = linkText.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    
    return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="${linkClass}">${cleanLinkText}${externalIcon}</a>`;
  });
  
  // Handle plain URLs (avoiding already processed markdown links)
  processedText = processedText.replace(urlRegex, (url) => {
    // Skip if this URL is already inside an <a> tag
    const beforeMatch = processedText.substring(0, processedText.indexOf(url));
    if (beforeMatch.includes('<a href=')) {
      // Check if we're inside a recently created link
      const lastLinkStart = beforeMatch.lastIndexOf('<a href=');
      const lastLinkEnd = beforeMatch.lastIndexOf('</a>');
      if (lastLinkStart > lastLinkEnd) {
        return url; // We're inside a link, don't process
      }
    }
    
    const cleanUrl = url.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    const displayUrl = cleanUrl.length > 50 ? cleanUrl.substring(0, 47) + '...' : cleanUrl;
    
    return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="${linkClass}">${displayUrl}${externalIcon}</a>`;
  });
  
  return processedText;
};

interface MessageContentProps {
  text: string;
  isUser: boolean;
  patientId?: string;
  sessionId?: string | null;
  citations?: Record<string, Citation>;
}

const MessageContent = ({ text, isUser, patientId, sessionId, citations = {} }: MessageContentProps) => {
  // Custom components for markdown rendering
  const markdownComponents = {
    // Links
    a: ({ href, children }: any) => (
      <a 
        href={href} 
        target="_blank" 
        rel="noopener noreferrer" 
        className={isUser 
          ? "text-blue-200 hover:text-blue-100 underline font-medium transition-colors duration-200 break-words"
          : "text-blue-600 hover:text-blue-800 underline font-medium transition-colors duration-200 break-words"
        }
      >
        {children}
        <svg className="w-3 h-3 inline ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
        </svg>
      </a>
    ),
    // Headers
    h1: ({ children }: any) => (
      <h1 className={`text-xl font-bold mb-2 text-gray-900`}>
        {children}
      </h1>
    ),
    h2: ({ children }: any) => (
      <h2 className={`text-lg font-bold mb-2 text-gray-900`}>
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className={`text-md font-bold mb-1 text-gray-900`}>
        {children}
      </h3>
    ),
    // Emphasis
    strong: ({ children }: any) => (
      <strong className={`font-bold text-gray-900`}>
        {children}
      </strong>
    ),
    em: ({ children }: any) => (
      <em className={`italic text-gray-900`}>
        {children}
      </em>
    ),
    // Code
    code: ({ children, className }: any) => {
      const isCodeBlock = className?.includes('language-');
      if (isCodeBlock) {
        return (
          <pre className={`bg-gray-800 text-green-400 p-3 rounded-lg overflow-x-auto text-sm my-2 ${isUser ? 'bg-gray-700' : 'bg-gray-800'}`}>
            <code className="font-mono">{children}</code>
          </pre>
        );
      }
      return (
        <code className={`px-1 py-0.5 rounded text-sm font-mono ${
          isUser 
            ? 'bg-blue-700 text-blue-100' 
            : 'bg-gray-200 text-gray-800'
        }`}>
          {children}
        </code>
      );
    },
    // Lists
    ul: ({ children }: any) => (
      <ul className={`list-disc list-inside my-2 space-y-3 text-gray-900`}>
        {children}
      </ul>
    ),
    ol: ({ children }: any) => (
      <ol className={`list-decimal list-inside my-2 space-y-3 text-gray-900`}>
        {children}
      </ol>
    ),
    li: ({ children }: any) => (
      <li className={`text-gray-900 mb-2`}>
        {children}
      </li>
    ),
    // Blockquotes
    blockquote: ({ children }: any) => (
      <blockquote className={`border-l-4 pl-4 my-2 italic ${
        isUser 
          ? 'border-blue-300 text-blue-100' 
          : 'border-gray-400 text-gray-700'
      }`}>
        {children}
      </blockquote>
    ),
    // Paragraphs
    p: ({ children }: any) => (
      <p className={`mb-2 last:mb-0 text-gray-900`}>
        {children}
      </p>
    ),
    // Horizontal rule
    hr: () => (
      <hr className={`my-3 border-t ${
        isUser ? 'border-blue-300' : 'border-gray-300'
      }`} />
    ),
    // Tables
    table: ({ children }: any) => (
      <div className="overflow-x-auto mb-4 mt-2">
        <table className="min-w-full border-collapse border-2 border-gray-300 bg-white shadow-sm">{children}</table>
      </div>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-gray-100">{children}</thead>
    ),
    tbody: ({ children }: any) => (
      <tbody>{children}</tbody>
    ),
    th: ({ children }: any) => (
      <th className="border border-gray-300 bg-gray-100 px-4 py-3 text-sm font-bold text-gray-900 text-left">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="border border-gray-300 px-4 py-3 text-sm text-gray-700">{children}</td>
    ),
    tr: ({ children }: any) => (
      <tr className="hover:bg-gray-50">{children}</tr>
    ),
  };
  
  // Selection-based lookup UI
  const [selection, setSelection] = useState<string>("");
  const [lookupTerm, setLookupTerm] = useState<string>("");
  const [showLookup, setShowLookup] = useState<boolean>(false);
  const tChatBox = useTranslations('chatBox');

  // Scope selection to this message content only
  // Scope selection to this message content only
  const contentRef = useRef<HTMLDivElement>(null);
  const ignoreSelectionUntil = useRef<number>(0);
  const updateSelection = () => {
    const container = contentRef.current;
    if (!container) {
      setSelection("");
      return;
    }
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) {
      setSelection("");
      return;
    }
    const range = sel.getRangeAt(0);
    const inContainer = container.contains(range.startContainer) && container.contains(range.endContainer);
    setSelection(inContainer ? sel.toString().trim() : "");
  };

  // Removed programmatic word selection; rely on native selection

  // We avoid global selectionchange to reduce flakiness across devices

  // Get word at a touch/click point without changing DOM selection
  const getWordAtPoint = (evt: any): string => {
    const container = contentRef.current;
    if (!container) return "";

    let x = 0, y = 0;
    if (evt?.changedTouches?.length) {
      x = evt.changedTouches[0].clientX;
      y = evt.changedTouches[0].clientY;
    } else {
      x = evt.clientX;
      y = evt.clientY;
    }

    let caretRange: Range | null = (document as any).caretRangeFromPoint?.(x, y) || null;
    if (!caretRange && (document as any).caretPositionFromPoint) {
      const pos = (document as any).caretPositionFromPoint(x, y);
      if (pos) {
        caretRange = document.createRange();
        caretRange.setStart(pos.offsetNode, pos.offset);
        caretRange.collapse(true);
      }
    }

    if (!caretRange) return "";
    let node: Node = caretRange.startContainer;
    let offset: number = caretRange.startOffset;
    if (!container.contains(node)) return "";

    if (node.nodeType !== Node.TEXT_NODE) {
      let candidate: Node | null = null;
      if ((node as any).childNodes?.length) {
        const idx = Math.min(offset, (node as any).childNodes.length - 1);
        candidate = (node as any).childNodes[idx] || (node as any).firstChild;
      }
      while (candidate && candidate.nodeType !== Node.TEXT_NODE && (candidate as any).firstChild) {
        candidate = (candidate as any).firstChild;
      }
      if (!candidate || candidate.nodeType !== Node.TEXT_NODE) return "";
      node = candidate;
      offset = 0;
    }

    const textNode = node as Text;
    const text = textNode.data || "";
    if (!text) return "";

    const isWord = (ch: string) => /[A-Za-z0-9]/.test(ch);
    let start = Math.max(0, Math.min(offset, text.length));
    let end = start;
    while (start > 0 && isWord(text[start - 1])) start--;
    while (end < text.length && isWord(text[end])) end++;
    return text.slice(start, end).trim();
  };

  const handleTouchEnd = (e: any) => {
    // Treat quick taps as word lookups without forcing DOM highlight
    const word = getWordAtPoint(e);
    if (word) {
      e.preventDefault?.();
      e.stopPropagation?.();
      setSelection(word);
      return;
    }
    updateSelection();
  };
  const handleMouseUp = () => updateSelection();

  return (
    <div
      ref={contentRef}
      className={`font-medium text-gray-900 select-text`}
      onTouchEnd={handleTouchEnd}
      onMouseUp={handleMouseUp}
      onKeyUp={updateSelection}
    >
      <MarkdownWithCitations
        content={text}
        citations={citations}
        components={markdownComponents}
      />
      {selection && selection.length >= 2 && !isUser && (
        <div className="mt-2">
          <button
            type="button"
            onMouseDown={(e) => { e.stopPropagation(); }}
            onMouseUp={(e) => { e.stopPropagation(); }}
            onTouchStart={(e) => { e.stopPropagation(); }}
            onTouchEnd={(e) => { e.stopPropagation(); }}
            onPointerDown={(e) => { e.stopPropagation(); }}
            onPointerUp={(e) => { e.stopPropagation(); }}
            onClick={() => { setLookupTerm(selection); setShowLookup(true); }}
            className="px-2 py-1 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700"
          >
            {tChatBox('lookup.action', { term: selection, default: `Lookup “${selection}”` })}
          </button>
        </div>
      )}
      {showLookup && lookupTerm && (
        <LookupPanel term={lookupTerm} onClose={() => setShowLookup(false)} patientId={patientId} sessionId={sessionId} />
      )}
    </div>
  );
};

const getAuthHeaders = () => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  // Get the authentication session_id from localStorage
  const authToken = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
  if (authToken) {
    headers['X-Session-ID'] = authToken;
  }
  return headers;
};

const GeneratedImageDisplay = ({ imageInfo }: { imageInfo: GeneratedImageInfo }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoading, setImageLoading] = useState(true);
  const [imageUrl, setImageUrl] = useState<string>('');

  // DEBUG: Log what we received
  useEffect(() => {
    logInfo(`🖼️ GeneratedImageDisplay received - image_generated: ${imageInfo.image_generated}, image_id: ${imageInfo.image_id ? sanitizeDocumentId(imageInfo.image_id) : 'none'}`);
  }, [imageInfo]);

  // Load image with proper headers
  useEffect(() => {
    if (imageInfo.image_generated && imageInfo.image_id) {
      const loadImageWithHeaders = async () => {
        try {
          logInfo(`Loading image with headers - image_id: ${sanitizeDocumentId(imageInfo.image_id!)}`);
          const response = await fetch(`/api/images/generated/${imageInfo.image_id}`, {
            headers: getAuthHeaders()
          });

          if (response.ok) {
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            setImageUrl(url);
            logInfo('Image loaded successfully');
          } else {
            logError(`Failed to load image: ${response.status} ${response.statusText}`);
            setImageError(true);
          }
        } catch (error) {
          logError('Error loading image', error as Error);
          setImageError(true);
        } finally {
          setImageLoading(false);
        }
      };

      loadImageWithHeaders();
    }
  }, [imageInfo.image_generated, imageInfo.image_id]);

  // Cleanup blob URL when component unmounts
  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

  if (!imageInfo.image_generated || !imageInfo.image_id) {
    logInfo(`🚫 Not displaying image - image_generated: ${imageInfo.image_generated}, image_id: ${imageInfo.image_id ? sanitizeDocumentId(imageInfo.image_id) : 'none'}`);
    return null;
  }

  const handleDownload = async () => {
    try {
      await downloadGeneratedImage(imageInfo.image_id!, `generated_${imageInfo.image_id}.png`);
    } catch (error) {
      logError('Error downloading image', error as Error);
      alert('Failed to download image');
    }
  };

  const handleOpenInNewTab = async () => {
    try {
      const imageUrl = await getGeneratedImageUrl(imageInfo.image_id!);
      window.open(imageUrl, '_blank');
    } catch (error) {
      logError('Error opening image', error as Error);
      alert('Failed to open image');
    }
  };

  const handleImageLoad = () => {
    logInfo('✅ Image displayed successfully');
    setImageError(false);
  };

  const handleImageError = (e: any) => {
    logError('❌ Failed to display image', e);
    setImageError(true);
  };

  return (
    <div className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
      <div className="flex items-center gap-2 mb-2">
        <ImageIcon className="h-4 w-4 text-blue-600" />
        <span className="text-sm font-medium text-gray-700">Generated Educational Image</span>
      </div>
      
      <div className="mb-2">
        {imageLoading && !imageError && (
          <div className="flex items-center justify-center p-4 bg-gray-100 rounded border">
            <div className="animate-spin h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full mr-2"></div>
            <span className="text-sm text-gray-600">Loading image...</span>
          </div>
        )}
        
        {imageError ? (
          <div className="p-4 bg-red-50 border border-red-200 rounded text-center">
            <p className="text-sm text-red-600 mb-2">Failed to load image</p>
            <p className="text-xs text-gray-500 mb-2">Image ID: {imageInfo.image_id}</p>
            <button
              onClick={() => {
                logInfo('🔄 Retrying image load');
                setImageError(false);
                setImageLoading(true);
                // Trigger re-load by updating a dependency
                window.location.reload();
              }}
              className="text-xs text-blue-600 hover:text-blue-800 underline"
            >
              Retry
            </button>
          </div>
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt="Generated medical illustration"
            className="max-w-full h-auto rounded border border-gray-300 shadow-sm"
            style={{ 
              maxHeight: '300px'
            }}
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        ) : null}
      </div>
      
      {imageInfo.image_prompt && (
        <p className="text-xs text-gray-600 mb-2">
          <strong>Prompt:</strong> {imageInfo.image_prompt}
        </p>
      )}
      
      <div className="flex gap-2">
        <button
          onClick={handleDownload}
          className="flex items-center gap-1 px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors"
        >
          <Download className="h-3 w-3" />
          Download
        </button>
        <button
          onClick={handleOpenInNewTab}
          className="flex items-center gap-1 px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700 transition-colors"
        >
          <ExternalLink className="h-3 w-3" />
          Open in New Tab
        </button>
      </div>
    </div>
  );
};

const formatTimestamp = (timestamp: string | number): string => {
  try {
    let date: Date;
    
    if (typeof timestamp === 'string') {
      // Check if it's a string of digits (milliseconds)
      if (timestamp.match(/^\d+$/)) {
        date = new Date(parseInt(timestamp));
      } else {
        // Try parsing as ISO string
        date = new Date(timestamp);
      }
    } else {
      // It's already a number
      date = new Date(timestamp);
    }
    
    // Check if the date is valid
    if (isNaN(date.getTime())) {
      logWarning(`Invalid timestamp: ${timestamp}`);
      return new Date().toLocaleTimeString();
    }

    return date.toLocaleTimeString();
  } catch (error) {
    logError(`Error formatting timestamp: ${timestamp}`, error as Error);
    return new Date().toLocaleTimeString();
  }
};

export function ChatBox({ mode, patientId, sessionId: propSessionId }: ChatBoxProps) {
  const t = useTranslations('chatBox');
  const locale = useLocale();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [infoRetrievalMode, setInfoRetrievalMode] = useState("post_meet");
  const [defaultPrompt, setDefaultPrompt] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // PDF upload state
  const [uploadedPDFs, setUploadedPDFs] = useState<PDFDocument[]>([]);
  const [isUploadingPDF, setIsUploadingPDF] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [forceRefresh, setForceRefresh] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // XML upload state
  const [uploadedXMLs, setUploadedXMLs] = useState<XMLDocument[]>([]);
  const [isUploadingXML, setIsUploadingXML] = useState(false);
  const xmlFileInputRef = useRef<HTMLInputElement>(null);

  // Note generation state
  const [noteGenerationDialogOpen, setNoteGenerationDialogOpen] = useState(false);
  const [autoGeneratedNote, setAutoGeneratedNote] = useState<string | null>(null);

  // Voice recording state
  const [isVoiceRecording, setIsVoiceRecording] = useState(false);
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false);

  // Check if info mode selection is enabled
  const isInfoModeEnabled = process.env.NEXT_PUBLIC_INFO_MODE === 'false';

  // Use provided sessionId or generate one
  const [sessionId] = useState(() => {
    if (propSessionId) return propSessionId;

    if (typeof window !== 'undefined') {
      const key = `chat_session_${mode}_${patientId || 'general'}`;
      let existing = localStorage.getItem(key);
      if (!existing) {
        existing = `${mode}_${patientId || 'general'}_${Date.now()}`;
        localStorage.setItem(key, existing);
      }
      return existing;
    }
    return `${mode}_${patientId || 'general'}_${Date.now()}`;
  });

  const {
    isStreaming,
    currentStep,
    currentDescription,
    reasoning,
    currentReasoning,
    finalResponse,
    streamingResponse,
    generatedImage,
    citations: streamingCitations,
    streamDifferentialDiagnoses, // Add this for differential diagnoses
    differentialDiagnosisProgress, // Add this for progress tracking
    noteGenerationProgress, // Add this for note generation tracking
    error: streamError,
    progress,
    startStream,
    stopStream,
  } = useStreamingChat(sessionId);
  
  const { user } = useUser();

  // Initialize info retrieval mode with default prompt
  useEffect(() => {
    if (mode === "diagnose") {
      const postMeetPrompt = "Following a patient encounter, I need to analyze the clinical data and findings. Please help me review the patient information, examination findings, and any relevant background data to support clinical decision-making and documentation.";
      
      setDefaultPrompt(postMeetPrompt);
      
      // Set the default prompt if input is empty (only if info mode is not enabled for selection)
      if (!input.trim() && !isInfoModeEnabled) {
        setInput(postMeetPrompt);
      }
    }
  }, [mode, isInfoModeEnabled]);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isStreaming]);

  // Auto-scroll when differential diagnosis computation starts
  useEffect(() => {
    if (differentialDiagnosisProgress?.isComputing) {
      logInfo('🔄 Differential diagnosis computation started - auto-scrolling');
      scrollToBottom();
    }
  }, [differentialDiagnosisProgress?.isComputing]);

  // Auto-scroll when differential diagnosis progress updates
  useEffect(() => {
    if (differentialDiagnosisProgress?.currentDiagnosis || differentialDiagnosisProgress?.currentStep) {
      logInfo('🔄 Differential diagnosis progress updated - auto-scrolling');
      scrollToBottom();
    }
  }, [differentialDiagnosisProgress?.currentDiagnosis, differentialDiagnosisProgress?.currentStep]);

  // Update sessionId when prop changes
  useEffect(() => {
    if (propSessionId && propSessionId !== sessionId) {
      // Clear messages when switching sessions
      setMessages([]);
    }
  }, [propSessionId]);

  // Use propSessionId if provided, otherwise use generated sessionId
  const currentSessionId = propSessionId || sessionId;

  // Load messages from localStorage on mount (GDPR-compliant client-side persistence)
  useEffect(() => {
    if (typeof window !== 'undefined' && currentSessionId) {
      const messagesKey = `chat_messages_${currentSessionId}`;
      const storedMessages = localStorage.getItem(messagesKey);

      if (storedMessages) {
        try {
          const parsedMessages = JSON.parse(storedMessages);
          setMessages(parsedMessages);
          logInfo(`[ChatBox] Loaded ${parsedMessages.length} messages from localStorage for session ${sanitizeSessionId(currentSessionId)}`);
        } catch (error) {
          logError('[ChatBox] Failed to parse stored messages', error as Error);
        }
      }
    }
  }, [currentSessionId]);

  // Save messages to localStorage whenever they change (GDPR-compliant client-side persistence)
  useEffect(() => {
    if (typeof window !== 'undefined' && currentSessionId && messages.length > 0) {
      const messagesKey = `chat_messages_${currentSessionId}`;
      try {
        localStorage.setItem(messagesKey, JSON.stringify(messages));
        logInfo(`[ChatBox] Saved ${messages.length} messages to localStorage for session ${sanitizeSessionId(currentSessionId)}`);
      } catch (error) {
        logError('[ChatBox] Failed to save messages to localStorage', error as Error);
      }
    }
  }, [messages, currentSessionId]);

  // Debug effect to track PDF state changes
  useEffect(() => {
    logInfo(`[ChatBox] uploadedPDFs state changed - count: ${uploadedPDFs.length}, pdfs: ${uploadedPDFs.map(pdf => `${pdf.filename}(${pdf.status})`).join(', ')}`);
  }, [uploadedPDFs]);

  // Debug effect to track XML state changes
  useEffect(() => {
    logInfo(`[ChatBox] uploadedXMLs state changed - count: ${uploadedXMLs.length}, xmls: ${uploadedXMLs.map(xml => `${xml.filename}(${xml.status},${xml.document_type})`).join(', ')}`);
  }, [uploadedXMLs]);

  // Load PDF documents for the current session context
  const loadPDFs = useCallback(async () => {
    try {
      logInfo(`[ChatBox] Loading PDFs for session - patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);

      // PDFs are now session-based, so we get PDFs for the current session
      // The patientId parameter filters to patient-specific PDFs when a patient is selected
      const pdfList = await listPDFDocuments(patientId, currentSessionId);

      logInfo(`[ChatBox] Raw API response - document count: ${pdfList.documents?.length || 0}`);

      const allDocs = pdfList.documents || [];

      // Filter to only show documents uploaded after this session started
      // This prevents old auth session documents from appearing in new sessions
      // Use a 5-second buffer to account for timing precision and clock skew
      // This ensures watcher agent uploads aren't filtered out due to timing issues
      const sessionStartWithBuffer = sessionStartTime.current - 5000; // 5 seconds buffer
      const newDocs = allDocs.filter(doc => {
        const uploadedAt = new Date(doc.uploaded_at).getTime();
        const isNew = uploadedAt >= sessionStartWithBuffer;
        if (!isNew) {
          logInfo(`[ChatBox] Filtering out old PDF: ${doc.filename} (uploaded before session start with buffer)`);
        }
        return isNew;
      });

      logInfo(`[ChatBox] Parsed ${newDocs.length} PDFs for session (patient: ${sanitizePatientId(patientId || null)}) - filtered from ${allDocs.length} total`);
      logInfo(`[ChatBox] PDF details - files: ${newDocs.map(pdf => `${pdf.filename}(${pdf.status})`).join(', ')}`);

      // Update the state and log the change
      setUploadedPDFs(prevPDFs => {
        logInfo(`[ChatBox] Previous PDF count: ${prevPDFs.length}, New PDF count: ${newDocs.length}, Changed: ${prevPDFs.length !== newDocs.length}`);
        return newDocs;
      });

      // Force refresh counter update to trigger re-renders
      setForceRefresh(prev => prev + 1);

    } catch (error) {
      logError('[ChatBox] Failed to load PDFs', error as Error);
    }
  }, [patientId, currentSessionId]);

  // Load XML documents for the current session context
  const loadXMLs = useCallback(async () => {
    try {
      logInfo(`[ChatBox] Loading XMLs for session - patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);

      // XMLs are now session-based, so we get XMLs for the current session
      // The patientId parameter filters to patient-specific XMLs when a patient is selected
      const xmlList = await listXMLDocuments(patientId, currentSessionId);

      logInfo(`[ChatBox] Raw XML API response - document count: ${xmlList.documents?.length || 0}`);

      const allDocs = xmlList.documents || [];

      // Filter to only show documents uploaded after this session started
      // This prevents old auth session documents from appearing in new sessions
      // Use a 5-second buffer to account for timing precision and clock skew
      // This ensures watcher agent uploads aren't filtered out due to timing issues
      const sessionStartWithBuffer = sessionStartTime.current - 5000; // 5 seconds buffer
      const newDocs = allDocs.filter(doc => {
        const uploadedAt = new Date(doc.uploaded_at).getTime();
        const isNew = uploadedAt >= sessionStartWithBuffer;
        if (!isNew) {
          logInfo(`[ChatBox] Filtering out old XML: ${doc.filename} (uploaded before session start with buffer)`);
        }
        return isNew;
      });

      logInfo(`[ChatBox] Parsed ${newDocs.length} XMLs for session (patient: ${sanitizePatientId(patientId || null)}) - filtered from ${allDocs.length} total`);
      logInfo(`[ChatBox] XML details - files: ${newDocs.map(xml => `${xml.filename}(${xml.status},${xml.document_type})`).join(', ')}`);

      // Update the state and log the change
      setUploadedXMLs(prevXMLs => {
        logInfo(`[ChatBox] Previous XML count: ${prevXMLs.length}, New XML count: ${newDocs.length}, Changed: ${prevXMLs.length !== newDocs.length}`);
        return newDocs;
      });

      // Force refresh counter update to trigger re-renders
      setForceRefresh(prev => prev + 1);

    } catch (error) {
      logError('[ChatBox] Failed to load XMLs', error as Error);
    }
  }, [patientId, currentSessionId]);

  // Track session start time to filter out old auth session documents
  // Persist session start time in localStorage to survive page refreshes
  const getInitialSessionStartTime = () => {
    if (typeof window !== 'undefined') {
      const key = `session_start_time_${currentSessionId}`;
      const stored = localStorage.getItem(key);
      if (stored) {
        const storedTime = parseInt(stored, 10);
        logInfo(`[ChatBox] Restored session start time from localStorage: ${new Date(storedTime).toISOString()}`);
        return storedTime;
      }
    }
    const now = Date.now();
    logInfo(`[ChatBox] Created new session start time: ${new Date(now).toISOString()}`);
    return now;
  };

  const sessionStartTime = useRef<number>(getInitialSessionStartTime());

  // Reset session start time when session changes
  useEffect(() => {
    logInfo(`[ChatBox] Session changed, initializing session start time - sessionId: ${sanitizeSessionId(currentSessionId)}`);

    // Persist session start time to localStorage
    if (typeof window !== 'undefined') {
      const key = `session_start_time_${currentSessionId}`;
      const existingTime = localStorage.getItem(key);

      // Check for old session ID to cleanup (stored by parent when creating new session)
      const oldSessionCleanupKey = `cleanup_old_session_${mode}_${patientId || 'general'}`;
      const oldSessionToCleanup = localStorage.getItem(oldSessionCleanupKey);

      // Only set new time if this is a new session (no existing time)
      if (!existingTime) {
        const now = Date.now();
        sessionStartTime.current = now;
        localStorage.setItem(key, now.toString());
        logInfo(`[ChatBox] Created new session start time: ${new Date(now).toISOString()}`);

        // NEW SESSION: Clear all documents, messages, and cleanup backend
        logInfo('[ChatBox] New session detected - clearing all documents and messages');
        setUploadedPDFs([]);
        setUploadedXMLs([]);
        setMessages([]);

        // Clear messages from localStorage
        const messagesKey = `chat_messages_${currentSessionId}`;
        localStorage.removeItem(messagesKey);
        logInfo('[ChatBox] Cleared messages from localStorage');

        // Clean up old documents from backend (both old chat session and auth session)
        const cleanup = async () => {
          try {
            logInfo(`[ChatBox] Calling backend to cleanup old documents - old chat session: ${oldSessionToCleanup ? sanitizeSessionId(oldSessionToCleanup) : 'none'}`);
            const result = await cleanupSessionDocuments(oldSessionToCleanup || undefined);
            logInfo(`[ChatBox] Backend cleanup complete: ${result.deleted_pdfs} PDFs, ${result.deleted_xmls} XMLs deleted`);

            // Clear the cleanup marker now that we've cleaned up
            if (oldSessionToCleanup) {
              localStorage.removeItem(oldSessionCleanupKey);
              logInfo('[ChatBox] Cleared old session cleanup marker from localStorage');
            }
          } catch (error) {
            logError('[ChatBox] Backend cleanup failed', error as Error);
            // Don't fail the session start if cleanup fails
          }
        };

        cleanup();
      } else {
        // Session already exists (e.g., after page refresh), restore the time
        const storedTime = parseInt(existingTime, 10);
        sessionStartTime.current = storedTime;
        logInfo(`[ChatBox] Restored existing session start time: ${new Date(storedTime).toISOString()}`);
        logInfo('[ChatBox] Page refresh detected - documents will be reloaded from backend');
        // Don't clear documents - let loadPDFs/loadXMLs restore them

        // Also clear any lingering cleanup marker (shouldn't happen but be safe)
        if (oldSessionToCleanup) {
          localStorage.removeItem(oldSessionCleanupKey);
        }
      }

      // Clean up old session start times (older than 7 days)
      const sevenDaysAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
      Object.keys(localStorage).forEach(storageKey => {
        if (storageKey.startsWith('session_start_time_')) {
          const timeValue = localStorage.getItem(storageKey);
          if (timeValue && parseInt(timeValue, 10) < sevenDaysAgo) {
            localStorage.removeItem(storageKey);
            logInfo(`[ChatBox] Cleaned up old session start time: ${storageKey}`);
          }
        }
      });
    }
  }, [currentSessionId, mode, patientId]);

  // GDPR-compliant: Chat history now loaded from localStorage (client-side only)
  // This useEffect loads documents but not messages (messages are loaded from localStorage above)
  useEffect(() => {
  const loadHistory = async () => {
    try {
      logInfo(`[GDPR] Chat history loaded from localStorage - sessionId: ${sanitizeSessionId(currentSessionId)}, patientId: ${sanitizePatientId(patientId || null)}`);

      // GDPR Compliance: Chat history is now stored in localStorage (client-side only)
      // Messages are loaded from localStorage in a separate useEffect
      // This function now only handles backend chat history API (which is disabled for GDPR)

      // Skip backend API call - we use localStorage instead
      logInfo('🔍 [GDPR] Skipping backend chat history API - using localStorage instead');
      return;

      // The code below is kept for reference but never executed
      const response = await fetch('/api/chat-history', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          patient_id: patientId,
          session_id: currentSessionId,
          mode: mode
        })
      });
      
      if (response.ok) {
        const data = await response.json();
        logInfo(`🔍 Raw chat history data received - message count: ${data.messages?.length || 0}`);

        if (data.messages && data.messages.length > 0) {
          const formattedMessages = data.messages.map((msg: any, index: number) => {
            logInfo(`🔍 Processing message ${index} - role: ${msg.role}, hasDifferential: ${!!msg.differential_diagnoses}, differentialCount: ${msg.differential_diagnoses?.length || 0}, hasReasoning: ${!!(msg.reasoning || msg.reasoning_steps?.length)}, reasoningStepsCount: ${msg.reasoning_steps?.length || 0}`);

            const formattedMessage: Message = {
              sender: msg.role === 'user' ? 'user' : 'system',
              text: msg.content,
              timestamp: msg.timestamp ? formatTimestamp(msg.timestamp) : new Date().toLocaleTimeString()
            };
            
            // Add reasoning from multiple possible sources
            if (msg.reasoning || (msg.reasoning_steps && msg.reasoning_steps.length > 0)) {
              logInfo(`🧠 Found reasoning in chat history for message ${index} - reasoning: ${!!msg.reasoning}, reasoningSteps: ${msg.reasoning_steps?.length || 0}`);

              formattedMessage.reasoning = msg.reasoning || (msg.reasoning_steps ? msg.reasoning_steps.join('\n') : '');
              formattedMessage.reasoningSteps = msg.reasoning_steps || [];
            }

            // Add generated image info if present
            if (msg.generated_image && msg.generated_image.image_generated) {
              formattedMessage.generatedImage = msg.generated_image;
              logInfo(`📸 Found image in chat history for message ${index} - image_id: ${sanitizeDocumentId(msg.generated_image.image_id)}`);
            }

            // Enhanced differential diagnoses loading - more lenient validation
            if (msg.differential_diagnoses && Array.isArray(msg.differential_diagnoses)) {
              logInfo(`🩺 Processing differential diagnoses for message ${index} - count: ${msg.differential_diagnoses.length}`);

              // More lenient validation - only require essential fields
              const validDiagnoses = msg.differential_diagnoses.filter((diff: any) => {
                const isValid = diff &&
                  typeof diff === 'object' &&
                  diff.diagnosis_name &&
                  (diff.confidence !== undefined && diff.confidence !== null);

                if (!isValid) {
                  logWarning(`🚫 Invalid diagnosis in message ${index} - diagnosis_name: ${diff?.diagnosis_name || 'missing'}, confidence: ${diff?.confidence}`);
                }
                return isValid;
              });

              if (validDiagnoses.length > 0) {
                // Ensure all required fields have defaults
                formattedMessage.differentialDiagnoses = validDiagnoses.map((diff: any) => ({
                  icd_code: diff.icd_code || '',
                  diagnosis_name: diff.diagnosis_name || 'Unknown Diagnosis',
                  confidence: typeof diff.confidence === 'number' ? diff.confidence : 0,
                  reasoning: diff.reasoning || 'No reasoning provided',
                  supporting_evidence: Array.isArray(diff.supporting_evidence) ? diff.supporting_evidence : []
                }));

              } else {
                logWarning(`🚫 No valid differential diagnoses found for message ${index} - total count: ${msg.differential_diagnoses.length}`);
              }
            } else {
              logInfo(`📄 No differential diagnoses for message ${index} - hasDifferential: ${!!msg.differential_diagnoses}, isArray: ${Array.isArray(msg.differential_diagnoses)}, type: ${typeof msg.differential_diagnoses}`);
            }

            // Handle SBAR results (both old format and new JSON cards format)
            if (msg.sbar_results && typeof msg.sbar_results === 'object') {
              logInfo(`📋 Processing SBAR results for message ${index}`);
              formattedMessage.sbarResults = {
                situation: msg.sbar_results.situation || undefined,
                background: msg.sbar_results.background || undefined,
                assessment: msg.sbar_results.assessment || undefined,
                recommendation: msg.sbar_results.recommendation || undefined
              };
            } else {
              // Check if the main content is a JSON SBAR cards response
              logInfo(`🔍 Checking message ${index} text for SBAR JSON - preview: ${msg.text?.substring(0, 100)}`);
              try {
                // Trim the text and check if it looks like JSON
                const trimmedText = msg.text?.trim();
                if (trimmedText && trimmedText.startsWith('{') && trimmedText.endsWith('}')) {
                  const parsedContent = JSON.parse(trimmedText);
                  logInfo(`🧪 Parsed JSON for message ${index} - type: ${parsedContent.type}`);

                  if (parsedContent.type === 'sbar_cards' && parsedContent.components) {
                    logInfo(`📋 Processing JSON SBAR cards for message ${index}`);
                    formattedMessage.sbarResults = {
                      situation: parsedContent.components.situation?.content || undefined,
                      background: parsedContent.components.background?.content || undefined,
                      assessment: parsedContent.components.assessment?.content || undefined,
                      recommendation: parsedContent.components.recommendation?.content || undefined
                    };
                    // Clear the content so we don't display the raw JSON
                    formattedMessage.text = '';
                    logInfo(`✅ Successfully processed SBAR cards, cleared text`);
                  } else if (parsedContent.type === 'general_summary_cards' && parsedContent.components) {
                    logInfo(`📋 Processing JSON General Summary cards for message ${index}`);
                    formattedMessage.generalSummaryResults = {
                      snapshot: parsedContent.components.snapshot?.content || undefined,
                      problems: parsedContent.components.problems?.content || undefined,
                      medications: parsedContent.components.medications?.content || undefined,
                      trends: parsedContent.components.trends?.content || undefined,
                      // For encounters, pass the full object with structured_data for clickable encounters
                      encounters: parsedContent.components.encounters ? {
                        content: parsedContent.components.encounters.content || '',
                        structured_data: parsedContent.components.encounters.structured_data || []
                      } : undefined,
                      risks: parsedContent.components.risks?.content || undefined
                    };
                    // Clear the content so we don't display the raw JSON
                    formattedMessage.text = '';
                    logInfo(`✅ Successfully processed General Summary cards, cleared text`);
                  } else if (parsedContent.type === 'focused_summary' && parsedContent.sections) {
                    logInfo(`🎯 Processing JSON Focused Summary for message ${index}`);
                    formattedMessage.focusedSummaryResults = {
                      diagnoses: parsedContent.sections.diagnoses?.content || undefined,
                      events: parsedContent.sections.events?.content || undefined,
                      medications: parsedContent.sections.medications?.content || undefined,
                      objective_data: parsedContent.sections.objective_data?.content || undefined,
                      assessment: parsedContent.sections.assessment?.content || undefined,
                      next_steps: parsedContent.sections.next_steps?.content || undefined
                    };
                    formattedMessage.focusedAspect = parsedContent.aspect || "Medical Condition";
                    formattedMessage.focusedAspectIcon = parsedContent.aspect_icon || "file-text";
                    // Clear the content so we don't display the raw JSON
                    formattedMessage.text = '';
                    logInfo(`✅ Successfully processed Focused Summary, cleared text`);
                  } else if (parsedContent.type === 'timeline_view' && parsedContent.events) {
                    logInfo(`📅 Processing JSON Timeline for message ${index}`);
                    formattedMessage.timelineResults = {
                      events: parsedContent.events
                    };
                    // Clear the content so we don't display the raw JSON
                    formattedMessage.text = '';
                    logInfo(`✅ Successfully processed Timeline, cleared text`);
                  } else {
                    logInfo(`📄 JSON parsed but not SBAR cards or Timeline format for message ${index} - type: ${parsedContent.type}, hasComponents: ${!!parsedContent.components}, hasEvents: ${!!parsedContent.events}`);
                  }
                } else {
                  logInfo(`📄 Message ${index} text doesn't look like JSON - startsWith: ${trimmedText?.startsWith('{')}, endsWith: ${trimmedText?.endsWith('}')}, length: ${trimmedText?.length}`);
                }
              } catch (e: any) {
                // Not JSON or not SBAR cards format, continue normally
                logInfo(`📄 Failed to parse JSON for message ${index} - hasSBAR: ${!!msg.sbar_results}, type: ${typeof msg.sbar_results}, parseError: ${e.message}, textPreview: ${msg.text?.substring(0, 50)}`);
              }
            }

            return formattedMessage;
          });
          
          setMessages(formattedMessages);

          // Enhanced logging
          const messagesWithReasoning = formattedMessages.filter((msg: Message) =>
            msg.reasoning || (msg.reasoningSteps && msg.reasoningSteps.length > 0)
          );
          const messagesWithDifferentials = formattedMessages.filter((msg: Message) =>
            msg.differentialDiagnoses && msg.differentialDiagnoses.length > 0
          );
          const messagesWithBoth = formattedMessages.filter((msg: Message) =>
            (msg.reasoning || (msg.reasoningSteps && msg.reasoningSteps.length > 0)) &&
            (msg.differentialDiagnoses && msg.differentialDiagnoses.length > 0)
          );

          logInfo(`📊 Chat history loaded successfully - totalMessages: ${formattedMessages.length}, withReasoning: ${messagesWithReasoning.length}, withDifferentials: ${messagesWithDifferentials.length}, withBoth: ${messagesWithBoth.length}`);
        }
      } else {
        logError(`Failed to load chat history: ${response.status} ${response.statusText}`);
      }
    } catch (error) {
      logError('Failed to load conversation history', error as Error);
    }
  };

    // Only load if we have a patient ID for diagnosis mode or if it's general chat
    if ((mode === 'diagnose' && patientId) || mode === 'chat') {
      loadHistory();
      loadPDFs();
      loadXMLs();
    }
  }, [currentSessionId, patientId, mode, loadPDFs, loadXMLs]);

  // Real-time document updates via SSE (same as chat streaming)
  useEffect(() => {
    if (!((mode === 'diagnose' && patientId) || mode === 'chat')) {
      return;
    }

    logInfo('[ChatBox] Connecting to document events stream...');

    const sessionId = localStorage.getItem('session_id');
    if (!sessionId) {
      logError('[ChatBox] No session ID in localStorage');
      return;
    }

    const eventSource = new EventSource(`/api/documents/events?session_id=${sessionId}`);

    eventSource.onopen = () => {
      logInfo('[ChatBox] Document events connected');
    };

    eventSource.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data);
        logInfo(`[ChatBox] Document event - type: ${data.type}, filename: ${data.filename}`);

        if (data.type === 'uploaded') {
          logInfo(`[ChatBox] Document uploaded: ${data.filename}`);
          // Reload documents to show new upload
          await loadPDFs();
          await loadXMLs();
        }
      } catch (err) {
        logError('[ChatBox] Event parse error', err);
      }
    };

    eventSource.onerror = (error) => {
      logError(`[ChatBox] SSE error - readyState: ${eventSource.readyState}, url: ${eventSource.url}`, error);
      // EventSource auto-reconnects
    };

    return () => {
      logInfo('[ChatBox] Closing document events stream');
      eventSource.close();
    };
  }, [currentSessionId, patientId, mode, loadPDFs, loadXMLs]);

    // Update the final response effect to include differential diagnoses
    useEffect(() => {
    logInfo(`📧 Final response effect - hasFinalResponse: ${!!finalResponse}, isStreaming: ${isStreaming}, hasReasoning: ${!!reasoning}, hasImage: ${!!generatedImage}, hasDifferentials: ${!!streamDifferentialDiagnoses}`);

    if (finalResponse && !isStreaming) {
      logInfo(`✅ Adding final response to messages - reasoning steps: ${reasoning?.length || 0}`);
      setMessages((prev) => {
        const lastMessage = prev[prev.length - 1];
        if (lastMessage && lastMessage.sender === "system" && lastMessage.text === finalResponse) {
          logInfo('⚠️ Duplicate message prevented');
          return prev;
        }
        
        // Convert streaming generatedImage format to Message generatedImage format
        let formattedGeneratedImage: GeneratedImageInfo | undefined = undefined;
        if (generatedImage) {
          formattedGeneratedImage = {
            image_generated: true,
            image_id: generatedImage.image_id,
            image_prompt: generatedImage.prompt,
            generation_metadata: generatedImage.metadata || {},
            model_info: {}
          };
          logInfo(`🖼️ Including generated image in message - image_id: ${sanitizeDocumentId(generatedImage.image_id)}`);
        }

        // Log differential diagnoses being added
        if (streamDifferentialDiagnoses && streamDifferentialDiagnoses.length > 0) {
          logInfo(`🩺 Including differential diagnoses in message - count: ${streamDifferentialDiagnoses.length}`);
        }

        // CRITICAL FIX: Ensure reasoning is properly formatted
        const reasoningText = reasoning && reasoning.length > 0 ? reasoning.join('\n') : '';
        logInfo(`🧠 Final reasoning for message - hasArray: ${!!reasoning}, textLength: ${reasoningText.length}, hasReasoning: ${!!reasoningText}`);
        
        // Check if finalResponse is SBAR, General Summary, Timeline, or Generated Note JSON format and parse it
        let messageText = finalResponse;
        let sbarResults = undefined;
        let generalSummaryResults = undefined;
        let focusedSummaryResults = undefined;
        let focusedAspect = undefined;
        let focusedAspectIcon = undefined;
        let timelineResults = undefined;
        let jsonCitations = undefined; // Extract citations from JSON responses

        try {
          const trimmedText = finalResponse?.trim();
          if (trimmedText && trimmedText.startsWith('{') && trimmedText.endsWith('}')) {
            const parsedContent = JSON.parse(trimmedText);
            logInfo(`🧪 Parsed streaming JSON - type: ${parsedContent.type}`);

            // Extract citations if present in JSON
            if (parsedContent.citations) {
              jsonCitations = parsedContent.citations;
              console.log('📚 Extracted citations from JSON:', jsonCitations);
              console.log('📚 Citation keys from JSON:', Object.keys(jsonCitations));
            }

            if (parsedContent.type === 'generated_note' && parsedContent.content) {
              logInfo(`📝 [NOTE DETECTION] Processing generated note - type: ${parsedContent.type}, templateName: ${parsedContent.template_name}, contentLength: ${parsedContent.content.length}, generation_id: ${parsedContent.generation_id}`);
              // Store the note content and open the dialog
              logInfo(`📝 [NOTE DETECTION] Setting autoGeneratedNote and opening dialog`);
              setAutoGeneratedNote(parsedContent.content);
              setNoteGenerationDialogOpen(true);
              // Show a user-friendly message instead of raw JSON
              messageText = `✅ Generated ${parsedContent.template_name || 'clinical note'} - opening editor...`;
              logInfo(`✅ [NOTE DETECTION] Successfully processed generated note, dialog should open`);
            } else if (parsedContent.type === 'sbar_cards' && parsedContent.components) {
              logInfo(`📋 Processing streaming SBAR cards`);
              sbarResults = {
                situation: parsedContent.components.situation?.content || undefined,
                background: parsedContent.components.background?.content || undefined,
                assessment: parsedContent.components.assessment?.content || undefined,
                recommendation: parsedContent.components.recommendation?.content || undefined
              };
              // Clear the text so we don't display the raw JSON
              messageText = '';
              logInfo(`✅ Successfully processed streaming SBAR cards, cleared text`);
            } else if (parsedContent.type === 'general_summary_cards' && parsedContent.components) {
              logInfo(`📋 Processing streaming General Summary cards`);
              generalSummaryResults = {
                snapshot: parsedContent.components.snapshot?.content || undefined,
                problems: parsedContent.components.problems?.content || undefined,
                medications: parsedContent.components.medications?.content || undefined,
                trends: parsedContent.components.trends?.content || undefined,
                // For encounters, pass the full object with structured_data for clickable encounters
                encounters: parsedContent.components.encounters ? {
                  content: parsedContent.components.encounters.content || '',
                  structured_data: parsedContent.components.encounters.structured_data || []
                } : undefined,
                risks: parsedContent.components.risks?.content || undefined
              };
              // Clear the text so we don't display the raw JSON
              messageText = '';
              logInfo(`✅ Successfully processed streaming General Summary cards, cleared text`);
            } else if (parsedContent.type === 'focused_summary' && parsedContent.sections) {
              logInfo(`🎯 Processing streaming Focused Summary`);
              focusedSummaryResults = {
                diagnoses: parsedContent.sections.diagnoses?.content || undefined,
                events: parsedContent.sections.events?.content || undefined,
                medications: parsedContent.sections.medications?.content || undefined,
                objective_data: parsedContent.sections.objective_data?.content || undefined,
                assessment: parsedContent.sections.assessment?.content || undefined,
                next_steps: parsedContent.sections.next_steps?.content || undefined
              };
              focusedAspect = parsedContent.aspect || "Medical Condition";
              focusedAspectIcon = parsedContent.aspect_icon || "file-text";
              // Clear the text so we don't display the raw JSON
              messageText = '';
              logInfo(`✅ Successfully processed streaming Focused Summary, cleared text`);
            } else if (parsedContent.type === 'timeline_view' && parsedContent.events) {
              logInfo(`📅 Processing streaming Timeline`);
              timelineResults = {
                events: parsedContent.events
              };
              // Clear the text so we don't display the raw JSON
              messageText = '';
              logInfo(`✅ Successfully processed streaming Timeline, cleared text`);
            } else if (parsedContent.type === 'general_response' && parsedContent.content) {
              logInfo(`💬 Processing general response with citations`);
              // Use the content field as the message text (don't clear it)
              messageText = parsedContent.content;
              logInfo(`✅ Successfully processed general response with ${Object.keys(parsedContent.citations || {}).length} citations`);
            }
          }
        } catch (e: any) {
          logInfo(`📄 Failed to parse streaming JSON: ${e.message}`);
        }

        // Use citations from JSON if available, otherwise use streaming citations
        const finalCitations = jsonCitations || streamingCitations || {};

        const newMessage = {
          sender: "system" as const,
          text: messageText,
          timestamp: new Date().toLocaleTimeString(),
          reasoning: reasoningText,
          reasoningSteps: reasoning,
          generatedImage: formattedGeneratedImage,
          differentialDiagnoses: streamDifferentialDiagnoses,
          citations: finalCitations,
          sbarResults: sbarResults,
          generalSummaryResults: generalSummaryResults,
          focusedSummaryResults: focusedSummaryResults,
          focusedAspect: focusedAspect,
          focusedAspectIcon: focusedAspectIcon,
          timelineResults: timelineResults
        };

        console.log('🎯 New message citations (final):', finalCitations);
        console.log('🎯 Citation keys (final):', Object.keys(finalCitations || {}));
        console.log('🎯 Citations from JSON:', jsonCitations);
        console.log('🎯 Citations from streaming:', streamingCitations);
        logInfo(`🔥 Creating new message - hasReasoning: ${!!(newMessage.reasoning || (newMessage.reasoningSteps && newMessage.reasoningSteps.length > 0))}, hasDifferential: ${!!(newMessage.differentialDiagnoses && newMessage.differentialDiagnoses.length > 0)}, hasImage: ${!!newMessage.generatedImage}, hasCitations: ${!!(finalCitations && Object.keys(finalCitations).length > 0)}`);
        
        return [
          ...prev,
          newMessage
        ];
      });
    }
  }, [finalResponse, isStreaming, reasoning, generatedImage, streamDifferentialDiagnoses, streamingCitations]);

  // Handle streaming errors
  useEffect(() => {
    if (streamError) {
      logError(`❌ Stream error: ${streamError}`);
      setMessages((prev) => [
        ...prev,
        {
          sender: "system",
          text: `Error: ${streamError}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  }, [streamError]);

  // Debug logging to see streaming state
  useEffect(() => {
    logInfo(`🖥️ ChatBox streaming state update - isStreaming: ${isStreaming}, streamingResponseLength: ${streamingResponse?.length || 0}, streamingResponsePreview: ${streamingResponse?.substring(0, 50)}..., hasTrimmedContent: ${!!(streamingResponse && streamingResponse.trim())}, currentStep: ${currentStep}, progress: ${progress}`);
  }, [isStreaming, streamingResponse, currentStep, progress]);

  const handleModeChange = (newMode: string, newDefaultPrompt: string) => {
    setInfoRetrievalMode(newMode);
    setDefaultPrompt(newDefaultPrompt);
    setInput(newDefaultPrompt);
  };

  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;

    const userText = input.trim();
    const timestamp = new Date().toLocaleTimeString();
    
    // 1) Add user message
    setMessages((prev) => [
      ...prev, 
      { sender: "user", text: userText, timestamp }
    ]);
    setInput("");

    try {
      // 2) Start streaming
      const endpoint = mode === "chat" ? "/api/chat/stream" : "/api/diagnose/stream";
      const sessionId = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
      
      const payload = { 
        patient_id: patientId ?? null,
        user_prompt: userText,
        chat_mode: mode === "chat",
        diagnostic_mode: mode === "diagnose" ? infoRetrievalMode : "chat",
        user_id: user?.user_id,
        session_id: currentSessionId
      };

      logInfo(`Sending message with diagnostic mode: ${payload.diagnostic_mode}`);
      await startStream(endpoint, payload, sessionId || undefined);

    } catch (error) {
      logError('Streaming error', error as Error);
      setMessages((prev) => [
        ...prev,
        {
          sender: "system",
          text: "Error starting analysis. Please try again.",
          timestamp: new Date().toLocaleTimeString()
        },
      ]);
    }
  };

  // Memoized callbacks for VoiceRecorder to prevent unnecessary re-renders
  const handleInterimTranscript = useCallback((text: string) => {
    // Don't update input during recording - we'll show waveform instead
    if (!isVoiceRecording) {
      setInput(text);
    }
  }, [isVoiceRecording]);

  const handleTranscriptComplete = useCallback((text: string) => {
    logInfo(`[ChatBox] Voice transcript received: ${text.substring(0, 100)}...`);
    setInput(text);
    // Auto-submit after minimal delay (200ms gives user a chance to see/edit if needed)
    setTimeout(() => {
      const formEvent = new Event('submit', { cancelable: true, bubbles: true }) as any;
      sendMessage(formEvent);
    }, 200);
  }, [sendMessage]);

  const handleRecordingStateChange = useCallback((isRecording: boolean) => {
    setIsVoiceRecording(isRecording);
    // Clear input when starting recording
    if (isRecording) {
      setInput('');
    }
  }, []);

  const handleProcessingStateChange = useCallback((isProcessing: boolean) => {
    setIsVoiceProcessing(isProcessing);
  }, []);

  const getPlaceholderText = () => {
    if (mode === "chat") return t('placeholder.chat');
    if (mode === "diagnose" && patientId) {
      return t('placeholder.diagnose');
    }
    return t('placeholder.generic');
  };

  const getEmptyStateText = () => {
    if (mode === "chat") return "CLARA Färdiga Gå!";
    if (mode === "diagnose" && patientId) {
      return "CLARA Färdiga Gå!";
    }
    return "Enter patient details to begin information access...";
  };

  useEffect(() => {
    if (streamingResponse) {
      logInfo(`🔄 ChatBox: streamingResponse updated - length: ${streamingResponse.length}, preview: ${streamingResponse.slice(0, 100)}..., isStreaming: ${isStreaming}`);
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [streamingResponse]);

  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  useAutosizeTextArea(textAreaRef, input);

  // PDF upload handlers
  const handlePDFUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (file.type !== 'application/pdf') {
      setUploadError('Please select a PDF file');
      return;
    }

    if (file.size > 10 * 1024 * 1024) { // 10MB limit
      setUploadError('File size must be less than 10MB');
      return;
    }

    setIsUploadingPDF(true);
    setUploadError(null);

    try {
      logInfo(`[ChatBox] Upload params - patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);
      const uploadResponse = await uploadPDFDocument(file, patientId, currentSessionId);

      logInfo(`[ChatBox] Upload response received - document_id: ${uploadResponse.document_id ? sanitizeDocumentId(uploadResponse.document_id) : 'none'}`);

      // Check if upload was successful - API returns document_id on success
      if (uploadResponse.document_id) {
        logInfo('[ChatBox] Upload successful, refreshing PDF list...');

        // Optimistically add the PDF to the list immediately
        const newPDF: PDFDocument = {
          document_id: uploadResponse.document_id,
          filename: uploadResponse.filename || file.name,
          file_size: uploadResponse.file_size || file.size,
          status: (uploadResponse.status as "UPLOADED" | "PROCESSING" | "READY" | "ERROR") || 'PROCESSING',
          uploaded_at: uploadResponse.uploaded_at || new Date().toISOString(),
          patient_id: uploadResponse.patient_id || patientId,
        };

        setUploadedPDFs(prev => {
          const updated = [...prev, newPDF];
          logInfo(`[ChatBox] Optimistically updated PDF list - count: ${updated.length}`);
          return updated;
        });

        // Force refresh the document lists to get server state
        setTimeout(async () => {
          logInfo('[ChatBox] Refreshing from server...');
          await loadPDFs();
          await loadXMLs();
        }, 1000);

        // Force component re-render by updating refresh counter
        setForceRefresh(prev => prev + 1);

        setMessages(prev => [
          ...prev,
          {
            sender: 'system',
            text: t('documents.pdfUploaded', { filename: file.name }),
            timestamp: new Date().toLocaleTimeString()
          }
        ]);

      } else {
        logError(`[ChatBox] Upload response missing document_id`);
        setUploadError('Upload failed - invalid response from server');
      }
    } catch (error: any) {
      logError('PDF upload error', error as Error);
      setUploadError(error.message || 'Failed to upload PDF');
    } finally {
      setIsUploadingPDF(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleXMLUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const validExtensions = ['.xml', '.hl7', '.cda', '.ccda'];
    const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));

    if (!validExtensions.includes(fileExtension)) {
      setUploadError(`Please select an XML file with one of these extensions: ${validExtensions.join(', ')}`);
      return;
    }

    if (file.size > 100 * 1024 * 1024) { // 100MB limit for XML files
      setUploadError('File size must be less than 100MB');
      return;
    }

    setIsUploadingXML(true);
    setUploadError(null);

    try {
      logInfo(`[ChatBox] XML Upload params - patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);
      const uploadResponse = await uploadXMLDocument(file, patientId, currentSessionId);

      logInfo(`[ChatBox] XML Upload response received - document_id: ${uploadResponse.document_id ? sanitizeDocumentId(uploadResponse.document_id) : 'none'}`);

      // Check if upload was successful - API returns document_id on success
      if (uploadResponse.document_id) {
        logInfo('[ChatBox] XML Upload successful, refreshing document lists...');

        // Optimistically add the XML to the list immediately
        const newXML: XMLDocument = {
          document_id: uploadResponse.document_id,
          filename: uploadResponse.filename || file.name,
          file_size: uploadResponse.file_size || file.size,
          status: (uploadResponse.status as "UPLOADED" | "PROCESSING" | "READY" | "ERROR") || 'PROCESSING',
          uploaded_at: uploadResponse.uploaded_at || new Date().toISOString(),
          patient_id: uploadResponse.patient_id || patientId,
          document_type: uploadResponse.document_type
        };

        setUploadedXMLs(prev => {
          const updated = [...prev, newXML];
          logInfo(`[ChatBox] Optimistically updated XML list - count: ${updated.length}`);
          return updated;
        });

        // Force refresh the document lists to get server state
        setTimeout(async () => {
          logInfo('[ChatBox] Refreshing from server...');
          await loadPDFs();
          await loadXMLs();
        }, 1000);

        // Force component re-render by updating refresh counter
        setForceRefresh(prev => prev + 1);

        const documentTypeText = uploadResponse.document_type ? ` (${uploadResponse.document_type})` : '';
        setMessages(prev => [
          ...prev,
          {
            sender: 'system',
            text: t('documents.xmlUploaded', { filename: file.name, documentType: documentTypeText }),
            timestamp: new Date().toLocaleTimeString()
          }
        ]);

      } else {
        logError(`[ChatBox] XML Upload response missing document_id`);
        setUploadError('XML upload failed - invalid response from server');
      }
    } catch (error: any) {
      logError('XML upload error', error as Error);
      setUploadError(error.message || 'Failed to upload XML document');
    } finally {
      setIsUploadingXML(false);
      if (xmlFileInputRef.current) {
        xmlFileInputRef.current.value = '';
      }
    }
  };

  const handleDeletePDF = async (documentId: string, filename: string) => {
    try {
      logInfo(`[ChatBox] Attempting to delete PDF - documentId: ${sanitizeDocumentId(documentId)}, filename: ${filename}, patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);

      // Show confirmation to user
      if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
        return;
      }

      // Call the delete API with detailed error handling
      logInfo('[ChatBox] Making DELETE request...');
      const deleteResponse = await deletePDFDocument(documentId, patientId, currentSessionId);
      logInfo('[ChatBox] Delete API call completed successfully');

      // Immediately update the local state to reflect the deletion
      setUploadedPDFs(prev => {
        const updated = prev.filter(pdf => pdf.document_id !== documentId);
        logInfo(`[ChatBox] Local state updated. PDF count after delete: ${updated.length}, Remaining PDFs: ${updated.map(pdf => pdf.filename).join(', ')}`);
        return updated;
      });

      // Force component refresh
      setForceRefresh(prev => prev + 1);

      // Verify deletion by refreshing from server
      setTimeout(async () => {
        logInfo('[ChatBox] Verifying deletion by refreshing from server...');
        await loadPDFs();
        await loadXMLs();
      }, 500);

      setMessages(prev => [
        ...prev,
        {
          sender: 'system',
          text: t('documents.pdfRemoved', { filename }),
          timestamp: new Date().toLocaleTimeString()
        }
      ]);

    } catch (error: any) {
      logError(`[ChatBox] PDF delete error - message: ${error.message}, status: ${error.status || 'unknown'}`, error as Error);

      setUploadError(error.message || 'Failed to delete PDF');

      // Don't refresh on error - let user see what happened
      logInfo('[ChatBox] Delete failed, NOT refreshing list to preserve current state');
    }
  };

  const handleDeleteXML = async (documentId: string, filename: string) => {
    try {
      logInfo(`[ChatBox] Attempting to delete XML - documentId: ${sanitizeDocumentId(documentId)}, filename: ${filename}, patientId: ${sanitizePatientId(patientId || null)}, sessionId: ${sanitizeSessionId(currentSessionId)}`);

      // Show confirmation to user
      if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
        return;
      }

      // Call the delete API with detailed error handling
      logInfo('[ChatBox] Making DELETE request for XML...');
      const deleteResponse = await deleteXMLDocument(documentId, patientId, currentSessionId);
      logInfo('[ChatBox] Delete XML API call completed successfully');

      // Immediately update the local state to reflect the deletion
      setUploadedXMLs(prev => {
        const updated = prev.filter(xml => xml.document_id !== documentId);
        logInfo(`[ChatBox] Local XML state updated. XML count after delete: ${updated.length}, Remaining XMLs: ${updated.map(xml => xml.filename).join(', ')}`);
        return updated;
      });

      // Force component refresh
      setForceRefresh(prev => prev + 1);

      // Verify deletion by refreshing from server
      setTimeout(async () => {
        logInfo('[ChatBox] Verifying XML deletion by refreshing from server...');
        await loadPDFs();
        await loadXMLs();
      }, 500);

      setMessages(prev => [
        ...prev,
        {
          sender: 'system',
          text: t('documents.xmlRemoved', { filename }),
          timestamp: new Date().toLocaleTimeString()
        }
      ]);

    } catch (error: any) {
      logError(`[ChatBox] XML delete error - message: ${error.message}, status: ${error.status || 'unknown'}`, error as Error);

      setUploadError(error.message || 'Failed to delete XML document');

      // Don't refresh on error - let user see what happened
      logInfo('[ChatBox] XML Delete failed, NOT refreshing list to preserve current state');
    }
  };

  const triggerFileUpload = () => {
    fileInputRef.current?.click();
  };

  const triggerXMLUpload = () => {
    xmlFileInputRef.current?.click();
  };

  const markdownComponents = {
    // Links
    a: ({ href, children }: any) => (
      <a 
        href={href} 
        target="_blank" 
        rel="noopener noreferrer" 
        className="text-blue-600 hover:text-blue-800 underline font-medium transition-colors duration-200 break-words"
      >
        {children}
        <svg className="w-3 h-3 inline ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
        </svg>
      </a>
    ),
    // Headers
    h1: ({ children }: any) => (
      <h1 className="text-xl font-bold mb-2 text-gray-900">
        {children}
      </h1>
    ),
    h2: ({ children }: any) => (
      <h2 className="text-lg font-bold mb-2 text-gray-900">
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className="text-md font-bold mb-1 text-gray-900">
        {children}
      </h3>
    ),
    // Emphasis
    strong: ({ children }: any) => (
      <strong className="font-bold text-gray-900">
        {children}
      </strong>
    ),
    em: ({ children }: any) => (
      <em className="italic text-gray-900">
        {children}
      </em>
    ),
    // Code
    code: ({ children, className }: any) => {
      const isCodeBlock = className?.includes('language-');
      if (isCodeBlock) {
        return (
          <pre className="bg-gray-800 text-green-400 p-3 rounded-lg overflow-x-auto text-sm my-2">
            <code className="font-mono">{children}</code>
          </pre>
        );
      }
      return (
        <code className="px-1 py-0.5 rounded text-sm font-mono bg-gray-200 text-gray-800">
          {children}
        </code>
      );
    },
    // Lists
    ul: ({ children }: any) => (
      <ul className="list-disc list-inside my-2 space-y-3 text-gray-900">
        {children}
      </ul>
    ),
    ol: ({ children }: any) => (
      <ol className="list-decimal list-inside my-2 space-y-3 text-gray-900">
        {children}
      </ol>
    ),
    li: ({ children }: any) => (
      <li className="text-gray-900 mb-2">
        {children}
      </li>
    ),
    // Paragraphs
    p: ({ children }: any) => (
      <p className="mb-2 last:mb-0 text-gray-900">
        {children}
      </p>
    ),
    // Tables
    table: ({ children }: any) => (
      <div className="overflow-x-auto mb-4 mt-2">
        <table className="min-w-full border-collapse border-2 border-gray-300 bg-white shadow-sm">{children}</table>
      </div>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-gray-100">{children}</thead>
    ),
    tbody: ({ children }: any) => (
      <tbody>{children}</tbody>
    ),
    th: ({ children }: any) => (
      <th className="border border-gray-300 bg-gray-100 px-4 py-3 text-sm font-bold text-gray-900 text-left">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="border border-gray-300 px-4 py-3 text-sm text-gray-700">{children}</td>
    ),
    tr: ({ children }: any) => (
      <tr className="hover:bg-gray-50">{children}</tr>
    ),
  };


  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-0 h-full w-full relative bg-gray-50">
      {/* Chat area with scrollable messages */}
      <div className="flex-1 w-full flex justify-center overflow-y-auto min-h-0 pt-4 pb-[160px]">
        <div className="w-full max-w-4xl px-4 space-y-3">
          {/* Messages */}
          {messages.length === 0 && !isStreaming && (
            <div className="text-center py-8">
              <p className="text-gray-600 font-medium italic">{getEmptyStateText()}</p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={msg.sender === 'user' ? "max-w-[80%]" : "max-w-4xl w-full"}>
                {msg.sender === 'user' ? (
                  <div className="px-3 py-2 text-sm rounded-xl bg-gray-200 text-gray-900 mb-1">
                    <MessageContent text={msg.text} isUser={true} patientId={patientId} sessionId={currentSessionId} citations={msg.citations} />
                  </div>
                ) : (
                  <div className="text-sm text-gray-900 mb-1">
                    <MessageContent text={msg.text} isUser={false} patientId={patientId} sessionId={currentSessionId} citations={msg.citations} />
                  </div>
                )}

                {msg.generatedImage && <GeneratedImageDisplay imageInfo={msg.generatedImage} />}

                {msg.sender === 'system' && msg.differentialDiagnoses && msg.differentialDiagnoses?.length > 0 && (
                  <div className="mt-3">
                    <DifferentialDiagnosisCards diagnoses={msg.differentialDiagnoses} />
                  </div>
                )}

                {msg.sender === 'system' && msg.sbarResults && (
                  <div className="mt-3">
                    <SBARSummaryCards
                      sbarResults={msg.sbarResults}
                      isLoading={msg.loading}
                      reasoning={msg.reasoning}
                      reasoningSteps={msg.reasoningSteps}
                      patientId={patientId}
                      sessionId={sessionId}
                      citations={msg.citations}
                    />
                  </div>
                )}

                {msg.sender === 'system' && msg.generalSummaryResults && (
                  <div className="mt-3">
                    <GeneralSummaryCards
                      summaryResults={msg.generalSummaryResults}
                      isLoading={msg.loading}
                      reasoning={msg.reasoning}
                      reasoningSteps={msg.reasoningSteps}
                      patientId={patientId}
                      sessionId={sessionId}
                      citations={msg.citations}
                    />
                  </div>
                )}

                {msg.sender === 'system' && msg.focusedSummaryResults && (
                  <div className="mt-3">
                    <FocusedSummaryCards
                      summaryResults={msg.focusedSummaryResults}
                      aspect={msg.focusedAspect || "Medical Condition"}
                      aspectIcon={msg.focusedAspectIcon || "file-text"}
                      isLoading={msg.loading}
                      patientId={patientId}
                      sessionId={sessionId}
                      citations={msg.citations}
                    />
                  </div>
                )}

                {msg.sender === 'system' && msg.timelineResults && (
                  <div className="mt-3">
                    <TimelineView
                      events={msg.timelineResults.events}
                      isLoading={msg.loading}
                      patientId={patientId}
                      sessionId={sessionId}
                      citations={msg.citations}
                    />
                  </div>
                )}

                {msg.sender === 'system' && msg.reasoningSteps && (msg.reasoning || msg.reasoningSteps?.length > 0) && !msg.sbarResults && !msg.timelineResults && (
                  <div className="mt-3">
                    <ReasoningViewer
                      reasoning={msg.reasoning || ''}
                      reasoningSteps={msg.reasoningSteps}
                    />
                  </div>
                )}

                {msg.timestamp && (
                  <div
                    className={`text-xs mt-1 ${
                      msg.sender === 'user' ? 'text-right text-gray-500' : 'text-left text-gray-500'
                    }`}
                  >
                    {msg.timestamp}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Streaming response display - show when we have streaming content (but hide JSON note responses) */}
          {(() => {
            // Check if streaming response is a note generation JSON (hide it if so)
            if (isStreaming && streamingResponse && streamingResponse.trim()) {
              const trimmed = streamingResponse.trim();
              // Don't display if it's JSON note response - dialog will handle it
              if (trimmed.startsWith('{') && trimmed.includes('"type": "generated_note"')) {
                return null;
              }

              return (
                <div className="flex justify-start mb-4">
                  <div className="max-w-4xl w-full">
                    <div className="text-sm text-gray-900 mb-1">
                      <div className="rounded-2xl px-4 py-3 bg-white border border-gray-200 shadow-sm">
                        <div className="text-sm leading-relaxed text-gray-900">
                          <MarkdownWithCitations
                            content={streamingResponse}
                            citations={streamingCitations || {}}
                            components={markdownComponents}
                          />
                          <span className="inline-block w-2 h-5 bg-blue-600 animate-pulse ml-1" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            }
            return null;
          })()}

          {/* Streaming progress bar - show when streaming, or when differential diagnosis is computing, or when note generation is in progress */}
          {(() => {
            // Check if we're generating a note (streaming response contains note JSON)
            const isGeneratingNote = streamingResponse && streamingResponse.trim().includes('"type": "generated_note"');

            return ((isStreaming && (!streamingResponse || !streamingResponse.trim() || isGeneratingNote)) ||
             differentialDiagnosisProgress?.isComputing ||
             (differentialDiagnosisProgress?.currentDiagnosis && differentialDiagnosisProgress.currentDiagnosis.trim() !== '') ||
             noteGenerationProgress?.isGenerating ||
             (currentStep && (currentStep.toLowerCase().includes('note') || currentStep.toLowerCase().includes('template')))) ? (
              <StreamingProgress
                isStreaming={isStreaming}
                currentStep={isGeneratingNote ? 'Generating Clinical Note' : currentStep}
                currentDescription={isGeneratingNote ? 'Finalizing note content...' : currentDescription}
                progress={progress}
                reasoning={reasoning}
                currentReasoning={currentReasoning}
                differentialDiagnosisProgress={differentialDiagnosisProgress}
              />
            ) : null;
          })()}

          {/* Auto-scroll anchor */}
          <div ref={messagesEndRef} />
          {/* Spacer to ensure last message is visible above input bar */}
          <div style={{ height: 60 }} aria-hidden="true" />
        </div>
      </div>

      {/* Centered ChatGPT-style input bar */}
      <div className="absolute bottom-4 left-0 right-0 px-4 z-20 pointer-events-none flex justify-center">
        <div className="w-full max-w-3xl pointer-events-auto">
          {/* Upload Error Display */}
          {uploadError && (
            <div className="mb-2">
              <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                <X className="h-4 w-4" />
                <span>{uploadError}</span>
                <button
                  type="button"
                  onClick={() => setUploadError(null)}
                  className="ml-auto text-red-500 hover:text-red-700"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* ChatGPT-style text input */}
          <div className="border border-gray-300 bg-white shadow-lg rounded-2xl">
            <form onSubmit={sendMessage} className="flex items-end gap-2 px-4 py-2">
              {isVoiceRecording ? (
                /* Show waveform during recording */
                <div className="flex-1" style={{ minHeight: '64px' }}>
                  <LiveWaveform
                    active={isVoiceRecording}
                    processing={false}
                    mode="static"
                    height={64}
                    barWidth={3}
                    barGap={1}
                    barRadius={1.5}
                    fadeEdges={true}
                    fadeWidth={24}
                    sensitivity={1.2}
                    className="w-full"
                  />
                </div>
              ) : (
                /* Show textarea when not recording */
                <textarea
                  ref={textAreaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={getPlaceholderText()}
                  className="flex-1 resize-none overflow-hidden border-0 bg-transparent placeholder-gray-400
                            text-gray-900 focus:outline-none text-base leading-relaxed max-h-32"
                  disabled={isStreaming || isVoiceProcessing}
                  rows={1}
                  style={{ minHeight: '24px' }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage(e as any);
                    }
                  }}
                />
              )}
              <div className="flex items-center gap-1 pb-1">
                {/* Voice Recorder */}
                <VoiceRecorder
                  onInterimTranscript={handleInterimTranscript}
                  onTranscriptComplete={handleTranscriptComplete}
                  onRecordingStateChange={handleRecordingStateChange}
                  onProcessingStateChange={handleProcessingStateChange}
                  disabled={isStreaming}
                  language={locale === 'sv' ? 'sv' : 'en'}
                />

                <button
                  type="submit"
                  disabled={!input.trim() || isStreaming}
                  className="p-1.5 bg-black text-white rounded-full hover:bg-gray-800 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  {isStreaming ? (
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                    </svg>
                  )}
                </button>
                {isStreaming && (
                  <button
                    type="button"
                    onClick={stopStream}
                    className="p-1.5 bg-gray-600 text-white rounded-full hover:bg-gray-700 transition-colors"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h12v12H6z" />
                    </svg>
                  </button>
                )}
              </div>
            </form>
          </div>

          {/* Hidden file inputs */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={handlePDFUpload}
            className="hidden"
          />
          <input
            ref={xmlFileInputRef}
            type="file"
            accept=".xml,.hl7,.cda,.ccda,application/xml,text/xml"
            onChange={handleXMLUpload}
            className="hidden"
          />
        </div>
      </div>

      {/* Separate Document Library - Top Right Corner */}
      <div className="absolute top-4 right-4 z-20 w-64 pointer-events-auto" key={`docs-${forceRefresh}-${uploadedPDFs.length}-${uploadedXMLs.length}`}>
        <div className="flex flex-col gap-1.5">
          {/* Document Library - Ultra Compact */}
          <div className="border border-gray-300 bg-white shadow-sm rounded-lg">
            <div className="px-2 py-1.5 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-gray-700 flex items-center gap-1">
                  <FileText className="h-3 w-3 text-blue-600" />
                  {t('documents.title')} ({uploadedPDFs.length + uploadedXMLs.length})
                </div>
                {(uploadedPDFs.length + uploadedXMLs.length) > 0 && (
                  <div className="text-xs text-gray-500">
                    {uploadedPDFs.filter(pdf => pdf.status === 'READY').length + uploadedXMLs.filter(xml => xml.status === 'READY').length} {t('documents.ready')}
                  </div>
                )}
              </div>
            </div>

            <div className="max-h-24 overflow-y-auto">
              {(uploadedPDFs.length + uploadedXMLs.length) > 0 ? (
                <div className="p-1.5 space-y-1">
                  {/* PDF Documents */}
                  {uploadedPDFs.map((pdf) => (
                    <div key={`pdf-${pdf.document_id}`} className="flex items-center justify-between p-1 bg-gray-50 rounded text-xs">
                      <div className="flex items-center gap-1 flex-1 min-w-0">
                        <FileText className="h-2.5 w-2.5 text-blue-600 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-gray-900 truncate" title={pdf.filename}>
                            {pdf.filename}
                          </div>
                          <div className="text-gray-500 text-xs">
                            {(pdf.file_size / 1024).toFixed(0)}KB
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className={`w-2 h-2 rounded-full ${
                          pdf.status === 'READY' ? 'bg-green-500' :
                          pdf.status === 'PROCESSING' ? 'bg-yellow-500' :
                          pdf.status === 'ERROR' ? 'bg-red-500' :
                          'bg-gray-400'
                        }`} title={pdf.status}></span>
                        <button
                          type="button"
                          onClick={() => handleDeletePDF(pdf.document_id, pdf.filename)}
                          className="p-0.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded transition-colors"
                          title={`Remove ${pdf.filename}`}
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </div>
                  ))}

                  {/* XML Documents */}
                  {uploadedXMLs.map((xml) => (
                    <div key={`xml-${xml.document_id}`} className="flex items-center justify-between p-1 bg-green-50 rounded text-xs">
                      <div className="flex items-center gap-1 flex-1 min-w-0">
                        <FileText className="h-2.5 w-2.5 text-green-600 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-gray-900 truncate" title={xml.filename}>
                            {xml.filename}
                          </div>
                          <div className="text-gray-500 text-xs">
                            {(xml.file_size / 1024).toFixed(0)}KB
                            {xml.document_type && ` • ${xml.document_type}`}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className={`w-2 h-2 rounded-full ${
                          xml.status === 'READY' ? 'bg-green-500' :
                          xml.status === 'PROCESSING' ? 'bg-yellow-500' :
                          xml.status === 'ERROR' ? 'bg-red-500' :
                          'bg-gray-400'
                        }`} title={xml.status}></span>
                        <button
                          type="button"
                          onClick={() => handleDeleteXML(xml.document_id, xml.filename)}
                          className="p-0.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded transition-colors"
                          title={`Remove ${xml.filename}`}
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-2 text-gray-500">
                  <FileText className="h-3 w-3 mx-auto mb-1 text-gray-300" />
                  <div className="text-xs">No documents</div>
                </div>
              )}
            </div>
          </div>

          {/* Upload Buttons */}
          <div className="flex gap-1.5">
            {/* PDF Upload Button */}
            <button
              type="button"
              onClick={triggerFileUpload}
              disabled={isStreaming || isUploadingPDF}
              className="flex-1 px-2 py-1.5 bg-blue-100 text-blue-700 font-medium rounded-lg hover:bg-blue-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 border border-blue-300 shadow-sm text-xs"
              title="Upload PDF document"
            >
              {isUploadingPDF ? (
                <div className="animate-spin h-3 w-3 border-2 border-blue-600 border-t-transparent rounded-full" />
              ) : (
                <FileText className="h-3 w-3" />
              )}
              PDF
            </button>

            {/* XML Upload Button */}
            <button
              type="button"
              onClick={triggerXMLUpload}
              disabled={isStreaming || isUploadingXML}
              className="flex-1 px-2 py-1.5 bg-green-100 text-green-700 font-medium rounded-lg hover:bg-green-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 border border-green-300 shadow-sm text-xs"
              title="Upload XML document (HL7, CDA, FHIR, or generic XML)"
            >
              {isUploadingXML ? (
                <div className="animate-spin h-3 w-3 border-2 border-green-600 border-t-transparent rounded-full" />
              ) : (
                <FileText className="h-3 w-3" />
              )}
              XML
            </button>
          </div>
        </div>
      </div>

      {/* Right-side mode selector - only show if info mode is enabled and we're in diagnose mode */}
      {isInfoModeEnabled && mode === "diagnose" && (
        <div className="absolute right-4 top-40 z-30 pointer-events-auto">
          <div className="p-3 border border-gray-300 bg-white/90 backdrop-blur-md shadow-xl rounded-xl">
            <ModeSelector
              selectedMode={infoRetrievalMode}
              onModeChange={handleModeChange}
              disabled={isStreaming}
              layout="vertical"
            />
          </div>
        </div>
      )}

      {/* Note Generation Dialog - Used for auto-generated notes from chat interface */}
      <NoteGenerationDialog
        open={noteGenerationDialogOpen}
        onOpenChange={(open) => {
          setNoteGenerationDialogOpen(open);
          if (!open) {
            // Clear auto-generated note when dialog closes
            setAutoGeneratedNote(null);
          }
        }}
        patientId={patientId}
        sessionId={sessionId}
        initialNote={autoGeneratedNote}
        onNoteGenerated={(noteContent) => {
          // Add the generated note to messages as confirmation
          setMessages((prev) => [
            ...prev,
            {
              sender: "system",
              text: "✅ Note generated and copied to clipboard successfully!",
              timestamp: new Date().toLocaleTimeString(locale, {
                hour: '2-digit',
                minute: '2-digit'
              }),
            },
          ]);
        }}
      />
    </div>
  );
}

export { ChatBox as default };