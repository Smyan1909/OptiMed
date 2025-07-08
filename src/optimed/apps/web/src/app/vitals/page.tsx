'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchPatient, PatientDetail } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { getDisplayName, formatLabValue, formatVitalValue, formatNumericalValue } from '@/lib/codeMapping';
import { Heart, Beaker, Camera, Stethoscope, Scissors, UserCheck, Pill, AlertTriangle, FileText } from 'lucide-react';

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

  // Helper function to render observation sections
  const renderObservationSection = (
    title: string,
    data: Record<string, string>,
    icon: React.ReactNode,
    gradientFrom: string,
    gradientTo: string,
    emptyMessage: string,
    badgeVariant: "default" | "secondary" | "destructive" | "outline" = "outline"
  ) => (
    <div className="bg-white shadow-sm rounded-lg border border-gray-200">
      <div className={`px-6 py-4 border-b border-gray-200 bg-gradient-to-r ${gradientFrom} ${gradientTo}`}>
        <h2 className="text-lg font-bold text-gray-900 flex items-center">
          {icon}
          {title}
          {data && Object.keys(data).length > 0 && (
            <Badge variant="secondary" className="ml-2 text-xs">
              {Object.keys(data).length} {Object.keys(data).length === 1 ? 'entry' : 'entries'}
            </Badge>
          )}
        </h2>
      </div>
      <div className="p-6">
        {data && Object.keys(data).length > 0 ? (
          <div className="space-y-3">
            {Object.entries(data).map(([key, value]) => {
              const displayName = key.includes('-') ? getDisplayName(key, 'vital') : key;
              const formattedValue = title === 'Vital Signs' ? formatVitalValue(key, value) : 
                                   title === 'Lab Results' ? formatLabValue(key, value) : 
                                   formatNumericalValue(value); // Use the new formatter for all other fields
              
              return (
                <div key={key} className="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors min-h-[50px]">
                  <div className="flex items-center flex-1">
                    <span className="text-sm font-medium text-gray-700 flex-1">{displayName}</span>
                  </div>
                  <Badge variant={badgeVariant} className="text-sm font-semibold ml-4">{formattedValue}</Badge>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="h-16 w-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
              {icon}
            </div>
            <h3 className="text-sm font-medium text-gray-900 mb-1">No {title}</h3>
            <p className="text-sm text-gray-500">{emptyMessage}</p>
          </div>
        )}
      </div>
    </div>
  );

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
                <span className="text-gray-900 font-medium">Clinical Data</span>
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
                    <h1 className="text-2xl font-bold text-gray-900">{patient?.name} - Clinical Data</h1>
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

          {/* Comprehensive Clinical Data Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6 mb-6">
            
            {/* Vital Signs */}
            {renderObservationSection(
              'Vital Signs',
              patient?.vitals || {},
              <Heart className="h-5 w-5 mr-2 text-red-500" />,
              'from-red-50',
              'to-pink-50',
              'No vital signs recorded for this patient'
            )}

            {/* Lab Results */}
            {renderObservationSection(
              'Lab Results',
              patient?.labs || {},
              <Beaker className="h-5 w-5 mr-2 text-blue-500" />,
              'from-blue-50',
              'to-indigo-50',
              'No laboratory results available for this patient'
            )}

            {/* Imaging Studies */}
            {renderObservationSection(
              'Imaging Studies',
              patient?.imaging || {},
              <Camera className="h-5 w-5 mr-2 text-purple-500" />,
              'from-purple-50',
              'to-violet-50',
              'No imaging studies recorded for this patient'
            )}

            {/* Physical Exam */}
            {renderObservationSection(
              'Physical Exam',
              patient?.exam || {},
              <Stethoscope className="h-5 w-5 mr-2 text-green-500" />,
              'from-green-50',
              'to-emerald-50',
              'No physical exam findings recorded for this patient'
            )}

            {/* Procedures */}
            {renderObservationSection(
              'Procedures',
              patient?.procedure || {},
              <Scissors className="h-5 w-5 mr-2 text-orange-500" />,
              'from-orange-50',
              'to-amber-50',
              'No procedures recorded for this patient'
            )}

            {/* Social History */}
            {renderObservationSection(
              'Social History',
              patient?.social_history || {},
              <UserCheck className="h-5 w-5 mr-2 text-cyan-500" />,
              'from-cyan-50',
              'to-teal-50',
              'No social history recorded for this patient'
            )}

            {/* Medications */}
            {renderObservationSection(
              'Medications',
              patient?.medications || {},
              <Pill className="h-5 w-5 mr-2 text-indigo-500" />,
              'from-indigo-50',
              'to-blue-50',
              'No medications recorded for this patient'
            )}

            {/* Allergies */}
            {renderObservationSection(
              'Allergies',
              patient?.allergies || {},
              <AlertTriangle className="h-5 w-5 mr-2 text-red-500" />,
              'from-red-50',
              'to-rose-50',
              'No known allergies recorded for this patient',
              'destructive'
            )}

            {/* Diagnoses */}
            {renderObservationSection(
              'Diagnoses',
              patient?.diagnoses || {},
              <FileText className="h-5 w-5 mr-2 text-gray-500" />,
              'from-gray-50',
              'to-slate-50',
              'No diagnoses recorded for this patient'
            )}

          </div>

          {/* Summary Section */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-bold text-gray-900">Clinical Data Summary</h2>
            </div>
            <div className="p-6">
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 text-center">
                <div className="bg-red-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-red-600">
                    {patient?.vitals ? Object.keys(patient.vitals).length : 0}
                  </div>
                  <div className="text-sm text-red-700">Vital Signs</div>
                </div>
                <div className="bg-blue-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-blue-600">
                    {patient?.labs ? Object.keys(patient.labs).length : 0}
                  </div>
                  <div className="text-sm text-blue-700">Lab Results</div>
                </div>
                <div className="bg-purple-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-purple-600">
                    {patient?.imaging ? Object.keys(patient.imaging).length : 0}
                  </div>
                  <div className="text-sm text-purple-700">Imaging Studies</div>
                </div>
                <div className="bg-green-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-green-600">
                    {patient?.exam ? Object.keys(patient.exam).length : 0}
                  </div>
                  <div className="text-sm text-green-700">Exam Findings</div>
                </div>
                <div className="bg-orange-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-orange-600">
                    {patient?.procedure ? Object.keys(patient.procedure).length : 0}
                  </div>
                  <div className="text-sm text-orange-700">Procedures</div>
                </div>
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