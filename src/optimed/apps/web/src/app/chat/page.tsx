"use client";

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useState } from 'react';
import Link from 'next/link';
import ChatBox from "@/components/ChatBox";
import { useUser } from '@/contexts/UserContext';
import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';
import { Plus } from 'lucide-react';

function ChatPageContent() {
  const { user } = useUser();
  const t = useTranslations('chatPage');
  const tc = useTranslations('common');
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>(undefined);
  const [chatKey, setChatKey] = useState(0); // Force ChatBox re-render

  const handleNewSession = async () => {
    // Clear the localStorage session to force a new session ID
    if (typeof window !== 'undefined') {
      const sessionKey = `chat_session_chat_general`; // Match the key format from ChatBox.tsx
      const oldSessionId = localStorage.getItem(sessionKey);

      // Store old session ID for ChatBox to clean up when it remounts
      // This is critical because changing chatKey unmounts/remounts ChatBox, resetting all refs
      if (oldSessionId) {
        const cleanupKey = `cleanup_old_session_chat_general`;
        localStorage.setItem(cleanupKey, oldSessionId);
        console.log('[ChatPage] Stored old session ID for cleanup:', oldSessionId);
      }

      // Call backend to clear session memory
      if (oldSessionId) {
        try {
          const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
          console.log('[ChatPage] 🔄 Attempting to clear backend session:', oldSessionId);
          console.log('[ChatPage] API URL:', `${API_BASE_URL}/chat/sessions/${oldSessionId}`);

          const response = await fetch(`${API_BASE_URL}/chat/sessions/${oldSessionId}`, {
            method: 'DELETE',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
            },
          });

          console.log('[ChatPage] Response status:', response.status);

          if (response.ok) {
            const data = await response.json();
            console.log('[ChatPage] ✓ Backend session cleared:', data);
            console.log('[ChatPage]   - Cleared memory:', data.cleared_memory);
            console.log('[ChatPage]   - Cleared cache:', data.cleared_cache);
          } else {
            const errorText = await response.text();
            console.warn('[ChatPage] ⚠ Failed to clear backend session (status ' + response.status + '):', errorText);
            console.warn('[ChatPage] Continuing with frontend-only clear...');
          }
        } catch (error) {
          console.error('[ChatPage] ✗ Error clearing backend session:', error);
          console.warn('[ChatPage] Continuing with frontend-only clear...');
          // Continue anyway - frontend will still create new session
        }

        // Clear the session start time and messages for the old session
        const startTimeKey = `session_start_time_${oldSessionId}`;
        const messagesKey = `chat_messages_${oldSessionId}`;
        localStorage.removeItem(startTimeKey);
        localStorage.removeItem(messagesKey);
        console.log('[ChatPage] Cleared session start time and messages from localStorage');
      }

      // Clear the session ID
      localStorage.removeItem(sessionKey);
      console.log('[ChatPage] Cleared session from localStorage');
    }

    setSelectedSessionId(undefined);
    setChatKey(prev => prev + 1); // Force ChatBox to reset for new session
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-50">
      <Header />

      <main className="relative flex flex-1 overflow-hidden">
        {/* New Session Button - Top Left */}
        <button
          onClick={() => {
            console.log('[ChatPage] ========== NEW SESSION BUTTON CLICKED ==========');
            console.log('[ChatPage] Button onclick fired at:', new Date().toISOString());
            handleNewSession();
          }}
          className="absolute top-4 left-4 z-30
                     bg-blue-600 hover:bg-blue-700 text-white
                     px-4 py-2 rounded-lg shadow-lg
                     flex items-center gap-2
                     transition-colors duration-200
                     font-medium text-sm"
          title={t('newSession')}
        >
          <Plus className="h-4 w-4" />
          {t('newSession')}
        </button>

        {/* Chat area - Full width */}
        <section className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <ChatBox
            key={chatKey}
            mode="chat"
            patientId={undefined}
            sessionId={selectedSessionId}
          />
        </section>
      </main>
    </div>
  );
}

export default function ChatPage() {
  return (
    <ProtectedRoute>
      <ChatPageContent />
    </ProtectedRoute>
  );
}