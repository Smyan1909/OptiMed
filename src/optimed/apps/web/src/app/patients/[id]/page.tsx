'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchPatient, PatientDetail } from "@/lib/api";
import { useUser } from '@/contexts/UserContext';
import ChatBox from "@/components/ChatBox";
import SessionsList from "@/components/SessionsList";
import { Badge } from "@/components/ui/badge";


function PatientDetailContent() {
  const params = useParams();
  const router = useRouter();
  const { user } = useUser();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>(undefined);
  const [chatKey, setChatKey] = useState(0); // Force ChatBox re-render
  const [sessionsKey, setSessionsKey] = useState(0); // Force SessionsList re-render
  const [showSessions, setShowSessions] = useState(true); // Toggle sessions visibility


  const patientId = params?.id as string;

  useEffect(() => {
    const loadPatient = async () => {
      if (!patientId) return;
      
      setLoading(true);
      setError(null);
      try {
        const result = await fetchPatient(patientId);
        setPatient(result);
      } catch (err: any) {
        setError(err.message || "Failed to load patient");
        console.error('Patient load error:', err);
      } finally {
        setLoading(false);
      }
    };

    loadPatient();
  }, [patientId]);

  const handleSessionSelect = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    setChatKey(prev => prev + 1); // Force ChatBox to reload with new session
  };

  const handleNewSession = () => {
    setSelectedSessionId(undefined);
    setChatKey(prev => prev + 1); // Force ChatBox to reset for new session
    setSessionsKey(prev => prev + 1); // Force SessionsList to reload
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
              <p className="text-gray-900 font-medium">Loading patient details...</p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <div className="bg-red-50 border border-red-200 rounded-md p-6">
            <div className="flex">
              <div className="flex-shrink-0">
                <span className="text-red-400 text-2xl">⚠️</span>
              </div>
              <div className="ml-3">
                <h3 className="text-lg font-medium text-red-800">Error Loading Patient</h3>
                <div className="mt-2 text-sm text-red-700">
                  <p>{error}</p>
                </div>
                <div className="mt-4">
                  <Link href="/patients">
                    <button className="bg-red-100 text-red-800 px-4 py-2 rounded-md hover:bg-red-200 transition-colors font-semibold">
                      ← Back to Patients
                    </button>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <Header />
      <main className="flex-1 w-full flex flex-col overflow-hidden">
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Breadcrumb - kompakt */}
          <nav className="flex mb-2 px-6 pt-4 flex-shrink-0" aria-label="Breadcrumb">
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
                <span className="text-gray-900 font-medium">{patient?.name}</span>
              </li>
            </ol>
          </nav>

          {/* Patient Header - extra stor med mer detaljer */}
          <div className="bg-gradient-to-r from-blue-50 to-white border-b border-gray-200 px-8 py-8 shadow-sm flex-shrink-0">
            <div className="flex items-start justify-between">
              <div className="flex items-start">
                <div className="h-20 w-20 bg-blue-100 rounded-full flex items-center justify-center mr-6 shadow-md">
                  <span className="text-blue-600 font-bold text-3xl">
                    {patient?.name.split(' ').map(n => n[0]).join('').substring(0, 2)}
                  </span>
                </div>
                <div>
                  <h1 className="text-4xl font-bold text-gray-900 mb-2">{patient?.name}</h1>
                  <div className="grid grid-cols-3 gap-6 text-gray-600 mb-3">
                    <div>
                      <span className="text-sm text-gray-500 block">Age</span>
                      <span className="text-lg font-semibold">{patient?.age} years</span>
                    </div>
                    <div>
                      <span className="text-sm text-gray-500 block">Gender</span>
                      <span className="text-lg font-semibold">{patient?.sex}</span>
                    </div>
                    <div>
                      <span className="text-sm text-gray-500 block">Care Unit</span>
                      <span className="text-lg font-semibold">{patient?.care_unit}</span>
                    </div>
                  </div>
                  <div className="flex items-center space-x-4">
                    <span className="text-sm text-gray-500">Patient ID: <span className="font-mono">{patientId}</span></span>
                    <span className="text-sm text-gray-500">•</span>
                    <span className="text-sm text-gray-500">Last accessed: {new Date().toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
              <div className="flex flex-col items-end space-y-3">
                <div className="flex items-center space-x-3">
                  <Link href={`/vitals?id=${patientId}`}>
                    <button className="bg-blue-600 text-white px-6 py-3 text-base font-semibold rounded-lg hover:bg-blue-700 transition-colors shadow-md flex items-center space-x-2">
                      <span>Vitals & Labs</span>
                    </button>
                  </Link>
                  <Link href={`/journal?id=${patientId}`}>
                    <button className="bg-green-600 text-white px-6 py-3 text-base font-semibold rounded-lg hover:bg-green-700 transition-colors shadow-md flex items-center space-x-2">
                      <span>Medical Journal</span>
                    </button>
                  </Link>
                </div>
                <div className="flex flex-col items-end space-y-2">
                </div>
              </div>
            </div>
          </div>

          {/* Chat Section - tar resten av skärmen */}
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
            
            {/* Sessions and Chat Layout - tar resten av utrymmet */}
            <div className="flex flex-1 min-h-0 overflow-hidden">
              {showSessions && (
                <SessionsList
                  key={sessionsKey}
                  patientId={patientId}
                  selectedSessionId={selectedSessionId}
                  onSessionSelect={handleSessionSelect}
                  onNewSession={handleNewSession}
                  mode="diagnose"
                />
              )}
              
              {/* Chat Area - tar upp resten av utrymmet */}
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                <ChatBox 
                  key={chatKey}
                  mode="diagnose" 
                  patientId={patientId}
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

export default function PatientDetailPage() {
  return (
    <ProtectedRoute>
      <PatientDetailContent />
    </ProtectedRoute>
  );
}