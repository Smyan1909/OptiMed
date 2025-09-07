'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchPatient, PatientDetail } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { getDisplayKey, formatLabValue, formatVitalValue, formatNumericalValue, type ObservationCategory } from '@/lib/codeMapping';
import { Heart, Beaker, Camera, Stethoscope, Scissors, UserCheck, Pill, AlertTriangle, FileText, ClipboardList, ChevronDown, ChevronRight, Calendar, Clock, Shield } from 'lucide-react';
import { useTranslations } from 'next-intl';

// Helper function to format timestamps
const formatTimestamp = (timestamp: string | undefined): string => {
  if (!timestamp || timestamp === 'Unknown') return 'Unknown';
  
  try {
    // Try to parse the timestamp and format it nicely
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
      // If it's not a valid date, return as-is (might already be formatted)
      return timestamp;
    }
    
    // Format as a more readable date and time
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return timestamp;
  }
};

function VitalsPageContent() {
  const t = useTranslations();
  const params = useSearchParams();
  const patientId = params.get('id');
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

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

  const toggleSection = (sectionId: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(sectionId)) {
      newExpanded.delete(sectionId);
    } else {
      newExpanded.add(sectionId);
    }
    setExpandedSections(newExpanded);
  };

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

  // Helper function to render observation sections with expand/collapse
  const renderObservationSection = (
    title: string,
    data: Record<string, string>,
    timestampsData: Record<string, string> | undefined,
    icon: React.ReactNode,
    gradientFrom: string,
    gradientTo: string,
    emptyMessage: string,
    badgeVariant: "default" | "secondary" | "destructive" | "outline" = "outline",
    category: ObservationCategory
  ) => {
    const sectionId = title.toLowerCase().replace(/\s+/g, '_');
    const isExpanded = expandedSections.has(sectionId);
    const hasData = data && Object.keys(data).length > 0;

    return (
      <div className="bg-white shadow-sm rounded-lg border border-gray-200">
        <div className={`px-6 py-4 border-b border-gray-200 bg-gradient-to-r ${gradientFrom} ${gradientTo}`}>
          <h2 className="text-lg font-bold text-gray-900 flex items-center">
            {icon}
            {title}
            {hasData && (
              <Badge variant="secondary" className="ml-2 text-xs">
                {Object.keys(data).length} {Object.keys(data).length === 1 ? t('vitalsPage.item') : t('vitalsPage.items')}
              </Badge>
            )}
          </h2>
        </div>
        <div className="p-6">
          {hasData ? (
            <div>
              <button
                onClick={() => toggleSection(sectionId)}
                className="flex items-center justify-between w-full px-4 py-3 bg-gray-50 hover:bg-gray-100 rounded-lg transition-colors mb-4"
              >
                <span className="text-sm font-medium text-gray-700">
                  {t('vitalsPage.viewSection', { title, count: Object.keys(data).length, itemLabel: Object.keys(data).length === 1 ? t('vitalsPage.item') : t('vitalsPage.items') })}
                </span>
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4 text-gray-500" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-gray-500" />
                )}
              </button>
              
              {isExpanded && (
                <div className="space-y-3">
                  {Object.entries(data).map(([key, value]) => {
                    const displayKey = getDisplayKey(key, category);
                    const displayName = displayKey.startsWith('codes.')
                      ? t(displayKey as any)
                      : displayKey;
                    const formattedValue = category === 'vitals' ? formatVitalValue(key, value)
                      : category === 'labs' ? formatLabValue(key, value)
                      : formatNumericalValue(value);
                    const timestamp = formatTimestamp(timestampsData?.[key]);

                    return (
                      <div key={key} className="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors min-h-[50px]">
                        <div className="flex flex-col flex-1">
                          <span className="text-sm font-medium text-gray-700">{displayName}</span>
                          {timestamp !== 'Unknown' && timestampsData && (
                            <div className="flex items-center text-xs text-gray-500 mt-1">
                              <Clock className="h-3 w-3 mr-1" />
                              <span>{t('vitalsPage.recorded', { timestamp })}</span>
                            </div>
                          )}
                        </div>
                        <Badge variant={badgeVariant} className="text-sm font-semibold ml-4">{formattedValue}</Badge>
                      </div>
                    );
                  })}
                </div>
              )}
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
  };

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
                <span className="text-gray-900 font-medium">{t('vitalsPage.breadcrumb.clinicalData')}</span>
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
                    <h1 className="text-2xl font-bold text-gray-900">{patient?.name} - {t('vitalsPage.breadcrumb.clinicalData')}</h1>
                    <p className="text-gray-700 font-medium">{t('common.patientId')}: {patient?.id}</p>
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
                  <span className="font-medium text-gray-700">{t('common.sex')}:</span>
                  <span className="ml-2 text-gray-900">{patient?.sex}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">{t('common.unit')}:</span>
                  <span className="ml-2 text-gray-900">{patient?.care_unit}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Recent Encounters Overview */}
          {patient?.encounters && Object.keys(patient.encounters).length > 0 && (
            <div className="bg-white shadow rounded-lg mb-6">
              <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-sky-50">
                <h2 className="text-lg font-bold text-gray-900 flex items-center">
                  <Calendar className="h-5 w-5 mr-2 text-blue-500" />
                  {t('vitalsPage.recentEncounters')}
                  <Badge variant="secondary" className="ml-2 text-xs">
                    {Object.keys(patient.encounters).length} {Object.keys(patient.encounters).length === 1 ? t('vitalsPage.item') : t('vitalsPage.items')}
                  </Badge>
                </h2>
              </div>
              <div className="p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {Object.entries(patient.encounters).slice(0, 6).map(([encounterId, encounterType]) => {
                    const encounterKey = getDisplayKey(encounterType, 'encounters');
                    const encounterDisplay = encounterKey.startsWith('codes.') ? t(encounterKey as any) : encounterKey;
                    const timestamp = formatTimestamp(patient.encounters_timestamps?.[encounterId]);
                    return (
                      <div key={encounterId} className="bg-blue-50 p-4 rounded-lg border border-blue-200">
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <h3 className="font-medium text-gray-900 text-sm">{encounterDisplay}</h3>
                            <p className="text-xs text-gray-600 mt-1">ID: {encounterId}</p>
                            {timestamp !== 'Unknown' && patient.encounters_timestamps && (
                              <div className="flex items-center text-xs text-gray-500 mt-2">
                                <Clock className="h-3 w-3 mr-1" />
                                <span>{timestamp}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                {Object.keys(patient.encounters).length > 6 && (
                  <div className="mt-4 text-center">
                    <p className="text-sm text-gray-500">
                    {t('vitalsPage.andMore', {count: Object.keys(patient.encounters).length - 6})}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Comprehensive Clinical Data Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6 mb-6">
            
            {/* Vital Signs */}
            {renderObservationSection(
              t('vitalsPage.sections.vitals'),
              patient?.vitals || {},
              patient?.vitals_timestamps,
              <Heart className="h-5 w-5 mr-2 text-red-500" />,
              'from-red-50',
              'to-pink-50',
              t('vitalsPage.noData.vitals'),
              undefined,
              'vitals'
            )}

            {/* Lab Results */}
            {renderObservationSection(
              t('vitalsPage.sections.labs'),
              patient?.labs || {},
              patient?.labs_timestamps,
              <Beaker className="h-5 w-5 mr-2 text-blue-500" />,
              'from-blue-50',
              'to-indigo-50',
              t('vitalsPage.noData.labs'),
              undefined,
              'labs'
            )}

            {/* Imaging Studies */}
            {renderObservationSection(
              t('vitalsPage.sections.imaging'),
              patient?.imaging || {},
              patient?.imaging_timestamps,
              <Camera className="h-5 w-5 mr-2 text-purple-500" />,
              'from-purple-50',
              'to-violet-50',
              t('vitalsPage.noData.imaging'),
              undefined,
              'imaging'
            )}

            {/* Physical Exam */}
            {renderObservationSection(
              t('vitalsPage.sections.exam'),
              patient?.exam || {},
              patient?.exam_timestamps,
              <Stethoscope className="h-5 w-5 mr-2 text-green-500" />,
              'from-green-50',
              'to-emerald-50',
              t('vitalsPage.noData.exam'),
              undefined,
              'exam'
            )}

            {/* Procedures */}
            {renderObservationSection(
              t('vitalsPage.sections.procedures'),
              patient?.procedure || {},
              patient?.procedure_timestamps,
              <Scissors className="h-5 w-5 mr-2 text-orange-500" />,
              'from-orange-50',
              'to-amber-50',
              t('vitalsPage.noData.procedures'),
              undefined,
              'procedures'
            )}

            {/* Social History */}
            {renderObservationSection(
              t('vitalsPage.sections.social'),
              patient?.social_history || {},
              patient?.social_history_timestamps,
              <UserCheck className="h-5 w-5 mr-2 text-cyan-500" />,
              'from-cyan-50',
              'to-teal-50',
              t('vitalsPage.noData.social'),
              undefined,
              'social'
            )}

            {/* Medications */}
            {renderObservationSection(
              t('vitalsPage.sections.medications'),
              patient?.medications || {},
              patient?.medications_timestamps,
              <Pill className="h-5 w-5 mr-2 text-indigo-500" />,
              'from-indigo-50',
              'to-blue-50',
              t('vitalsPage.noData.medications'),
              undefined,
              'medications'
            )}

            {/* Immunizations */}
            {renderObservationSection(
              t('vitalsPage.sections.immunizations'),
              patient?.immunizations || {},
              patient?.immunizations_timestamps,
              <Shield className="h-5 w-5 mr-2 text-green-500" />,
              'from-green-50',
              'to-emerald-50',
              t('vitalsPage.noData.immunizations'),
              undefined,
              'immunizations'
            )}

            {/* Allergies */}
            {renderObservationSection(
              t('vitalsPage.sections.allergies'),
              patient?.allergies || {},
              patient?.allergies_timestamps,
              <AlertTriangle className="h-5 w-5 mr-2 text-red-500" />,
              'from-red-50',
              'to-rose-50',
              t('vitalsPage.noData.allergies'),
              'destructive',
              'allergies'
            )}

            {/* Diagnoses */}
            {renderObservationSection(
              t('vitalsPage.sections.diagnoses'),
              patient?.diagnoses || {},
              patient?.diagnoses_timestamps,
              <FileText className="h-5 w-5 mr-2 text-gray-500" />,
              'from-gray-50',
              'to-slate-50',
              t('vitalsPage.noData.diagnoses'),
              undefined,
              'diagnoses'
            )}

            {/* Medication Statements */}
            {renderObservationSection(
              t('vitalsPage.sections.medicationStatement'),
              patient?.medication_statement || {},
              patient?.medication_statement_timestamps,
              <Pill className="h-5 w-5 mr-2 text-emerald-500" />,
              'from-emerald-50',
              'to-green-50',
              t('vitalsPage.noData.medicationStatement'),
              undefined,
              'medicationStatement'
            )}

            {/* Questionnaire Responses */}
            {renderObservationSection(
              t('vitalsPage.sections.questionnaire'),
              patient?.questionnaire_response || {},
              patient?.questionnaire_response_timestamps,
              <ClipboardList className="h-5 w-5 mr-2 text-violet-500" />,
              'from-violet-50',
              'to-purple-50',
              t('vitalsPage.noData.questionnaire'),
              undefined,
              'questionnaire'
            )}

            {/* Encounters */}
            {renderObservationSection(
              t('vitalsPage.sections.encounters'),
              patient?.encounters || {},
              patient?.encounters_timestamps,
              <Calendar className="h-5 w-5 mr-2 text-blue-500" />,
              'from-blue-50',
              'to-sky-50',
              t('vitalsPage.noData.encounters'),
              undefined,
              'encounters'
            )}

          </div>

          {/* Summary Section */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-bold text-gray-900">{t('vitalsPage.summary.title')}</h2>
            </div>
            <div className="p-6">
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4 text-center">
                <div className="bg-red-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-red-600">
                    {patient?.vitals ? Object.keys(patient.vitals).length : 0}
                  </div>
                  <div className="text-sm text-red-700">{t('vitalsPage.summary.vitals')}</div>
                </div>
                <div className="bg-blue-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-blue-600">
                    {patient?.labs ? Object.keys(patient.labs).length : 0}
                  </div>
                  <div className="text-sm text-blue-700">{t('vitalsPage.summary.labs')}</div>
                </div>
                <div className="bg-purple-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-purple-600">
                    {patient?.imaging ? Object.keys(patient.imaging).length : 0}
                  </div>
                  <div className="text-sm text-purple-700">{t('vitalsPage.summary.imaging')}</div>
                </div>
                <div className="bg-green-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-green-600">
                    {patient?.exam ? Object.keys(patient.exam).length : 0}
                  </div>
                  <div className="text-sm text-green-700">{t('vitalsPage.summary.exam')}</div>
                </div>
                <div className="bg-orange-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-orange-600">
                    {patient?.procedure ? Object.keys(patient.procedure).length : 0}
                  </div>
                  <div className="text-sm text-orange-700">{t('vitalsPage.summary.procedures')}</div>
                </div>
                <div className="bg-emerald-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-emerald-600">
                    {patient?.immunizations ? Object.keys(patient.immunizations).length : 0}
                  </div>
                  <div className="text-sm text-emerald-700">{t('vitalsPage.summary.immunizations')}</div>
                </div>
                <div className="bg-sky-50 p-4 rounded-lg">
                  <div className="text-2xl font-bold text-sky-600">
                    {patient?.encounters ? Object.keys(patient.encounters).length : 0}
                  </div>
                  <div className="text-sm text-sky-700">{t('vitalsPage.summary.encounters')}</div>
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