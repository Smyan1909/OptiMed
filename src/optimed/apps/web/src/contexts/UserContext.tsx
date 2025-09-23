'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getCurrentUser, loginUser, logoutUser, User, setupSessionEncryption } from '@/lib/api';

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

      // Setup encryption for the session
      try {
        const encryptionSetup = await setupSessionEncryption(response.session.session_id);
        if (encryptionSetup) {
          console.log('✅ Session encryption setup successful');
        } else {
          console.warn('⚠️ Session encryption setup failed, continuing without encryption');
        }
      } catch (encryptionError) {
        console.warn('⚠️ Encryption setup error:', encryptionError);
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
      await logoutUser();
    } catch (err) {
      console.error('Logout error:', err);
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
