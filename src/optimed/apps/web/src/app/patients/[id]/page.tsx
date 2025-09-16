'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchPatient, PatientDetail } from '@/lib/api';
import { useUser } from '@/contexts/UserContext';
import ChatBox from '@/components/ChatBox';
import SessionsList from '@/components/SessionsList';
import { useTranslations } from 'next-intl';
import { getSexKey } from '@/lib/codeMapping';

function PatientDetailContent() {
  const t = useTranslations();
  const params = useParams();
  const { user } = useUser();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>();
  const [chatKey, setChatKey] = useState(0);
  const [sessionsKey, setSessionsKey] = useState(0);
  const [showSessions, setShowSessions] = useState(true);

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
        setError(err.message || 'Failed to load patient');
        console.error('Patient load error:', err);
      } finally {
        setLoading(false);
      }
    };
    loadPatient();
  }, [patientId]);

  const handleSessionSelect = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    setChatKey(prev => prev + 1);
  };

  const handleNewSession = () => {
    setSelectedSessionId(undefined);
    setChatKey(prev => prev + 1);
    setSessionsKey(prev => prev + 1);
  };

  /* ---------------------- STATE SCREENS ---------------------- */
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8 flex justify-center items-center">
          <div className="text-center">
            <div className="animate-spin h-10 w-10 border-[6px] border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p className="text-gray-900 font-medium">{t('common.loadingPatient')}</p>
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
            <h3 className="text-lg font-medium text-red-800">{t('common.errorLoadingPatient')}</h3>
            <p className="mt-2 text-sm text-red-700">{error}</p>
            <Link href="/patients">
              <button className="mt-4 bg-red-100 text-red-800 px-4 py-2 rounded-md hover:bg-red-200 font-semibold">
                ← {t('common.backToPatients')}
              </button>
            </Link>
          </div>
        </main>
      </div>
    );
  }

  /* ---------------------- HELPERS ---------------------- */
  const initials = (() => {
    const fullName = patient?.name;
    if (!fullName || typeof fullName !== 'string') return '';
    const parts = fullName.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '';
    return parts.map(p => p[0]).join('').substring(0, 2).toUpperCase();
  })();

  /* ---------------------- MAIN RENDER ---------------------- */
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-50">
      <Header />

      {/* The whole content pane */}
      <main className="relative flex flex-1 overflow-hidden">

        {/* ─────  FLOATING   Show/Hide button  ───── */}
        <button
          onClick={() => setShowSessions(!showSessions)}
          className={`absolute top-3 z-30
                      ${showSessions ? 'left-[20.25rem]' : 'left-3'}   /* outside the 20-rem sidebar */
                      bg-white/10 backdrop-blur-md border shadow
                      rounded-full hover:bg-white transition-colors
                      flex items-center justify-center
                      h-8 w-8 hover:bg-white/70 transition-colors`}                        
          title={showSessions ? t('common.hideSessions') : t('common.showSessions')}
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

        {/* ─────  SIDEBAR  (patient details + sessions)  ───── */}
        {showSessions && (
          <aside className="w-80 flex-shrink-0 border-r border-gray-200 flex flex-col overflow-y-auto bg-white">
            {/* Patient details */}
            <div className="p-3 bg-gradient-to-r from-blue-50 to-white border-b border-gray-200 shadow-sm">
              <div className="flex items-start space-x-3">
                <div className="h-12 w-12 bg-blue-100 rounded-full flex items-center justify-center shadow text-blue-600 font-bold">
                  {initials}
                </div>
                <div className="flex-1">
                  <h2 className="text-lg font-bold text-gray-900">{patient?.name}</h2>
                  <div className="grid grid-cols-2 gap-1 text-xs text-gray-700">
                    <div>
                      <span className="text-gray-500 block">{t('common.age')}</span>
                      <span className="font-medium">{patient?.age}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">{t('common.sex')}</span>
                      <span className="font-medium">{patient?.sex ? t(getSexKey(patient?.sex) as any) : ''}</span>
                    </div>
                    <div className="col-span-2">
                      <span className="text-gray-500 block">{t('common.unit')}</span>
                      <span className="font-medium">{patient?.care_unit}</span>
                    </div>
                  </div>
                  <div className="mt-1 text-[10px] text-gray-500">
                    ID:&nbsp;<span className="font-mono">{patientId}</span>
                  </div>
                </div>
              </div>

              {/* Quick Links */}
              <div className="mt-4">
                {/* Clinical Data button */}
                <div className="mb-3">
                  <Link href={`/vitals?id=${patientId}`}>
                    <button className="w-full bg-blue-600 text-white text-xs font-medium rounded-lg px-3 py-2 flex items-center justify-center gap-2 group hover:bg-blue-700 transition">
                      {/* bar-chart icon */}
                      <svg
                        className="w-4 h-4 group-hover:scale-110 transition-transform"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                        />
                      </svg>
                       <span>{t('patientDetail.quickLinks.clinicalData')}</span>
                    </button>
                  </Link>
                </div>

                {/* Medical Journal button */}
                <div>
                  <Link href={`/journal?id=${patientId}`}>
                    <button className="w-full bg-blue-600 text-white text-xs font-medium rounded-lg px-3 py-2 flex items-center justify-center gap-2 group hover:bg-blue-700 transition">
                      {/* document icon */}
                      <svg
                        className="w-4 h-4 group-hover:scale-110 transition-transform"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        />
                      </svg>
                       <span>{t('patientDetail.quickLinks.medicalJournal')}</span>
                    </button>
                  </Link>
                </div>
              </div>

              <div className="mt-4 text-[10px] text-right text-gray-500">
                {t('common.consultingAs')} <span className="font-semibold">{user?.display_name}</span>
              </div>
            </div>

            {/* Sessions list */}
            <div className="flex-1 overflow-y-auto">
              <SessionsList
                key={sessionsKey}
                patientId={patientId}
                selectedSessionId={selectedSessionId}
                onSessionSelect={handleSessionSelect}
                onNewSession={handleNewSession}
                mode="diagnose"
              />
            </div>
          </aside>
        )}

        {/* ─────  CHAT AREA  ───── */}
        <section className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <ChatBox
            key={chatKey}
            mode="diagnose"
            patientId={patientId}
            sessionId={selectedSessionId}
          />
        </section>
      </main>
    </div>
  );
}

/* ───────────────────────────────────
      PAGE WRAPPER WITH PROTECTION
─────────────────────────────────── */
export default function PatientDetailPage() {
  return (
    <ProtectedRoute>
      <PatientDetailContent />
    </ProtectedRoute>
  );
}
