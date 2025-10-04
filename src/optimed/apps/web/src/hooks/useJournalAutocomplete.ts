import { useState, useCallback, useRef } from 'react';
import { getJournalAutocomplete, JournalEntryType } from '@/lib/api';
import { logError } from '@/lib/logger';

interface UseJournalAutocompleteProps {
  entryType: JournalEntryType;
  onTextChange: (text: string) => void;
}

export function useJournalAutocomplete({ entryType, onTextChange }: UseJournalAutocompleteProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [suggestion, setSuggestion] = useState<string>('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const getSuggestion = useCallback(async (text: string, cursorPosition: number) => {
    // Cancel previous request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Clear previous timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Don't suggest for very short text
    if (text.trim().length < 10) {
      setSuggestion('');
      return;
    }

    // Debounce the request
    timeoutRef.current = setTimeout(async () => {
      try {
        setIsLoading(true);
        
        const controller = new AbortController();
        abortControllerRef.current = controller;

        const response = await getJournalAutocomplete({
          text,
          entry_type: entryType,
          cursor_position: cursorPosition,
          max_tokens: 50
        });

        if (!controller.signal.aborted && response.completion) {
          setSuggestion(response.completion);
        }
      } catch (error) {
        if (!abortControllerRef.current?.signal.aborted) {
          logError('useJournalAutocomplete: Autocomplete error', error);
          setSuggestion('');
        }
      } finally {
        setIsLoading(false);
      }
    }, 500); // 500ms debounce
  }, [entryType]);

  const applySuggestion = useCallback((currentText: string, cursorPosition: number) => {
    if (!suggestion) return currentText;

    const beforeCursor = currentText.substring(0, cursorPosition);
    const afterCursor = currentText.substring(cursorPosition);
    
    // Add a space before the suggestion if needed
    const needsSpace = beforeCursor.length > 0 && !beforeCursor.endsWith(' ') && !suggestion.startsWith(' ');
    const finalSuggestion = needsSpace ? ' ' + suggestion : suggestion;
    
    const newText = beforeCursor + finalSuggestion + afterCursor;
    setSuggestion('');
    return newText;
  }, [suggestion]);

  const clearSuggestion = useCallback(() => {
    setSuggestion('');
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
  }, []);

  return {
    suggestion,
    isLoading,
    getSuggestion,
    applySuggestion,
    clearSuggestion
  };
}