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
      // Clear session from local CLARA watcher (fails silently if not running)
      clearSessionFromWatcher().catch(() => {
        // Ignore errors - watcher is optional
      });

      await logoutUser();
    } catch (err) {
      logError('Logout error', err instanceof Error ? err : new Error(String(err)));
    } finally {
      localStorage.removeItem('session_id');
      setUser(null);
      setIsAuthenticated(false);
    }
  };

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
