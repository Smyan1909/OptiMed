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

  const handleNewSession = () => {
    setSelectedSessionId(undefined);
    setChatKey(prev => prev + 1); // Force ChatBox to reset for new session
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-50">
      <Header />

      <main className="relative flex flex-1 overflow-hidden">
        {/* New Session Button - Top Left */}
        <button
          onClick={handleNewSession}
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