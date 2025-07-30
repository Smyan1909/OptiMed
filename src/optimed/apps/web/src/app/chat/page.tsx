"use client";

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useState } from 'react';
import Link from 'next/link';
import ChatBox from "@/components/ChatBox";
import SessionsList from "@/components/SessionsList";
import { useUser } from '@/contexts/UserContext';
import { Badge } from '@/components/ui/badge';

function ChatPageContent() {
  const { user } = useUser();
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>(undefined);
  const [chatKey, setChatKey] = useState(0); // Force ChatBox re-render
  const [sessionsKey, setSessionsKey] = useState(0); // Force SessionsList re-render
  const [showSessions, setShowSessions] = useState(true); // Toggle sessions visibility

  const handleSessionSelect = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    setChatKey(prev => prev + 1); // Force ChatBox to reload with new session
  };

  const handleNewSession = () => {
    setSelectedSessionId(undefined);
    setChatKey(prev => prev + 1); // Force ChatBox to reset for new session
    setSessionsKey(prev => prev + 1); // Force SessionsList to reload
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-50">
      <Header />

      <main className="relative flex flex-1 overflow-hidden">
        {/* Sidebar toggle button */}
        <button
          onClick={() => setShowSessions(!showSessions)}
          className={`absolute top-3 z-30
                      ${showSessions ? 'left-[20.25rem]' : 'left-3'}
                      bg-white/10 backdrop-blur-md border shadow
                      rounded-full hover:bg-white transition-colors
                      flex items-center justify-center
                      h-8 w-8 hover:bg-white/70 transition-colors`}
          title={showSessions ? 'Hide sessions panel' : 'Show sessions panel'}
        >
          <svg
            className="w-4 h-4 text-gray-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            {showSessions ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            )}
          </svg>
        </button>

        {/* Sidebar */}
        {showSessions && (
          <aside className="w-80 flex-shrink-0 border-r border-gray-200 flex flex-col overflow-y-auto bg-white">
            <div className="p-3 bg-gradient-to-r from-blue-50 to-white border-b border-gray-200 shadow-sm">
              <div className="flex items-start space-x-3">
                <div className="h-12 w-12 bg-blue-100 rounded-full flex items-center justify-center shadow text-blue-600 font-bold">
                  {user?.display_name?.slice(0, 2) || "AI"}
                </div>
                <div className="flex-1">
                  <h2 className="text-lg font-bold text-gray-900">{user?.display_name || "AI User"}</h2>
                  <div className="mt-1 text-[10px] text-gray-500">
                    General Chat
                  </div>
                </div>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              <SessionsList
                key={sessionsKey}
                patientId={undefined}
                selectedSessionId={selectedSessionId}
                onSessionSelect={handleSessionSelect}
                onNewSession={handleNewSession}
                mode="chat"
              />
            </div>
          </aside>
        )}

        {/* Chat area */}
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