"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchPatients, Patient } from "@/lib/api";

export default function PatientsList() {
  const [query, setQuery] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const results = await fetchPatients(query);
      setPatients(results);
    } catch (err: any) {
      setError(err.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  // initial load
  useEffect(() => {
    doSearch();
  }, []);

  return (
    <section className="py-8 max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-4 text-center">Patients</h1>

      <form onSubmit={doSearch} className="mb-6 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by name…"
          className="flex-1 border border-gray-300 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-600"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition"
          disabled={loading}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && <p className="text-red-600 text-center mb-4">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {!loading && patients.length === 0 && (
          <p className="text-center text-gray-500 col-span-full">
            No patients found.
          </p>
        )}

        {patients.map((p) => (
          <Link
            key={p.id}
            href={`/patients/${p.id}`}
            className="block no-underline"
          >
            <div className="bg-white p-6 rounded-lg shadow hover:shadow-lg transition-shadow duration-200 cursor-pointer">
              <p className="text-lg font-semibold text-gray-900">{p.name}</p>
              {p.dob && <p className="text-sm text-gray-600">DOB: {p.dob}</p>}
              {p.age !== undefined && (
                <p className="text-sm text-gray-600">Age: {p.age}</p>
              )}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}