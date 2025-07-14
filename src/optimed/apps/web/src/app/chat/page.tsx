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
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <Header />
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Breadcrumb - kompakt */}
          <nav className="flex mb-2 px-6 pt-4 flex-shrink-0" aria-label="Breadcrumb">
            <ol className="flex items-center space-x-4">
              <li>
                <Link href="/patients" className="text-blue-600 hover:text-blue-800 font-medium">
                  Patients
                </Link>
              </li>
            </ol>
          </nav>

          {/* Page Header - kompakt */}
          <div className="px-6 py-4 border-b border-gray-200 flex-shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Chat with CLARA</h1>
                <p className="mt-1 text-sm text-gray-600">
                  Welcome back, {user?.display_name}. Have a general conversation with your AI assistant.
                </p>
              </div>
              <div className="flex items-center space-x-3">
                <div className="text-right mr-4">
                  <div className="text-sm text-gray-600">
                    Chatting as <span className="font-semibold">{user?.display_name}</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    {user?.role} • General consultation mode
                  </div>
                </div>
                <Link href="/patients">
                  <button className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors">
                    ← Back to Patients
                  </button>
                </Link>
              </div>
            </div>
          </div>

          {/* Chat Interface - tar resten av skärmen */}
          <div className="bg-white flex-1 flex flex-col min-h-0 overflow-hidden">
            <div className="px-6 py-2 border-b border-gray-200 flex-shrink-0">
              <button
                onClick={() => setShowSessions(!showSessions)}
                className="flex items-center space-x-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  {showSessions ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                  )}
                </svg>
                <span>{showSessions ? 'Hide Sessions' : 'Show Sessions'}</span>
              </button>
            </div>
            
            {/* Sessions and Chat Layout - tar hela återstående utrymmet */}
            <div className="flex flex-1 min-h-0 overflow-hidden">
              {showSessions && (
                <SessionsList
                  key={sessionsKey}
                  patientId={undefined} // No patient for general chat
                  selectedSessionId={selectedSessionId}
                  onSessionSelect={handleSessionSelect}
                  onNewSession={handleNewSession}
                  mode="chat"
                />
              )}
              
              {/* Chat Area - tar upp resten av utrymmet */}
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                <ChatBox 
                  key={chatKey}
                  mode="chat" 
                  patientId={undefined} // No patient for general chat
                  sessionId={selectedSessionId}
                />
              </div>
            </div>
          </div>
        </div>
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