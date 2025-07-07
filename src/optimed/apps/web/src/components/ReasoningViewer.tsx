import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Brain, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';

interface ReasoningViewerProps {
  reasoning: string;
  reasoningSteps?: string[];
}

// Custom components for markdown rendering
const MarkdownComponents = {
  // Style headings
  h1: ({ children }: any) => <h1 className="text-lg font-bold text-blue-900 mt-4 mb-2">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-base font-semibold text-blue-900 mt-3 mb-2">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-sm font-medium text-blue-900 mt-2 mb-1">{children}</h3>,
  
  // Style paragraphs
  p: ({ children }: any) => <p className="text-sm text-blue-900 leading-relaxed mb-2">{children}</p>,
  
  // Style lists
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-1 ml-2 mb-2">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-1 ml-2 mb-2">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-blue-900">{children}</li>,
  
  // Style code blocks
  code: ({ inline, children }: any) => {
    if (inline) {
      return <code className="bg-blue-100 text-blue-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
    }
    return (
      <pre className="bg-blue-100 text-blue-800 p-3 rounded text-xs font-mono overflow-x-auto mb-2">
        <code>{children}</code>
      </pre>
    );
  },
  
  // Style blockquotes
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-4 border-blue-300 pl-3 italic text-blue-800 mb-2">
      {children}
    </blockquote>
  ),
  
  // Style strong/bold text
  strong: ({ children }: any) => <strong className="font-semibold text-blue-900">{children}</strong>,
  
  // Style emphasis/italic text
  em: ({ children }: any) => <em className="italic text-blue-800">{children}</em>,
  
  // Style links
  a: ({ href, children }: any) => (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer" 
      className="text-blue-600 hover:text-blue-800 underline"
    >
      {children}
    </a>
  ),
  
  // Style tables
  table: ({ children }: any) => (
    <div className="overflow-x-auto mb-2">
      <table className="min-w-full border-collapse border border-blue-200">{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th className="border border-blue-200 bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-blue-200 px-2 py-1 text-xs text-blue-900">{children}</td>
  ),
};

export const ReasoningViewer: React.FC<ReasoningViewerProps> = ({
  reasoning,
  reasoningSteps = []
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      const contentToCopy = reasoning || reasoningSteps.join('\n\n');
      await navigator.clipboard.writeText(contentToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy reasoning:', error);
    }
  };

  // Enhanced check for reasoning content
  const hasReasoning = (reasoning && reasoning.trim().length > 0) || 
                      (reasoningSteps && reasoningSteps.length > 0 && reasoningSteps.some(step => step.trim().length > 0));

  if (!hasReasoning) {
    console.log('🔍 ReasoningViewer: No reasoning content found', { reasoning: !!reasoning, reasoningSteps: reasoningSteps?.length });
    return null;
  }

  console.log('🧠 ReasoningViewer: Displaying reasoning', { 
    reasoning: !!reasoning, 
    reasoningSteps: reasoningSteps?.length,
    firstStep: reasoningSteps?.[0]?.substring(0, 50) 
  });

  return (
    <div className="mt-3">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setIsExpanded(!isExpanded)}
        className="text-blue-600 hover:text-blue-800 hover:bg-blue-50 p-0 h-auto font-normal"
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 mr-1" />
        ) : (
          <ChevronRight className="h-4 w-4 mr-1" />
        )}
        <Brain className="h-4 w-4 mr-1" />
        Show AI Reasoning Process
        <Badge variant="secondary" className="ml-2 text-xs">
          {reasoningSteps?.length || 1} steps
        </Badge>
      </Button>

      {isExpanded && (
        <Card className="mt-2 border-blue-200 bg-blue-50">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Brain className="h-4 w-4 text-blue-600" />
                <span className="text-blue-900">AI Reasoning Process</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="h-8 text-xs"
              >
                {copied ? (
                  <>
                    <Check className="h-3 w-3 mr-1" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3 mr-1" />
                    Copy
                  </>
                )}
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {reasoningSteps && reasoningSteps.length > 0 ? (
                // Show structured reasoning steps with markdown support
                <div className="space-y-3">
                  {reasoningSteps.map((step, index) => (
                    <div key={index} className="bg-white/80 p-3 rounded border-l-4 border-blue-400">
                      <div className="flex items-start gap-2">
                        <Badge variant="outline" className="text-xs mt-0.5 flex-shrink-0">
                          {index + 1}
                        </Badge>
                        <div className="flex-1 min-w-0">
                          <div className="reasoning-markdown">
                            <ReactMarkdown
                              components={MarkdownComponents}
                              remarkPlugins={[remarkGfm]}
                            >
                              {step}
                            </ReactMarkdown>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="bg-white/80 p-4 rounded border-l-4 border-blue-400">
                  <div className="reasoning-markdown">
                    <ReactMarkdown
                      components={MarkdownComponents}
                      remarkPlugins={[remarkGfm]}
                    >
                      {reasoning}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};