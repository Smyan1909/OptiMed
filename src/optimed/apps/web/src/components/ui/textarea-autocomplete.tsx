'use client';

import React, { useRef, useCallback, KeyboardEvent, ChangeEvent } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { useJournalAutocomplete } from '@/hooks/useJournalAutocomplete';
import { JournalEntryType } from '@/lib/api';
import { cn } from '@/lib/utils';

interface TextareaAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  entryType: JournalEntryType;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  className?: string;
  required?: boolean;
  id?: string;
}

export function TextareaAutocomplete({
  value,
  onChange,
  entryType,
  placeholder,
  disabled = false,
  rows = 16,
  className,
  required,
  id
}: TextareaAutocompleteProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  
  const {
    suggestion,
    isLoading,
    getSuggestion,
    applySuggestion,
    clearSuggestion
  } = useJournalAutocomplete({
    entryType,
    onTextChange: onChange
  });

  const handleTextChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    const cursorPosition = e.target.selectionStart;
    
    onChange(newValue);
    
    // Get suggestion for new text
    if (!disabled) {
      getSuggestion(newValue, cursorPosition);
    }
  }, [onChange, getSuggestion, disabled]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Handle Tab key for autocomplete
    if (e.key === 'Tab' && suggestion && !e.shiftKey) {
      e.preventDefault();
      const cursorPosition = textarea.selectionStart;
      const newText = applySuggestion(value, cursorPosition);
      onChange(newText);
      
      // Move cursor to end of applied suggestion
      setTimeout(() => {
        const newCursorPosition = cursorPosition + suggestion.length + (value[cursorPosition - 1] !== ' ' ? 1 : 0);
        textarea.setSelectionRange(newCursorPosition, newCursorPosition);
      }, 0);
    }
    
    // Clear suggestion on other keys
    else if (e.key === 'Escape' || e.key === 'Enter') {
      clearSuggestion();
    }
  }, [suggestion, applySuggestion, value, onChange, clearSuggestion]);

  const handleBlur = useCallback(() => {
    // Clear suggestion when textarea loses focus
    setTimeout(() => {
      clearSuggestion();
    }, 100);
  }, [clearSuggestion]);

  const handleFocus = useCallback(() => {
    // Get suggestion when textarea gains focus
    const textarea = textareaRef.current;
    if (textarea && value) {
      getSuggestion(value, textarea.selectionStart);
    }
  }, [getSuggestion, value]);

  return (
    <div className="relative">
      <Textarea
        ref={textareaRef}
        id={id}
        value={value}
        onChange={handleTextChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onFocus={handleFocus}
        placeholder={placeholder}
        disabled={disabled}
        rows={rows}
        required={required}
        className={cn("font-mono text-sm resize-none", className)}
      />
      
      {/* Suggestion Overlay */}
      {suggestion && !disabled && (
        <div className="absolute top-2 right-2 z-10">
          <div className="bg-blue-50 border border-blue-200 rounded-md px-3 py-1 text-sm text-blue-800 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-blue-600">Tab to complete:</span>
              <span className="font-medium">{suggestion}</span>
              {isLoading && (
                <div className="animate-spin h-3 w-3 border border-blue-500 border-t-transparent rounded-full" />
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* Help Text */}
      <div className="mt-1 text-xs text-gray-500 flex items-center gap-1">
        <span>💡</span>
        <span>Press <kbd className="px-1 py-0.5 text-xs bg-gray-100 border rounded">Tab</kbd> to accept suggestions</span>
      </div>
    </div>
  );
}