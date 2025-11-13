'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getCurrentUser, loginUser, logoutUser, User, setupSessionEncryption } from '@/lib/api';
import { sendSessionToWatcher, clearSessionFromWatcher } from '@/lib/watcherService';
import { sanitizeUserId, sanitizePatientId, sanitizeSessionId, sanitizeDocumentId, logInfo, logError, logWarning } from '@/lib/logger';

type UserContextType = {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  error: string | null;
  setUser: (user: User | null) => void;  // Add this
  setIsAuthenticated: (authenticated: boolean) => void;  // Add this
};

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const checkAuth = async () => {
    try {
      setIsLoading(true);
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setIsAuthenticated(!!currentUser);

      // If user is authenticated, send existing session to watcher
      // This handles page refresh scenarios
      if (currentUser) {
        const sessionId = localStorage.getItem('session_id');
        if (sessionId) {
          sendSessionToWatcher(sessionId).catch(() => {
            // Ignore errors - watcher is optional
          });
        }
      }
    } catch (err) {
      setUser(null);
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const login = async (username: string, password: string) => {
    try {
      setError(null);
      setIsLoading(true);
      const response = await loginUser(username, password);

      localStorage.setItem('session_id', response.session.session_id);
      setUser(response.user);
      setIsAuthenticated(true);

      // Send session to local CLARA watcher (fails silently if not running)
      sendSessionToWatcher(response.session.session_id).catch(() => {
        // Ignore errors - watcher is optional
      });

      // Setup encryption for the session
      try {
        const encryptionSetup = await setupSessionEncryption(response.session.session_id);
        if (encryptionSetup) {
          logInfo(`Session encryption setup successful for session: ${sanitizeSessionId(response.session.session_id)}`);
        } else {
          logWarning(`Session encryption setup failed for session: ${sanitizeSessionId(response.session.session_id)}, continuing without encryption`);
        }
      } catch (encryptionError) {
        logWarning(`Encryption setup error for session: ${sanitizeSessionId(response.session.session_id)}`);
        // Continue without encryption - not critical for basic functionality
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      // Find all active chat sessions from localStorage
      let chatSessionId: string | undefined = undefined;
      if (typeof window !== 'undefined') {
        // Primary method: Look for chat_session_* keys (these store the actual session IDs)
        const chatSessionKeys = Object.keys(localStorage).filter(key =>
          key.startsWith('chat_session_') && !key.includes('cleanup')
        );

        logInfo(`[Logout] Found ${chatSessionKeys.length} chat_session_* keys in localStorage`);

        if (chatSessionKeys.length > 0) {
          // Get all session IDs and find the most recent one
          const sessions: { id: string; time: number }[] = [];

          for (const key of chatSessionKeys) {
            const sessionId = localStorage.getItem(key);
            if (sessionId) {
              // Check if there's a corresponding session_start_time
              const timeKey = `session_start_time_${sessionId}`;
              const timeStr = localStorage.getItem(timeKey);
              const time = timeStr ? parseInt(timeStr, 10) : 0;

              sessions.push({ id: sessionId, time });
              logInfo(`[Logout] Found session from ${key}: ${sanitizeSessionId(sessionId)}, time: ${time}`);
            }
          }

          // Sort by timestamp (most recent first) and take the first one
          if (sessions.length > 0) {
            sessions.sort((a, b) => b.time - a.time);
            chatSessionId = sessions[0].id;
            logInfo(`[Logout] Selected most recent chat session: ${sanitizeSessionId(chatSessionId)}`);
          }
        }

        // Fallback 1: Look for session_start_time_* keys
        if (!chatSessionId) {
          const sessionTimeKeys = Object.keys(localStorage).filter(key => key.startsWith('session_start_time_'));
          logInfo(`[Logout] Fallback: Found ${sessionTimeKeys.length} session_start_time_* keys`);

          if (sessionTimeKeys.length > 0) {
            let mostRecentTime = 0;
            for (const key of sessionTimeKeys) {
              const timeStr = localStorage.getItem(key);
              if (timeStr) {
                const time = parseInt(timeStr, 10);
                if (time > mostRecentTime) {
                  mostRecentTime = time;
                  chatSessionId = key.replace('session_start_time_', '');
                }
              }
            }
            if (chatSessionId) {
              logInfo(`[Logout] Found session from session_start_time: ${sanitizeSessionId(chatSessionId)}`);
            }
          }
        }

        // Fallback 2: Look for chat_messages_* keys
        if (!chatSessionId) {
          const messageKeys = Object.keys(localStorage).filter(key => key.startsWith('chat_messages_'));
          logInfo(`[Logout] Fallback 2: Found ${messageKeys.length} chat_messages_* keys`);

          if (messageKeys.length > 0) {
            const lastKey = messageKeys[messageKeys.length - 1];
            chatSessionId = lastKey.replace('chat_messages_', '');
            logInfo(`[Logout] Found session from chat_messages: ${sanitizeSessionId(chatSessionId)}`);
          }
        }

        if (!chatSessionId) {
          logWarning('[Logout] No chat session found in localStorage');
        }
      }

      // Clear session from local CLARA watcher (fails silently if not running)
      clearSessionFromWatcher().catch(() => {
        // Ignore errors - watcher is optional
      });

      // Session ID is sent via headers in logoutUser
      logInfo(`[Logout] Calling backend logout with chat_session_id: ${chatSessionId ? sanitizeSessionId(chatSessionId) : 'none'}`);
      await logoutUser();
    } catch (err) {
      logError('Logout error', err instanceof Error ? err : new Error(String(err)));
    } finally {
      localStorage.removeItem('session_id');
      setUser(null);
      setIsAuthenticated(false);
    }
  };

  // Global 401 interceptor - automatically logout when session expires
  useEffect(() => {
    if (!isAuthenticated) return;

    const originalFetch = window.fetch;
    let isLoggingOut = false; // Prevent multiple concurrent logout calls

    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await originalFetch(...args);

      // Intercept 401 responses (session expired/invalid)
      if (response.status === 401 && isAuthenticated && !isLoggingOut) {
        isLoggingOut = true;
        logWarning('[401 Interceptor] Session expired - triggering automatic logout');

        // Clone response before consuming it
        const clonedResponse = response.clone();

        // Trigger logout (async, but don't await to avoid blocking the response)
        logout().finally(() => {
          isLoggingOut = false;
        });

        return clonedResponse;
      }

      return response;
    };

    // Cleanup: restore original fetch when component unmounts or auth state changes
    return () => {
      window.fetch = originalFetch;
    };
  }, [isAuthenticated, logout]);

  return (
    <UserContext.Provider 
      value={{ 
        user, 
        isLoading, 
        isAuthenticated,
        login, 
        logout, 
        error,
        setUser,           // Export this
        setIsAuthenticated // Export this
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error('useUser must be used within a UserProvider');
  }
  return context;
}
