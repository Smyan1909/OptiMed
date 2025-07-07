'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchPatient, PatientDetail } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { getDisplayName, formatLabValue, formatVitalValue } from '@/lib/codeMapping';
import { Heart, Activity, Beaker } from 'lucide-react';

function VitalsPageContent() {
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
                <Link href={`/patients/${patientId}`} className="text-blue-600 hover:text-blue-800 font-medium">
                  {patient?.name}
                </Link>
              </li>
              <li>
                <span className="text-gray-400">/</span>
              </li>
              <li>
                <span className="text-gray-900 font-medium">Vitals & Labs</span>
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
                    <h1 className="text-2xl font-bold text-gray-900">{patient?.name} - Vitals & Labs</h1>
                    <p className="text-gray-700 font-medium">Patient ID: {patient?.id}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <Link href={`/patients/${patientId}`}>
                    <button className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors">
                      ← Back to Patient
                    </button>
                  </Link>
                </div>
              </div>
            </div>
            
            {/* Quick Patient Info */}
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

          {/* Enhanced Vitals and Labs Section */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-8 mb-6">
            {/* Vital Signs */}
            <div className="bg-white shadow-sm rounded-lg border border-gray-200">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-red-50 to-pink-50">
                <h2 className="text-lg font-bold text-gray-900 flex items-center">
                  <Heart className="h-5 w-5 mr-2 text-red-500" />
                  Vital Signs
                  {patient?.vitals && Object.keys(patient.vitals).length > 0 && (
                    <Badge variant="secondary" className="ml-2 text-xs">
                      {Object.keys(patient.vitals).length} readings
                    </Badge>
                  )}
                </h2>
              </div>
              <div className="p-6">
                {patient?.vitals && Object.keys(patient.vitals).length > 0 ? (
                  <div className="space-y-3">
                    {Object.entries(patient.vitals).map(([key, value]) => {
                      const displayName = key.includes('-') ? getDisplayName(key, 'vital') : key;
                      const formattedValue = formatVitalValue(key, value);
                      
                      return (
                        <div key={key} className="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors min-h-[50px]">
                          <div className="flex items-center flex-1">
                            <span className="text-sm font-medium text-gray-700 flex-1">{displayName}</span>
                          </div>
                          <Badge variant="outline" className="text-sm font-semibold ml-4">{formattedValue}</Badge>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center py-12">
                    <div className="h-16 w-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Activity className="h-8 w-8 text-gray-400" />
                    </div>
                    <h3 className="text-sm font-medium text-gray-900 mb-1">No Vital Signs</h3>
                    <p className="text-sm text-gray-500">No vital signs recorded for this patient</p>
                  </div>
                )}
              </div>
            </div>

            {/* Lab Results */}
            <div className="bg-white shadow-sm rounded-lg border border-gray-200">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
                <h2 className="text-lg font-bold text-gray-900 flex items-center">
                  <Beaker className="h-5 w-5 mr-2 text-blue-500" />
                  Lab Results
                  {patient?.labs && Object.keys(patient.labs).length > 0 && (
                    <Badge variant="secondary" className="ml-2 text-xs">
                      {Object.keys(patient.labs).length} tests
                    </Badge>
                  )}
                </h2>
              </div>
              <div className="p-6">
                {patient?.labs && Object.keys(patient.labs).length > 0 ? (
                  <div className="space-y-3">
                    {Object.entries(patient.labs).map(([key, value]) => {
                      const displayName = key.includes('-') ? getDisplayName(key, 'lab') : key;
                      const formattedValue = formatLabValue(key, value);
                      
                      return (
                        <div key={key} className="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors min-h-[50px]">
                          <div className="flex items-center flex-1">
                            <span className="text-sm font-medium text-gray-700 flex-1">{displayName}</span>
                          </div>
                          <Badge variant="outline" className="text-sm font-semibold ml-4">{formattedValue}</Badge>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center py-12">
                    <div className="h-16 w-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Beaker className="h-8 w-8 text-gray-400" />
                    </div>
                    <h3 className="text-sm font-medium text-gray-900 mb-1">No Lab Results</h3>
                    <p className="text-sm text-gray-500">No laboratory results available for this patient</p>
                  </div>
                )}
              </div>
            

            </div>
          </div>    
        </div>

      </main>
    </div>
  );
}

export default function VitalsPage() {
  return (
    <ProtectedRoute>
      <VitalsPageContent />
    </ProtectedRoute>
  );
}