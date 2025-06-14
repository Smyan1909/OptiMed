"use client";
import { useState, FormEvent, useEffect } from "react";

interface Message {
  sender: "user" | "system";
  text: string;
  loading?: boolean;
}

interface ChatBoxProps {
  mode: "chat" | "diagnose";
  patientId?: string;
}

export default function ChatBox({ mode, patientId }: ChatBoxProps) {
  const [chatHistory, setChatHistory] = useState<Message[]>([]);
  const [diagnoseHistory, setDiagnoseHistory] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  // Use different history based on mode
  const messages = mode === "chat" ? chatHistory : diagnoseHistory;
  const setMessages = mode === "chat" ? setChatHistory : setDiagnoseHistory;

  // Clear histories when patient changes
  useEffect(() => {
    setChatHistory([]);
    setDiagnoseHistory([]);
  }, [patientId]);

  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userText = input.trim();
    // 1) show user message
    setMessages((prev) => [...prev, { sender: "user", text: userText }]);
    setInput("");

    // 2) show thinking placeholder
    setMessages((prev) => [
      ...prev,
      { sender: "system", text: "OptiMed is thinking...", loading: true },
    ]);
    
    try {
      // 3) call appropriate backend endpoint
      const endpoint = mode === "chat" ? "/api/chat" : "/api/diagnose";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            patient_id: patientId ?? null,
            user_prompt: userText,
            chat_mode: mode === "chat"
         }),
      });
      const data = await res.json();
      console.log(`🏷️  ${endpoint} returned:`, res.status, data);
      
      // Handle different response formats
      const reply = data.explanation ?? data.message ?? data.response ?? "No reply";

      // 4) replace placeholder with actual reply
      setMessages((prev) => {
        const withoutLoading = prev.filter((m) => !m.loading);
        return [...withoutLoading, { sender: "system", text: reply }];
      });
    } catch {
      setMessages((prev) => {
        const withoutLoading = prev.filter((m) => !m.loading);
        return [
          ...withoutLoading,
          { sender: "system", text: "Error contacting server." },
        ];
      });
    }
  };

  return (
    <div className="flex flex-col h-full border rounded-lg p-4 bg-white">
      <div className="flex-1 overflow-y-auto mb-4 space-y-2">
        {messages.length === 0 && (
          <p className="text-gray-400 italic">
            {mode === "chat"
              ? "Start chatting with OptiMed..."
              : "Enter patient details to diagnose..."}
          </p>
        )}
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${
              msg.sender === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-xs px-3 py-2 rounded-lg ${
                msg.sender === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {msg.loading ? (
                <span className="animate-pulse text-gray-500">
                  {msg.text}
                </span>
              ) : (
                msg.text
              )}
            </div>
          </div>
        ))}
      </div>
      <form onSubmit={sendMessage} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            mode === "chat"
              ? "Type your message..."
              : "How do you want help with the diagnoses?"
          }
          className="
            flex-1
            border border-gray-300
            bg-gray-50
            placeholder-gray-400
            text-gray-900
            rounded
            px-3 py-2
            focus:outline-none
            focus:ring-2 focus:ring-blue-600
            focus:border-transparent
          "
        />
        <button
          type="submit"
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition"
        >
          Send
        </button>
      </form>
    </div>
  );
}