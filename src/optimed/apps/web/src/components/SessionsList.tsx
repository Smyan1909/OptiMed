import { useState, useEffect } from 'react';
import { listSessions, createSession, joinSession, SessionListRequest } from '@/lib/api';
import { Session } from '@/lib/api';
import { useUser } from '@/contexts/UserContext';
import { formatDistanceToNow } from 'date-fns';
import { useTranslations, useLocale } from 'next-intl';
import { enUS, sv as svLocale } from 'date-fns/locale';

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
  const t = useTranslations('sessions');
  const tc = useTranslations('common');
  const locale = useLocale();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAllSessions, setShowAllSessions] = useState(false);
  const [sessionMessageCounts, setSessionMessageCounts] = useState<Record<string, number>>({});
  
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
      
      console.log('Loading sessions with request:', request);
      
      const data = await listSessions(request);
      console.log('Sessions loaded:', data.length + ' sessions');
      setSessions(data);
      
      // Load actual message counts for each session
      await loadSessionMessageCounts(data);
      
      // Auto-select the most recent session if none is selected and we have sessions
      if (!selectedSessionId && data.length > 0) {
        const mostRecentSession = data[0]; // They're ordered by last_message_at DESC
        onSessionSelect(mostRecentSession.session_id);
      }
    } catch (err: any) {
      console.error('Failed to load sessions:', err);
      setError(err.message || 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  const loadSessionMessageCounts = async (sessionsList: Session[]) => {
    const counts: Record<string, number> = {};
    
    try {
      for (const session of sessionsList) {
        try {
          // Get chat history for this session to count actual messages
          const response = await fetch('/api/chat-history', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(typeof window !== 'undefined' && localStorage.getItem('session_id') ? {
                'X-Session-ID': localStorage.getItem('session_id')!
              } : {})
            },
            body: JSON.stringify({ 
              patient_id: session.patient_id,
              session_id: session.session_id,
              mode: session.mode
            })
          });
          
          if (response.ok) {
            const data = await response.json();
            // Count actual messages, excluding system messages
            const messageCount = data.messages ? data.messages.filter((msg: any) => msg.role !== 'system').length : 0;
            counts[session.session_id] = messageCount;
          } else {
            // Fallback to the stored count if API call fails
            counts[session.session_id] = session.message_count;
          }
        } catch (sessionError) {
          console.error(`Failed to load message count for session ${session.session_id}:`, sessionError);
          // Fallback to the stored count
          counts[session.session_id] = session.message_count;
        }
      }
      
      setSessionMessageCounts(counts);
    } catch (err) {
      console.error('Failed to load session message counts:', err);
      // Fallback to stored counts
      const fallbackCounts: Record<string, number> = {};
      sessionsList.forEach(session => {
        fallbackCounts[session.session_id] = session.message_count;
      });
      setSessionMessageCounts(fallbackCounts);
    }
  };

  useEffect(() => {
    loadSessions();
  }, [patientId, user?.user_id, showAllSessions]);

  // Add a new function to get user info
  const getUserDisplay = (userId: string): string => {
    if (!userId) return t('unknownUser');
    
    // If it's the current user
    if (userId === user?.user_id) {
      return t('you');
    }
    
    // Extract a readable name from the user ID
    if (userId.startsWith('ehr_user_')) {
      return t('ehrUser');
    }
    
    // For other user IDs, show a shortened version
    return userId.substring(0, 12) + '...';
  };

  const handleCreateNewSession = async () => {
    if (!user?.user_id) return;
    
    try {
      // Generate a more descriptive session title
      const sessionTitle = generateSessionTitle(mode, patientId);
      
      console.log('Creating session with data:', {
        patient_id: patientId,
        mode: mode,
        session_title: sessionTitle
      });
      
      const result = await createSession({
        patient_id: patientId,
        mode: mode,
        session_title: sessionTitle
      });
      
      console.log('Session created:', result);
      
      // Reload sessions and select the new one
      await loadSessions();
      onSessionSelect(result.session_id);
      onNewSession();
    } catch (err: any) {
      console.error('Failed to create session:', err);
      setError(err.message || 'Failed to create session');
    }
  };

  const generateSessionTitle = (mode: 'chat' | 'diagnose', patientId?: string): string => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString(locale, { 
      hour: '2-digit', 
      minute: '2-digit',
      hour12: locale === 'en' 
    });
    const dateStr = now.toLocaleDateString(locale, { 
      month: 'short', 
      day: 'numeric' 
    });

    if (mode === 'chat') {
      if (patientId) {
        return t('titles.patientChat', {date: dateStr, time: timeStr});
      } else {
        return t('titles.generalChat', {date: dateStr, time: timeStr});
      }
    } else {
      return t('titles.patientSession', {date: dateStr, time: timeStr});
    }
  };

  // Localize title for display regardless of stored string
  const getDisplayTitle = (session: Session): string => {
    const created = new Date(session.created_at);
    const timeStr = created.toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit',
      hour12: locale === 'en'
    });
    const dateStr = created.toLocaleDateString(locale, {
      month: 'short',
      day: 'numeric'
    });

    if (session.mode === 'chat') {
      if (session.patient_id) {
        return t('titles.patientChat', { date: dateStr, time: timeStr });
      }
      return t('titles.generalChat', { date: dateStr, time: timeStr });
    }
    return t('titles.patientSession', { date: dateStr, time: timeStr });
  };

  const handleJoinSession = async (sessionId: string) => {
    try {
      await joinSession(sessionId);
      onSessionSelect(sessionId);
      // Reload to update participant info and message counts
      await loadSessions();
    } catch (err: any) {
      console.error('Failed to join session:', err);
      setError(err.message || 'Failed to join session');
    }
  };

  const formatSessionTime = (dateString: string) => {
    try {
      const dfnsLocale = locale === 'sv' ? svLocale : enUS;
      return formatDistanceToNow(new Date(dateString), { addSuffix: true, locale: dfnsLocale });
    } catch {
      return t('unknownTime');
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
          <h3 className="text-lg font-semibold text-gray-900">{mode === 'chat' ? t('headers.chatSessions') : t('headers.patientSessions')}</h3>
          <button
            onClick={handleCreateNewSession}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
            disabled={loading}
          >
            {t('actions.new')}
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
              {t('filters.showAll')}
            </label>
          </div>
        )}
        
        {/* Add general chat indicator */}
        {!patientId && (
          <div className="text-xs text-gray-500 mt-2">💬 {t('info.generalNoPatient')}</div>
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
            <p className="text-sm text-gray-500">{t('loading')}</p>
          </div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center">
            <div className="text-gray-400 text-2xl mb-2">💬</div>
            <p className="text-sm text-gray-500">{t('empty.title')}</p>
            <p className="text-xs text-gray-400 mt-1">{t('empty.subtitle')}</p>
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
                        {getDisplayTitle(session)}
                      </h4>
                      
                      {/* Add creator info */}
                      <div className="mt-1 text-xs text-gray-500">
                        <span>{t('meta.createdBy', {name: getUserDisplay(session.created_by_user_id)})}</span>
                        {session.last_participant_id && session.last_participant_id !== session.created_by_user_id && (
                          <span> • {t('meta.last', {name: getUserDisplay(session.last_participant_id)})}</span>
                        )}
                      </div>
                      
                      <div className="mt-1 flex items-center space-x-2 text-xs text-gray-500">
                        <span>{t('meta.messages', {count: sessionMessageCounts[session.session_id] ?? session.message_count})}</span>
                        <span>•</span>
                        <span>{formatSessionTime(session.last_message_at)}</span>
                      </div>
                      
                      {/* Participants info */}
                      <div className="mt-1 flex items-center space-x-1">
                        <span className="text-xs text-gray-400">
                          {t('meta.participants', {count: session.participants.length})}
                        </span>
                        {!isParticipant && (
                          <span className="text-xs bg-yellow-100 text-yellow-800 px-1 py-0.5 rounded">{t('actions.join')}</span>
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
        <p className="text-xs text-gray-400">{patientId ? (showAllSessions ? t('footer.showingAll') : t('footer.showingYours')) : t('footer.general')}</p>
      </div>
    </div>
  );
}