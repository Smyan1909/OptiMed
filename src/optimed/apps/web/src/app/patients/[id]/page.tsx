"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import ChatBox from "@/components/ChatBox";
import { fetchPatient } from "@/lib/api";
import type { PatientDetail } from "@/lib/api";

export default function PatientDetail() {
  const { id } = useParams();
  const router = useRouter();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"chat" | "diagnose">("chat");

  useEffect(() => {
    if (!id) return;
    const pid = Array.isArray(id) ? id[0] : id;
    fetchPatient(pid)
      .then(setPatient)
      .catch(() => setPatient(null))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <p className="text-center py-8 text-lg text-gray-700">Loading patient…</p>;
  }
  if (!patient) {
    return <p className="text-center py-8 text-lg text-red-600">Patient not found.</p>;
  }

  return (
    <section className="max-w-6xl mx-auto py-8 space-y-8">
      <div className="flex items-center justify-between">
        <button
          onClick={() => router.push("/patients")}
          className="text-blue-600 hover:text-blue-800 font-medium"
        >
          ← Back to patients
        </button>
        <h1 className="text-2xl font-bold text-white-900">
          Patient: {patient.name}
        </h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Sidebar */}
        <aside className="space-y-8">
          {/* Demographics */}
          <div className="bg-blue-50 p-6 rounded-xl shadow">
            <h2 className="text-xl font-semibold text-blue-600 mb-4">Demographics</h2>
            <ul className="space-y-2 text-gray-900">
              <li><span className="font-medium">Name:</span> {patient.name}</li>
              <li><span className="font-medium">Age:</span> {patient.age}</li>
              <li><span className="font-medium">Sex:</span> {patient.sex}</li>
              <li><span className="font-medium">Unit:</span> {patient.care_unit}</li>
            </ul>
          </div>

          {/* Vitals */}
          <div className="bg-white p-6 rounded-xl shadow border-l-4 border-green-500">
            <h2 className="text-lg font-semibold text-green-600 mb-4">Vitals</h2>
            <dl className="grid grid-cols-1 gap-y-2 text-gray-800">
              {Object.entries(patient.vitals).map(([code, raw]) => {
                const parts = raw.split(/\s+/);
                const num = parseFloat(parts[0]);
                const displayValue = isNaN(num) ? raw : num.toFixed(2);
                const displayUnit = isNaN(num) ? "" : parts.slice(1).join(" ");
                return (
                  <div key={code} className="flex justify-between">
                    <dt className="font-medium">{code}</dt>
                    <dd className="text-right">
                      {displayValue}
                      {displayUnit && <> {displayUnit}</>}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>

          {/* Laboratory */}
          <div className="bg-white p-6 rounded-xl shadow border-l-4 border-purple-500">
            <h2 className="text-lg font-semibold text-purple-600 mb-4">Laboratory</h2>
            <dl className="grid grid-cols-1 gap-y-2 text-gray-800">
              {Object.entries(patient.labs).map(([code, raw]) => {
                const parts = raw.split(/\s+/);
                const num = parseFloat(parts[0]);
                const displayValue = isNaN(num) ? raw : num.toFixed(2);
                const displayUnit = isNaN(num) ? "" : parts.slice(1).join(" ");
                return (
                  <div key={code} className="flex justify-between">
                    <dt className="font-medium">{code}</dt>
                    <dd className="text-right">
                      {displayValue}
                      {displayUnit && <> {displayUnit}</>}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        </aside>

        {/* Main chat/diagnose */}
        <main className="lg:col-span-2 bg-white rounded-xl shadow flex flex-col p-6 h-[700px]">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-semibold text-gray-900">
              {mode === "chat" ? "Chat with OptiMed" : "Diagnosis Assistant"}
            </h1>
            <label className="inline-flex items-center space-x-3">
              <span className={mode === "chat" ? "text-blue-600" : "text-gray-500"}>Chat</span>
              <input
                type="checkbox"
                checked={mode === "diagnose"}
                onChange={() => setMode((m) => (m === "chat" ? "diagnose" : "chat"))}
                className="relative inline-block w-12 h-6 bg-gray-300 rounded-full transition-colors checked:bg-blue-600"
              />
              <span className={mode === "diagnose" ? "text-blue-600" : "text-gray-500"}>
                Diagnose
              </span>
            </label>
          </div>
          <ChatBox mode={mode} patientId={patient.id} />
        </main>
      </div>
    </section>
  );
}