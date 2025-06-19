'use client';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { Header } from '@/components/Header';
import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchPatients, Patient } from "@/lib/api";
import { useUser } from '@/contexts/UserContext';

function PatientsPageContent() {
  const [query, setQuery] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useUser();

  const doSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const results = await fetchPatients(query);
      setPatients(results);
    } catch (err: any) {
      setError(err.message || "Search failed");
      console.error('Patient search error:', err);
    } finally {
      setLoading(false);
    }
  };

  // initial load
  useEffect(() => {
    doSearch();
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          {/* Welcome Section */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900">Patient Directory</h1>
            <p className="mt-2 text-gray-600">
              Welcome back, {user?.display_name}. Search and manage your patients.
            </p>
          </div>

          {/* Search Section */}
          <div className="bg-white shadow rounded-lg p-6 mb-6">
            <form onSubmit={doSearch} className="flex gap-4">
              <div className="flex-1">
                <label htmlFor="search" className="block text-sm font-medium text-gray-700 mb-2">
                  Search Patients
                </label>
                <input
                  id="search"
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by name, MRN, or ID..."
                  className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div className="flex items-end">
                <button
                  type="submit"
                  className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={loading}
                >
                  {loading ? (
                    <span className="flex items-center">
                      <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2"></div>
                      Searching...
                    </span>
                  ) : (
                    'Search'
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-6">
              <div className="flex">
                <div className="flex-shrink-0">
                  <span className="text-red-400">⚠️</span>
                </div>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">Search Error</h3>
                  <div className="mt-2 text-sm text-red-700">
                    <p>{error}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Results Section */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-medium text-gray-900">
                {loading ? 'Searching...' : `${patients.length} Patient${patients.length !== 1 ? 's' : ''} Found`}
              </h2>
            </div>

            {/* Loading State */}
            {loading && (
              <div className="p-12 text-center">
                <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                <p className="text-gray-500">Searching patients...</p>
              </div>
            )}

            {/* Empty State */}
            {!loading && patients.length === 0 && (
              <div className="p-12 text-center">
                <div className="text-gray-400 text-6xl mb-4">👥</div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">No patients found</h3>
                <p className="text-gray-500">
                  {query ? `No patients match "${query}". Try a different search term.` : 'No patients available.'}
                </p>
              </div>
            )}

            {/* Patient List */}
            {!loading && patients.length > 0 && (
              <div className="divide-y divide-gray-200">
                {patients.map((patient) => (
                  <Link
                    key={patient.id}
                    href={`/patients/${patient.id}`}
                    className="block hover:bg-gray-50 transition-colors"
                  >
                    <div className="px-6 py-4">
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                          <div className="flex items-center">
                            <div className="flex-shrink-0">
                              <div className="h-10 w-10 bg-blue-100 rounded-full flex items-center justify-center">
                                <span className="text-blue-600 font-medium text-sm">
                                  {patient.name.split(' ').map(n => n[0]).join('').substring(0, 2)}
                                </span>
                              </div>
                            </div>
                            <div className="ml-4">
                              <div className="flex items-center">
                                <h3 className="text-lg font-medium text-gray-900">{patient.name}</h3>
                                <span className="ml-2 px-2 py-1 text-xs bg-green-100 text-green-800 rounded-full">
                                  Active
                                </span>
                              </div>
                              <div className="mt-1 flex items-center space-x-4 text-sm text-gray-500">
                                <span>ID: {patient.id}</span>
                                {patient.age !== undefined && <span>Age: {patient.age}</span>}
                                {patient.dob && <span>DOB: {patient.dob}</span>}
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="flex-shrink-0">
                          <span className="text-gray-400">→</span>
                        </div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function PatientsPage() {
  return (
    <ProtectedRoute>
      <PatientsPageContent />
    </ProtectedRoute>
  );
}