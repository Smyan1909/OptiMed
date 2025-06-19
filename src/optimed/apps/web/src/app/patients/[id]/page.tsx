'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchPatient, PatientDetail, diagnoseWithUser, chatWithUser } from "@/lib/api";
import { useUser } from '@/contexts/UserContext';
import ChatBox from "@/components/ChatBox";
import { Badge } from "@/components/ui/badge";

function PatientDetailContent() {
  const params = useParams();
  const router = useRouter();
  const { user } = useUser();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
                <div className="text-right">
                  <Badge variant="success" className="text-sm px-3 py-1">
                    ✅ Active
                  </Badge>
                </div>
              </div>
            </div>
            
            {/* Patient Info Grid */}
            <div className="px-6 py-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <h3 className="text-sm font-bold text-gray-900 mb-2">Demographics</h3>
                  <div className="space-y-1">
                    <p className="text-sm text-gray-900 font-medium">Age: {patient?.age} years</p>
                    <p className="text-sm text-gray-900 font-medium">Sex: {patient?.sex}</p>
                    <p className="text-sm text-gray-900 font-medium">Unit: {patient?.care_unit}</p>
                  </div>
                </div>
                
                <div>
                  <h3 className="text-sm font-bold text-gray-900 mb-2">Vital Signs</h3>
                  <div className="space-y-1">
                    {patient?.vitals && Object.keys(patient.vitals).length > 0 ? (
                      Object.entries(patient.vitals).map(([key, value]) => (
                        <p key={key} className="text-sm text-gray-900 font-medium">
                          {key}: <Badge variant="outline" className="ml-1">{value}</Badge>
                        </p>
                      ))
                    ) : (
                      <p className="text-sm text-gray-600 font-medium">No vitals recorded</p>
                    )}
                  </div>
                </div>
                
                <div>
                  <h3 className="text-sm font-bold text-gray-900 mb-2">Lab Results</h3>
                  <div className="space-y-1">
                    {patient?.labs && Object.keys(patient.labs).length > 0 ? (
                      Object.entries(patient.labs).map(([key, value]) => (
                        <p key={key} className="text-sm text-gray-900 font-medium">
                          {key}: <Badge variant="secondary" className="ml-1">{value}</Badge>
                        </p>
                      ))
                    ) : (
                      <p className="text-sm text-gray-600 font-medium">No lab results</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* AI Diagnosis Chat Section */}
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
            
            <div className="p-6">
              <div className="h-[600px]">
                <ChatBox mode="diagnose" patientId={patientId} />
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