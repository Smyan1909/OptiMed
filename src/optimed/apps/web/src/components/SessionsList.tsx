'use client';

import React, { useState, useEffect } from 'react';
import { useUser } from '@/contexts/UserContext';
import { listSessions, createSession, joinSession, Session, SessionListRequest } from '@/lib/api';
import { formatDistanceToNow } from 'date-fns';

interface SessionsListProps {
  patientId?: string;
  selectedSessionId?: string;
  onSessionSelect: (sessionId: string) => void;
  onNewSession: () => void;
  mode: 'chat' | 'diagnose';
}

export default function SessionsList({ 
  patientId, 
  selectedSessionId, 
  onSessionSelect, 
  onNewSession,
  mode 
}: SessionsListProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAllSessions, setShowAllSessions] = useState(false);
  
  const { user } = useUser();

  const loadSessions = async () => {
    if (!user?.user_id) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const request: SessionListRequest = {
        patient_id: patientId,
        user_id: user.user_id,
        include_all_patient_sessions: showAllSessions
      };
      
      console.log('Loading sessions with request:', request); // Add debugging
      
      const data = await listSessions(request);
      console.log('Sessions loaded:', data); // Add debugging
      setSessions(data);
    } catch (err: any) {
      console.error('Failed to load sessions:', err);
      setError(err.message || 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateNewSession = async () => {
    if (!user?.user_id) return;
    
    try {
      const sessionTitle = `${mode === 'chat' ? 'Chat' : 'Diagnosis'} Session - ${new Date().toLocaleDateString()}`;
      
      console.log('Creating session with data:', { // Add debugging
        patient_id: patientId,
        mode: mode,
        session_title: sessionTitle
      });
      
      const result = await createSession({
        patient_id: patientId,
        mode: mode,
        session_title: sessionTitle
      });
      
      console.log('Session created:', result); // Add debugging
      
      // Reload sessions and select the new one
      await loadSessions();
      onSessionSelect(result.session_id);
      onNewSession();
    } catch (err: any) {
      console.error('Failed to create session:', err);
      setError(err.message || 'Failed to create session');
    }
  };

  const handleJoinSession = async (sessionId: string) => {
    try {
      await joinSession(sessionId);
      onSessionSelect(sessionId);
      // Reload to update participant info
      await loadSessions();
    } catch (err: any) {
      console.error('Failed to join session:', err);
      setError(err.message || 'Failed to join session');
    }
  };

  const formatSessionTime = (dateString: string) => {
    try {
      return formatDistanceToNow(new Date(dateString), { addSuffix: true });
    } catch {
      return 'Unknown time';
    }
  };

  const isUserParticipant = (session: Session) => {
    return session.participants.includes(user?.user_id || '');
  };

  return (
    <div className="w-80 bg-white border-r border-gray-200 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-gray-900">
            {mode === 'chat' ? 'Chat Sessions' : 'Diagnosis Sessions'}
          </h3>
          <button
            onClick={handleCreateNewSession}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
            disabled={loading}
          >
            New
          </button>
        </div>
        
        {patientId && (
          <div className="flex items-center space-x-2">
            <label className="flex items-center text-sm">
              <input
                type="checkbox"
                checked={showAllSessions}
                onChange={(e) => setShowAllSessions(e.target.checked)}
                className="mr-2"
              />
              Show all sessions
            </label>
          </div>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div className="p-3 bg-red-50 border-l-4 border-red-400">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-center">
            <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-2"></div>
            <p className="text-sm text-gray-500">Loading sessions...</p>
          </div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center">
            <div className="text-gray-400 text-2xl mb-2">💬</div>
            <p className="text-sm text-gray-500">No sessions yet</p>
            <p className="text-xs text-gray-400 mt-1">Create a new session to get started</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {sessions.map((session) => {
              const isSelected = session.session_id === selectedSessionId;
              const isParticipant = isUserParticipant(session);
              
              return (
                <div
                  key={session.session_id}
                  className={`p-3 cursor-pointer hover:bg-gray-50 transition-colors ${
                    isSelected ? 'bg-blue-50 border-r-2 border-blue-500' : ''
                  }`}
                  onClick={() => {
                    if (isParticipant) {
                      onSessionSelect(session.session_id);
                    } else {
                      handleJoinSession(session.session_id);
                    }
                  }}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-gray-900 truncate">
                        {session.session_title}
                      </h4>
                      <div className="mt-1 flex items-center space-x-2 text-xs text-gray-500">
                        <span>{session.message_count} messages</span>
                        <span>•</span>
                        <span>{formatSessionTime(session.last_message_at)}</span>
                      </div>
                      
                      {/* Participants info */}
                      <div className="mt-1 flex items-center space-x-1">
                        <span className="text-xs text-gray-400">
                          {session.participants.length} participant{session.participants.length !== 1 ? 's' : ''}
                        </span>
                        {!isParticipant && (
                          <span className="text-xs bg-yellow-100 text-yellow-800 px-1 py-0.5 rounded">
                            Join
                          </span>
                        )}
                        {session.mode && (
                          <span className={`text-xs px-1 py-0.5 rounded ${
                            session.mode === 'chat' 
                              ? 'bg-green-100 text-green-800' 
                              : 'bg-purple-100 text-purple-800'
                          }`}>
                            {session.mode}
                          </span>
                        )}
                      </div>
                    </div>
                    
                    {isSelected && (
                      <div className="flex-shrink-0 ml-2">
                        <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-200">
        <p className="text-xs text-gray-400">
          {showAllSessions ? 'Showing all patient sessions' : 'Showing your sessions only'}
        </p>
      </div>
    </div>
  );
}