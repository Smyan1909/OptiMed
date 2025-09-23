import { useState, useRef } from 'react';
import { useTranslations } from 'next-intl';
import React from 'react';

export interface UseLookupProps {
  patientId?: string;
  sessionId?: string | null;
}

export interface UseLookupReturn {
  selection: string;
  lookupTerm: string;
  showLookup: boolean;
  contentRef: React.RefObject<HTMLDivElement>;
  handleTouchEnd: (e: React.TouchEvent | React.MouseEvent) => void;
  handleMouseUp: () => void;
  handleKeyUp: () => void;
  setLookupTerm: (term: string) => void;
  setShowLookup: (show: boolean) => void;
  LookupButton: React.FC;
  closeLookup: () => void;
}

export function useLookup({ }: UseLookupProps = {}): UseLookupReturn {
  const [selection, setSelection] = useState<string>("");
  const [lookupTerm, setLookupTerm] = useState<string>("");
  const [showLookup, setShowLookup] = useState<boolean>(false);
  const tChatBox = useTranslations('chatBox');

  const contentRef = useRef<HTMLDivElement>(null);

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

  const getWordAtPoint = (evt: React.TouchEvent | React.MouseEvent): string => {
    const container = contentRef.current;
    if (!container) return "";

    let x = 0, y = 0;
    if ('changedTouches' in evt && evt.changedTouches?.length) {
      x = evt.changedTouches[0].clientX;
      y = evt.changedTouches[0].clientY;
    } else if ('clientX' in evt) {
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
      if (node.childNodes?.length) {
        const idx = Math.min(offset, node.childNodes.length - 1);
        candidate = node.childNodes[idx] || node.firstChild;
      }
      while (candidate && candidate.nodeType !== Node.TEXT_NODE && candidate.firstChild) {
        candidate = candidate.firstChild;
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

  const handleTouchEnd = (e: React.TouchEvent | React.MouseEvent) => {
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
  const handleKeyUp = () => updateSelection();

  const closeLookup = () => setShowLookup(false);

  const LookupButton: React.FC = () => {
    if (!selection || selection.length < 2) return null;

    return (
      <div className="mt-2">
        <button
          type="button"
          onMouseDown={(e: React.MouseEvent) => { e.stopPropagation(); }}
          onMouseUp={(e: React.MouseEvent) => { e.stopPropagation(); }}
          onTouchStart={(e: React.TouchEvent) => { e.stopPropagation(); }}
          onTouchEnd={(e: React.TouchEvent) => { e.stopPropagation(); }}
          onPointerDown={(e: React.PointerEvent) => { e.stopPropagation(); }}
          onPointerUp={(e: React.PointerEvent) => { e.stopPropagation(); }}
          onClick={() => { setLookupTerm(selection); setShowLookup(true); }}
          className="px-2 py-1 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700"
        >
          {tChatBox('lookup.action', { term: selection, default: `Lookup "${selection}"` })}
        </button>
      </div>
    );
  };

  return {
    selection,
    lookupTerm,
    showLookup,
    contentRef,
    handleTouchEnd,
    handleMouseUp,
    handleKeyUp,
    setLookupTerm,
    setShowLookup,
    LookupButton,
    closeLookup,
  };
}