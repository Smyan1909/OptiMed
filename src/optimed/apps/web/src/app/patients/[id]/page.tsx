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
                <span className="text-gray-900 font-medium">{patient?.name}</span>
              </li>
            </ol>
          </nav>

          {/* Patient Header */}
          <div className="bg-white shadow rounded-lg mb-6">
            <div className="px-6 py-4 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <div className="h-12 w-12 bg-blue-100 rounded-full flex items-center justify-center">
                    <span className="text-blue-600 font-bold text-lg">
                      {patient?.name.split(' ').map(n => n[0]).join('').substring(0, 2)}
                    </span>
                  </div>
                  <div className="ml-4">
                    <h1 className="text-2xl font-bold text-gray-900">{patient?.name}</h1>
                    <p className="text-gray-700 font-medium">Patient ID: {patient?.id}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <Link href={`/vitals?id=${patientId}`}>
                    <button className="flex items-center space-x-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors">
                      <span>📊</span>
                      <span>View Vitals & Labs</span>
                    </button>
                  </Link>
                  <Link href={`/journal?id=${patientId}`}>
                    <button className="flex items-center space-x-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition-colors">
                      <span>📋</span>
                      <span>View Journal</span>
                    </button>
                  </Link>
                  <Badge variant="success" className="text-sm px-3 py-1">
                    ✅ Active
                  </Badge>
                </div>
              </div>
            </div>
            
            {/* Patient Demographics Only */}
            <div className="px-6 py-4 bg-gray-50">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="font-medium text-gray-700">Age:</span>
                  <span className="ml-2 text-gray-900">{patient?.age} years</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Sex:</span>
                  <span className="ml-2 text-gray-900">{patient?.sex}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Unit:</span>
                  <span className="ml-2 text-gray-900">{patient?.care_unit}</span>
                </div>
              </div>
            </div>
          </div>

          {/* AI Diagnosis Chat Section with Sessions */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-6 py-4 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-bold text-gray-900">AI Diagnostic Assistant</h2>
                  <p className="text-sm text-gray-700 font-medium">Have a continuous conversation about this patient's diagnosis</p>
                </div>
                <div className="flex items-center space-x-2">
                  <Badge variant="default" className="px-3 py-1">
                    🤖 AI Assistant
                  </Badge>
                  <Badge variant="outline" className="px-3 py-1">
                    👨‍⚕️ {user?.display_name}
                  </Badge>
                </div>
              </div>
            </div>
            
            {/* Sessions and Chat Layout */}
            <div className="flex h-[600px]">
              {/* Sessions List Sidebar */}
              <SessionsList
                key={sessionsKey}
                patientId={patientId}
                selectedSessionId={selectedSessionId}
                onSessionSelect={handleSessionSelect}
                onNewSession={handleNewSession}
                mode="diagnose"
              />
              
              {/* Chat Area */}
              <div className="flex-1 flex flex-col">
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