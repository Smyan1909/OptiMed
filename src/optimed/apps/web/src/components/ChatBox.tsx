"use client";

import { useState, useEffect, FormEvent } from "react";
import { useUser } from '@/contexts/UserContext';


interface Message {
  sender: "user" | "system";
  text: string;
  loading?: boolean;
  timestamp?: string;
}

interface ChatBoxProps {
  mode: "chat" | "diagnose";
  patientId?: string;
}

const parseLinksInText = (text: string, isUser: boolean = false) => {
  // Escape HTML first to prevent XSS
  const escapeHtml = (unsafe: string) => {
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  };

  // Escape the text first
  let processedText = escapeHtml(text);
  
  const linkClass = isUser 
    ? "text-blue-200 hover:text-blue-100 underline font-medium transition-colors duration-200 break-words"
    : "text-blue-600 hover:text-blue-800 underline font-medium transition-colors duration-200 break-words";
  
  const externalIcon = `<svg class="w-3 h-3 inline ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>`;
  
  // Regular expressions for different link formats
  const markdownLinkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const urlRegex = /(https?:\/\/[^\s<>]+)/g;
  
  // Handle markdown-style links [text](url) first
  processedText = processedText.replace(markdownLinkRegex, (match, linkText, url) => {
    // Unescape the URL and link text for proper use in href
    const cleanUrl = url.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    const cleanLinkText = linkText.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    
    return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="${linkClass}">${cleanLinkText}${externalIcon}</a>`;
  });
  
  // Handle plain URLs (avoiding already processed markdown links)
  processedText = processedText.replace(urlRegex, (url) => {
    // Skip if this URL is already inside an <a> tag
    const beforeMatch = processedText.substring(0, processedText.indexOf(url));
    if (beforeMatch.includes('<a href=')) {
      // Check if we're inside a recently created link
      const lastLinkStart = beforeMatch.lastIndexOf('<a href=');
      const lastLinkEnd = beforeMatch.lastIndexOf('</a>');
      if (lastLinkStart > lastLinkEnd) {
        return url; // We're inside a link, don't process
      }
    }
    
    const cleanUrl = url.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'");
    const displayUrl = cleanUrl.length > 50 ? cleanUrl.substring(0, 47) + '...' : cleanUrl;
    
    return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="${linkClass}">${displayUrl}${externalIcon}</a>`;
  });
  
  return processedText;
};

interface MessageContentProps {
  text: string;
  isUser: boolean;
}

const MessageContent = ({ text, isUser }: MessageContentProps) => {
  const processedText = parseLinksInText(text, isUser); // Add the isUser parameter here
  
  return (
    <div 
      className={`font-medium whitespace-pre-wrap ${isUser ? 'text-white' : 'text-gray-900'}`}
      dangerouslySetInnerHTML={{ __html: processedText }}
    />
  );
};

const getAuthHeaders = () => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  // Get the authentication session_id from localStorage
  const authToken = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
  if (authToken) {
    headers['X-Session-ID'] = authToken;
  }
  return headers;
};

