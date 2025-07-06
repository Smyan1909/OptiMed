import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Brain, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';

interface ReasoningViewerProps {
  reasoning: string;
  reasoningSteps?: string[];
}

export const ReasoningViewer: React.FC<ReasoningViewerProps> = ({
  reasoning,
  reasoningSteps = []
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(reasoning);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy reasoning:', error);
    }
  };

  if (!reasoning && (!reasoningSteps || reasoningSteps.length === 0)) {
    return null;
  }

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
                // Show structured reasoning steps
                <div className="space-y-3">
                  {reasoningSteps.map((step, index) => (
                    <div key={index} className="bg-white/80 p-3 rounded border-l-4 border-blue-400">
                      <div className="flex items-start gap-2">
                        <Badge variant="outline" className="text-xs mt-0.5">
                          {index + 1}
                        </Badge>
                        <div className="text-sm text-blue-900 leading-relaxed">
                          {step}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                // Show full reasoning text as fallback
                <div className="bg-white/80 p-4 rounded border-l-4 border-blue-400">
                  <div className="text-sm text-blue-900 leading-relaxed whitespace-pre-wrap">
                    {reasoning}
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