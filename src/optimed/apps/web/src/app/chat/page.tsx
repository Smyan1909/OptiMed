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
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          {/* Breadcrumb */}
          <nav className="flex mb-6" aria-label="Breadcrumb">
            <ol className="flex items-center space-x-4">
              <li>
                <Link href="/patients" className="text-blue-600 hover:text-blue-800 font-medium">
                  Patients
                </Link>
              </li>
              <li>
                <span className="text-gray-400">/</span>
              </li>
              <li>
                <span className="text-gray-900 font-medium">General Chat</span>
              </li>
            </ol>
          </nav>

          {/* Page Header */}
          <div className="mb-8">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-gray-900">Chat with CLARA</h1>
                <p className="mt-2 text-gray-600">
                  Welcome back, {user?.display_name}. Have a general conversation with your AI assistant.
                </p>
              </div>
              <div className="flex items-center space-x-3">
                <Link href="/patients">
                  <button className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors">
                    ← Back to Patients
                  </button>
                </Link>
                <Badge variant="success" className="text-sm px-3 py-1">
                  General Chat
                </Badge>
              </div>
            </div>
          </div>

          {/* Chat Interface */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-6 py-4 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-bold text-gray-900">AI Chat Assistant</h2>
                  <p className="text-sm text-gray-700 font-medium">General health assistant - No specific patient context</p>
                </div>
                <div className="flex items-center space-x-2">
                  <Badge variant="default" className="px-3 py-1">
                    CLARA
                  </Badge>
                  <Badge variant="outline" className="px-3 py-1">
                    {user?.display_name}
                  </Badge>
                </div>
              </div>
            </div>
            
            {/* Sessions and Chat Layout */}
            <div className="flex h-[600px]">
              {/* Sessions List Sidebar */}
              <SessionsList
                key={sessionsKey}
                patientId={undefined} // No patient for general chat
                selectedSessionId={selectedSessionId}
                onSessionSelect={handleSessionSelect}
                onNewSession={handleNewSession}
                mode="chat"
              />
              
              {/* Chat Area */}
              <div className="flex-1 flex flex-col">
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