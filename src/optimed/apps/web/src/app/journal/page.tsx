'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchPatient, PatientDetail } from '@/lib/api';
import JournalList from '@/components/journal/JournalList';
import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';
import { getSexKey } from '@/lib/codeMapping';

function JournalPageContent() {
  const t = useTranslations();
  const params = useSearchParams();
  const patientId = params.get('id');
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
              <p className="text-gray-900 font-medium">{t('common.loadingPatient')}</p>
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
                <h3 className="text-lg font-medium text-red-800">{t('common.errorLoadingPatient')}</h3>
                <div className="mt-2 text-sm text-red-700">
                  <p>{error}</p>
                </div>
                <div className="mt-4">
                  <Link href="/patients">
                    <button className="bg-red-100 text-red-800 px-4 py-2 rounded-md hover:bg-red-200 transition-colors font-semibold">
                      ← {t('back.toPatients')}
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
                  {t('common.patients')}
                </Link>
              </li>
              <li>
                <span className="text-gray-400">/</span>
              </li>
              <li>
                <Link href={`/patients/${patientId}`} className="text-blue-600 hover:text-blue-800 font-medium">
                  {patient?.name}
                </Link>
              </li>
              <li>
                <span className="text-gray-400">/</span>
              </li>
              <li>
                <span className="text-gray-900 font-medium">{t('journalPage.breadcrumb.journal')}</span>
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
                      {(() => {
                        const fullName = patient?.name;
                        if (!fullName || typeof fullName !== 'string') return '';
                        const parts = fullName.trim().split(/\s+/).filter(Boolean);
                        if (parts.length === 0) return '';
                        return parts.map(p => p[0]).join('').substring(0, 2).toUpperCase();
                      })()}
                    </span>
                  </div>
                  <div className="ml-4">
                    <h1 className="text-2xl font-bold text-gray-900">
                      {t('journalPage.header.journalOf', {name: patient?.name ?? ''})}
                    </h1>
                    <p className="text-gray-700 font-medium">
                      {t('common.patientId')}: {patient?.id ?? ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <Link href={`/patients/${patientId}`}>
                    <button className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors">
                      ← {t('back.toPatients')}
                    </button>
                  </Link>
                </div>
              </div>
            </div>
            
            {/* Quick Patient Info */}
            <div className="px-6 py-4 bg-gray-50">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="font-medium text-gray-700">{t('common.age')}:</span>
                  <span className="ml-2 text-gray-900">{patient?.age} {t('common.years')}</span>
                </div>
                <div>
                  <span className="font-medium text_gray-700">{t('common.sex')}:</span>
                  <span className="ml-2 text-gray-900">{patient?.sex ? t(getSexKey(patient?.sex) as any) : ''}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">{t('common.unit')}:</span>
                  <span className="ml-2 text-gray-900">{patient?.care_unit}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Journal Section */}
          <div className="mb-6">
            {patientId && <JournalList patientId={patientId} />}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function JournalPage() {
  return (
    <ProtectedRoute>
      <JournalPageContent />
    </ProtectedRoute>
  );
}