export default function ChatBox({ mode, patientId }: ChatBoxProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  
  // FIX: Create persistent session ID per patient/mode combination
  const [sessionId] = useState(() => {
    if (typeof window !== 'undefined') {
      const key = `chat_session_${mode}_${patientId || 'general'}`;
      let existing = localStorage.getItem(key);
      if (!existing) {
        existing = `${mode}_${patientId || 'general'}_${Date.now()}`;
        localStorage.setItem(key, existing);
      }
      return existing;
    }
    return `${mode}_${patientId || 'general'}_${Date.now()}`;
  });
  
  const { user } = useUser();

  // Load chat history on component mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        console.log(`Loading history for session: ${sessionId}, patient: ${patientId}`);
        
        const response = await fetch('/api/chat-history', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ 
            patient_id: patientId,
            session_id: sessionId,
            mode: mode
          })
        });
        
        if (response.ok) {
          const data = await response.json();
          console.log('Loaded chat history:', data);
          
          if (data.messages && data.messages.length > 0) {
            const formattedMessages = data.messages.map((msg: any) => ({
              sender: msg.role === 'user' ? 'user' : 'system',
              text: msg.content,
              timestamp: new Date(msg.timestamp || Date.now()).toLocaleTimeString()
            }));
            setMessages(formattedMessages);
          }
        }
      } catch (error) {
        console.error('Failed to load conversation history:', error);
      }
    };

    // Only load if we have a patient ID for diagnosis mode or if it's general chat
    if ((mode === 'diagnose' && patientId) || mode === 'chat') {
      loadHistory();
    }
  }, [sessionId, patientId, mode]);

  // Clear messages when patient changes (but not on initial load)
  useEffect(() => {
    if (patientId) {
      // Only clear if we're switching patients, not on initial load
      const key = `chat_session_${mode}_${patientId}`;
      if (!localStorage.getItem(key)) {
        setMessages([]);
      }
    }
  }, [patientId, mode]);

  // Add welcome message when starting diagnosis mode (only if no history)
  useEffect(() => {
    if (mode === "diagnose" && patientId && messages.length === 0) {
      setMessages([{
        sender: "system",
        text: `Hello! I'm OptiMed AI, ready to help with patient ${patientId}'s diagnosis. Ask me anything about their condition, symptoms, or potential treatments. What would you like to discuss?`,
        timestamp: new Date().toLocaleTimeString()
      }]);
    }
  }, [mode, patientId, messages.length]);

  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userText = input.trim();
    const timestamp = new Date().toLocaleTimeString();
    
    // 1) Add user message
    setMessages((prev) => [
      ...prev, 
      { sender: "user", text: userText, timestamp }
    ]);
    setInput("");

    // 2) Add thinking placeholder
    setMessages((prev) => [
      ...prev,
      { sender: "system", text: "OptiMed is thinking...", loading: true, timestamp },
    ]);
    
    try {
      // 3) Call appropriate backend endpoint
      const endpoint = mode === "chat" ? "/api/chat" : "/api/diagnose";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ 
          patient_id: patientId ?? null,
          user_prompt: userText,
          chat_mode: mode === "chat",
          user_id: user?.user_id,
          session_id: sessionId  // Use the consistent session ID
        }),
      });
      
      const data = await res.json();
      console.log(`🏷️ ${endpoint} returned:`, res.status, data);
      
      // Handle different response formats
      const reply = data.explanation ?? data.message ?? data.response ?? "No reply";

      // 4) Replace placeholder with actual reply
      setMessages((prev) => {
        const withoutLoading = prev.filter((m) => !m.loading);
        return [...withoutLoading, { 
          sender: "system", 
          text: reply,
          timestamp: new Date().toLocaleTimeString()
        }];
      });
    } catch (error) {
      console.error('Chat error:', error);
      setMessages((prev) => {
        const withoutLoading = prev.filter((m) => !m.loading);
        return [
          ...withoutLoading,
          { 
            sender: "system", 
            text: "Error contacting server. Please try again.",
            timestamp: new Date().toLocaleTimeString()
          },
        ];
      });
    }
  };

  const getPlaceholderText = () => {
    if (mode === "chat") return "Type your message...";
    if (mode === "diagnose" && patientId) return "Ask about diagnosis, symptoms, treatments...";
    return "How can I help with the diagnosis?";
  };

  const getEmptyStateText = () => {
    if (mode === "chat") return "Start chatting with OptiMed...";
    if (mode === "diagnose" && patientId) return "AI diagnosis assistant ready for patient consultation";
    return "Enter patient details to begin diagnosis...";
  };

  return (
    <div className="flex flex-col h-full border rounded-lg bg-white shadow-sm">
      {/* Chat Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <div className="text-gray-500 text-lg mb-2">🤖</div>
            <p className="text-gray-600 font-medium italic">
              {getEmptyStateText()}
            </p>
          </div>
        )}
        
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}>
            <div className="max-w-[80%]">
              <div className={`px-4 py-3 rounded-lg ${
                msg.sender === "user" 
                  ? "bg-blue-600 text-white" 
                  : "bg-gray-100 text-gray-900 border"
              }`}>
                {msg.loading ? (
                  <span className="flex items-center">
                    <div className="animate-spin h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full mr-2"></div>
                    <span className="animate-pulse text-gray-600">{msg.text}</span>
                  </span>
                ) : (
                  <MessageContent text={msg.text} isUser={msg.sender === "user"} />
                )}
              </div>
              {msg.timestamp && (
                <div className={`text-xs mt-1 ${
                  msg.sender === "user" ? "text-right text-gray-500" : "text-left text-gray-500"
                }`}>
                  {msg.timestamp}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Input Form */}
      <div className="border-t bg-gray-50 p-4">
        <form onSubmit={sendMessage} className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={getPlaceholderText()}
            className="flex-1 border border-gray-300 bg-white placeholder-gray-500 text-gray-900 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-medium"
          />
          <button
            type="submit"
            disabled={!input.trim()}
            className="px-6 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </form>
        
        {mode === "diagnose" && user && (
          <div className="mt-2 text-xs text-gray-600 text-center">
            Consulting as <span className="font-semibold">{user.display_name}</span> ({user.role})
          </div>
        )}
      </div>
    </div>
  );
}