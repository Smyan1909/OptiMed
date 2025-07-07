"use client";

import { useState, useEffect, FormEvent } from "react";
import { useUser } from '@/contexts/UserContext';
import { Download, Image as ImageIcon, ExternalLink } from 'lucide-react';
import { getGeneratedImageUrl, downloadGeneratedImage } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import { useStreamingChat } from "@/hooks/useStreamingChat";
import { StreamingProgress } from "./StreamingProgress";
import { ReasoningViewer } from "./ReasoningViewer";

export interface GeneratedImageInfo {
  image_generated: boolean;
  image_id?: string;
  image_prompt?: string;
  generation_metadata?: Record<string, any>;
  model_info?: Record<string, any>;
}

export interface ImageGenerationRequest {
  prompt: string;
  width?: number;
  height?: number;
  patient_id?: string;
}

export interface GeneratedImageResponse {
  success: boolean;
  image_id: string;
  prompt: string;
  created_at: string;
  metadata: Record<string, any>;
  model_info: Record<string, any>;
}

interface Message {
  sender: "user" | "system";
  text: string;
  loading?: boolean;
  timestamp?: string;
  generatedImage?: GeneratedImageInfo;
  reasoningSteps?: string[];
  reasoning?: string;
}

interface ChatBoxProps {
  mode: "chat" | "diagnose";
  patientId?: string;
  sessionId?: string | null; // Optional session ID for diagnosis mode
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
  // Custom components for markdown rendering
  const markdownComponents = {
    // Links
    a: ({ href, children }: any) => (
      <a 
        href={href} 
        target="_blank" 
        rel="noopener noreferrer" 
        className={isUser 
          ? "text-blue-200 hover:text-blue-100 underline font-medium transition-colors duration-200 break-words"
          : "text-blue-600 hover:text-blue-800 underline font-medium transition-colors duration-200 break-words"
        }
      >
        {children}
        <svg className="w-3 h-3 inline ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
        </svg>
      </a>
    ),
    // Headers
    h1: ({ children }: any) => (
      <h1 className={`text-xl font-bold mb-2 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </h1>
    ),
    h2: ({ children }: any) => (
      <h2 className={`text-lg font-bold mb-2 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className={`text-md font-bold mb-1 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </h3>
    ),
    // Emphasis
    strong: ({ children }: any) => (
      <strong className={`font-bold ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </strong>
    ),
    em: ({ children }: any) => (
      <em className={`italic ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </em>
    ),
    // Code
    code: ({ children, className }: any) => {
      const isCodeBlock = className?.includes('language-');
      if (isCodeBlock) {
        return (
          <pre className={`bg-gray-800 text-green-400 p-3 rounded-lg overflow-x-auto text-sm my-2 ${isUser ? 'bg-gray-700' : 'bg-gray-800'}`}>
            <code className="font-mono">{children}</code>
          </pre>
        );
      }
      return (
        <code className={`px-1 py-0.5 rounded text-sm font-mono ${
          isUser 
            ? 'bg-blue-700 text-blue-100' 
            : 'bg-gray-200 text-gray-800'
        }`}>
          {children}
        </code>
      );
    },
    // Lists
    ul: ({ children }: any) => (
      <ul className={`list-disc list-inside my-2 space-y-1 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </ul>
    ),
    ol: ({ children }: any) => (
      <ol className={`list-decimal list-inside my-2 space-y-1 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </ol>
    ),
    li: ({ children }: any) => (
      <li className={`${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </li>
    ),
    // Blockquotes
    blockquote: ({ children }: any) => (
      <blockquote className={`border-l-4 pl-4 my-2 italic ${
        isUser 
          ? 'border-blue-300 text-blue-100' 
          : 'border-gray-400 text-gray-700'
      }`}>
        {children}
      </blockquote>
    ),
    // Paragraphs
    p: ({ children }: any) => (
      <p className={`mb-2 last:mb-0 ${isUser ? 'text-white' : 'text-gray-900'}`}>
        {children}
      </p>
    ),
    // Horizontal rule
    hr: () => (
      <hr className={`my-3 border-t ${
        isUser ? 'border-blue-300' : 'border-gray-300'
      }`} />
    ),
  };
  
  return (
    <div className={`font-medium ${isUser ? 'text-white' : 'text-gray-900'}`}>
      <ReactMarkdown components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
};

// ...existing code...
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


const GeneratedImageDisplay = ({ imageInfo }: { imageInfo: GeneratedImageInfo }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoading, setImageLoading] = useState(true);
  const [imageUrl, setImageUrl] = useState<string>('');

  // DEBUG: Log what we received
  useEffect(() => {
    console.log('🖼️ GeneratedImageDisplay received:', imageInfo);
    console.log('Image generated?', imageInfo.image_generated);
    console.log('Image ID?', imageInfo.image_id);
  }, [imageInfo]);

  // Load image with proper headers
  useEffect(() => {
    if (imageInfo.image_generated && imageInfo.image_id) {
      const loadImageWithHeaders = async () => {
        try {
          console.log('Loading image with headers:', imageInfo.image_id);
          const response = await fetch(`/api/images/generated/${imageInfo.image_id}`, {
            headers: getAuthHeaders()
          });
          
          if (response.ok) {
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            setImageUrl(url);
            console.log('Image loaded successfully');
          } else {
            console.error('Failed to load image:', response.status, response.statusText);
            setImageError(true);
          }
        } catch (error) {
          console.error('Error loading image:', error);
          setImageError(true);
        } finally {
          setImageLoading(false);
        }
      };

      loadImageWithHeaders();
    }
  }, [imageInfo.image_generated, imageInfo.image_id]);

  // Cleanup blob URL when component unmounts
  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

  if (!imageInfo.image_generated || !imageInfo.image_id) {
    console.log('🚫 Not displaying image - image_generated:', imageInfo.image_generated, 'image_id:', imageInfo.image_id);
    return null;
  }

  const handleDownload = async () => {
    try {
      await downloadGeneratedImage(imageInfo.image_id!, `generated_${imageInfo.image_id}.png`);
    } catch (error) {
      console.error('Error downloading image:', error);
      alert('Failed to download image');
    }
  };

  const handleOpenInNewTab = async () => {
    try {
      const imageUrl = await getGeneratedImageUrl(imageInfo.image_id!);
      window.open(imageUrl, '_blank');
    } catch (error) {
      console.error('Error opening image:', error);
      alert('Failed to open image');
    }
  };

  const handleImageLoad = () => {
    console.log('✅ Image displayed successfully');
    setImageError(false);
  };

  const handleImageError = (e: any) => {
    console.error('❌ Failed to display image:', e);
    setImageError(true);
  };

  return (
    <div className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
      <div className="flex items-center gap-2 mb-2">
        <ImageIcon className="h-4 w-4 text-blue-600" />
        <span className="text-sm font-medium text-gray-700">Generated Educational Image</span>
      </div>
      
      <div className="mb-2">
        {imageLoading && !imageError && (
          <div className="flex items-center justify-center p-4 bg-gray-100 rounded border">
            <div className="animate-spin h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full mr-2"></div>
            <span className="text-sm text-gray-600">Loading image...</span>
          </div>
        )}
        
        {imageError ? (
          <div className="p-4 bg-red-50 border border-red-200 rounded text-center">
            <p className="text-sm text-red-600 mb-2">Failed to load image</p>
            <p className="text-xs text-gray-500 mb-2">Image ID: {imageInfo.image_id}</p>
            <button
              onClick={() => {
                console.log('🔄 Retrying image load');
                setImageError(false);
                setImageLoading(true);
                // Trigger re-load by updating a dependency
                window.location.reload();
              }}
              className="text-xs text-blue-600 hover:text-blue-800 underline"
            >
              Retry
            </button>
          </div>
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt="Generated medical illustration"
            className="max-w-full h-auto rounded border border-gray-300 shadow-sm"
            style={{ 
              maxHeight: '300px'
            }}
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        ) : null}
      </div>
      
      {imageInfo.image_prompt && (
        <p className="text-xs text-gray-600 mb-2">
          <strong>Prompt:</strong> {imageInfo.image_prompt}
        </p>
      )}
      
      <div className="flex gap-2">
        <button
          onClick={handleDownload}
          className="flex items-center gap-1 px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 transition-colors"
        >
          <Download className="h-3 w-3" />
          Download
        </button>
        <button
          onClick={handleOpenInNewTab}
          className="flex items-center gap-1 px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700 transition-colors"
        >
          <ExternalLink className="h-3 w-3" />
          Open in New Tab
        </button>
      </div>
    </div>
  );
};

export default function ChatBox({ mode, patientId, sessionId: propSessionId }: ChatBoxProps) {
  // ...existing code...
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const {
    isStreaming,
    currentStep,
    currentDescription,
    reasoning,
    currentReasoning,
    finalResponse,
    generatedImage, // Add this - it was missing!
    error: streamError,
    progress,
    startStream,
    stopStream,
  } = useStreamingChat();

  // Use provided sessionId or generate one
  const [sessionId] = useState(() => {
    if (propSessionId) return propSessionId;
    
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

  // Update sessionId when prop changes
  useEffect(() => {
    if (propSessionId && propSessionId !== sessionId) {
      // Clear messages when switching sessions
      setMessages([]);
    }
  }, [propSessionId]);

  // Use propSessionId if provided, otherwise use generated sessionId
  const currentSessionId = propSessionId || sessionId;

  // Load chat history on component mount or session change
  useEffect(() => {
    const loadHistory = async () => {
      try {
        console.log(`Loading history for session: ${currentSessionId}, patient: ${patientId}`);
        
        const response = await fetch('/api/chat-history', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ 
            patient_id: patientId,
            session_id: currentSessionId,
            mode: mode
          })
        });
        
        if (response.ok) {
          const data = await response.json();
          console.log('Loaded chat history:', data);
          
          if (data.messages && data.messages.length > 0) {
            const formattedMessages = data.messages.map((msg: any) => {
              const formattedMessage: Message = {
                sender: msg.role === 'user' ? 'user' : 'system',
                text: msg.content,
                timestamp: msg.timestamp ? new Date(parseInt(msg.timestamp)).toLocaleTimeString() : new Date().toLocaleTimeString()
              };
              
              // Add reasoning from multiple possible sources
              if (msg.reasoning || msg.reasoning_steps) {
                console.log('🧠 Found reasoning in chat history:', {
                  reasoning: !!msg.reasoning,
                  reasoningSteps: msg.reasoning_steps?.length || 0
                });
                
                // Use reasoning from content first, then from steps
                formattedMessage.reasoning = msg.reasoning || (msg.reasoning_steps ? msg.reasoning_steps.join('\n') : '');
                formattedMessage.reasoningSteps = msg.reasoning_steps || [];
              }
              
              // Add generated image info if present
              if (msg.generated_image && msg.generated_image.image_generated) {
                formattedMessage.generatedImage = msg.generated_image;
                console.log('📸 Found image in chat history:', msg.generated_image.image_id);
              }
              
              return formattedMessage;
            });
            setMessages(formattedMessages);
            
            // Log reasoning data for debugging
            const messagesWithReasoning: Message[] = formattedMessages.filter((msg: Message) => msg.reasoning || (msg.reasoningSteps && msg.reasoningSteps.length > 0));
            console.log(`📊 Loaded ${formattedMessages.length} messages, ${messagesWithReasoning.length} with reasoning`);
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
  }, [currentSessionId, patientId, mode]);

  useEffect(() => {
    console.log('📧 Final response effect:', { finalResponse, isStreaming, reasoning, generatedImage });
    if (finalResponse && !isStreaming) {
      console.log('✅ Adding final response to messages:', finalResponse);
      setMessages((prev) => {
        const lastMessage = prev[prev.length - 1];
        if (lastMessage && lastMessage.sender === "system" && lastMessage.text === finalResponse) {
          console.log('⚠️ Duplicate message prevented');
          return prev;
        }
        
        // Convert streaming generatedImage format to Message generatedImage format
        let formattedGeneratedImage: GeneratedImageInfo | undefined = undefined;
        if (generatedImage) {
          formattedGeneratedImage = {
            image_generated: true,
            image_id: generatedImage.image_id,
            image_prompt: generatedImage.prompt,
            generation_metadata: generatedImage.metadata || {},
            model_info: {}
          };
          console.log('🖼️ Including generated image in message:', formattedGeneratedImage);
        }
        
        return [
          ...prev,
          { 
            sender: "system", 
            text: finalResponse,
            timestamp: new Date().toLocaleTimeString(),
            reasoning: reasoning.join('\n'),
            reasoningSteps: reasoning,
            generatedImage: formattedGeneratedImage
          }
        ];
      });
    }
  }, [finalResponse, isStreaming, reasoning, generatedImage]);


  // Handle streaming errors
  useEffect(() => {
    if (streamError) {
      console.error('❌ Stream error:', streamError);
      setMessages((prev) => [
        ...prev,
        { 
          sender: "system", 
          text: `Error: ${streamError}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  }, [streamError]);
  // ... rest of existing code, but use currentSessionId in sendMessage
  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;

    const userText = input.trim();
    const timestamp = new Date().toLocaleTimeString();
    
    // 1) Add user message
    setMessages((prev) => [
      ...prev, 
      { sender: "user", text: userText, timestamp }
    ]);
    setInput("");

    try {
      // 2) Start streaming
      const endpoint = mode === "chat" ? "/api/chat/stream" : "/api/diagnose/stream";
      const sessionId = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
      
      const payload = { 
        patient_id: patientId ?? null,
        user_prompt: userText,
        chat_mode: mode === "chat",
        user_id: user?.user_id,
        session_id: currentSessionId
      };

      await startStream(endpoint, payload, sessionId || undefined);

    } catch (error) {
      console.error('Streaming error:', error);
      setMessages((prev) => [
        ...prev,
        { 
          sender: "system", 
          text: "Error starting analysis. Please try again.",
          timestamp: new Date().toLocaleTimeString()
        },
      ]);
    }
  };

  const getPlaceholderText = () => {
    if (mode === "chat") return "Type your message...";
    if (mode === "diagnose" && patientId) return "Ask about diagnosis, symptoms, treatments...";
    return "How can I help with the diagnosis?";
  };

  const getEmptyStateText = () => {
    if (mode === "chat") return "Start chatting with CLARA...";
    if (mode === "diagnose" && patientId) return "CLARA FÄRDIGA GÅ";
    return "Enter patient details to begin diagnosis...";
  };

  useEffect(() => {
    if (streamError) {
      setMessages((prev) => [
        ...prev,
        { 
          sender: "system", 
          text: `Error: ${streamError}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  }, [streamError]);

  return (
    <div className="flex flex-col h-full border rounded-lg bg-white shadow-sm">
      {/* Chat Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center py-8">
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
                <MessageContent text={msg.text} isUser={msg.sender === "user"} />
              </div>
              
              {/* Display generated image if available */}
              {msg.generatedImage && (
                <GeneratedImageDisplay imageInfo={msg.generatedImage} />
              )}
              
              {/* Display reasoning viewer for system messages */}
              {msg.sender === "system" && (msg.reasoning || (msg.reasoningSteps && msg.reasoningSteps.length > 0)) && (
                <ReasoningViewer 
                  reasoning={msg.reasoning || ''} 
                  reasoningSteps={msg.reasoningSteps} 
                />
              )}
              
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

        {/* Streaming Progress - simplified to show only steps */}
        <StreamingProgress
          isStreaming={isStreaming}
          currentStep={currentStep}
          currentDescription={currentDescription}
          progress={progress}
          reasoning={reasoning}
          currentReasoning={currentReasoning}
        />
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
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="px-6 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isStreaming ? 'Analyzing...' : 'Send'}
          </button>
          {isStreaming && (
            <button
              type="button"
              onClick={stopStream}
              className="px-4 py-2 bg-gray-600 text-white font-semibold rounded-lg hover:bg-gray-700 transition-colors"
            >
              Stop
            </button>
          )}
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