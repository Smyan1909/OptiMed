"use client";
import ChatBox from "@/components/ChatBox";

export default function GeneralChat() {
  return (
    <section className="max-w-4xl mx-auto py-8">
      <div className="bg-white rounded-xl shadow p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-gray-900">
            Chat with OptiMed AI
          </h1>
          <p className="text-sm text-gray-600">
            General health assistant - No patient context
          </p>
        </div>
        
        <div className="h-[600px]">
          <ChatBox mode="chat" patientId={undefined} />
        </div>
      </div>
    </section>
  );
}