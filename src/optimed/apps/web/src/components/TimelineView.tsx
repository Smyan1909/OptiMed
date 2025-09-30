import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card, CardContent } from '@/components/ui/card';
import { Calendar, Clock, Activity, TrendingUp, AlertCircle, FileText } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useLookup } from '@/hooks/useLookup';
import { LookupPanel } from '@/components/LookupPanel';

// Function to format numbers to 2 decimal places in text
const formatNumbersInText = (text: string): string => {
  return text.replace(/\b\d+\.\d{3,}\b/g, (match) => {
    const num = parseFloat(match);
    return num.toFixed(2);
  });
};

interface TimelineEvent {
  timestamp: string;
  title: string;
  content: string;
  icon: string;
  color: string;
}

interface TimelineViewProps {
  events: TimelineEvent[];
  isLoading?: boolean;
  patientId?: string;
  sessionId?: string | null;
}

// Custom markdown components for Timeline
const TimelineMarkdownComponents = {
  // Style headings
  h1: ({ children }: any) => <h1 className="text-sm font-bold text-gray-900 mt-2 mb-1">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-sm font-semibold text-gray-900 mt-2 mb-1">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-xs font-medium text-gray-900 mt-1 mb-1">{children}</h3>,

  // Style paragraphs
  p: ({ children }: any) => <p className="text-sm text-gray-700 leading-snug mb-1.5">{children}</p>,

  // Style lists
  ul: ({ children }: any) => <ul className="list-disc list-outside ml-3 space-y-2 mb-3">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-outside ml-3 space-y-2 mb-3">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 leading-relaxed py-1">{children}</li>,

  // Style code blocks
  code: ({ inline, children }: any) => {
    if (inline) {
      return <code className="bg-gray-100 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
    }
    return (
      <pre className="bg-gray-100 text-gray-800 p-2 rounded text-xs font-mono overflow-x-auto mb-1">
        <code>{children}</code>
      </pre>
    );
  },

  // Style blockquotes
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-2 border-gray-300 pl-2 italic text-gray-700 mb-1">
      {children}
    </blockquote>
  ),

  // Style strong/bold text
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,

  // Style emphasis/italic text
  em: ({ children }: any) => <em className="italic text-gray-700">{children}</em>,

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
    <div className="overflow-x-auto mb-1">
      <table className="min-w-full border-collapse border border-gray-200">{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-xs font-semibold text-gray-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-gray-200 px-2 py-1 text-xs text-gray-600">{children}</td>
  ),
};

// Component for Timeline event content with lookup functionality
const TimelineEventContent: React.FC<{
  content: string;
  lookup: any;
  isLoading: boolean;
  patientId?: string;
  sessionId?: string | null;
}> = ({ content, lookup, isLoading, patientId, sessionId }) => {
  return (
    <div
      ref={lookup.contentRef}
      className="text-sm leading-relaxed flex-grow overflow-hidden select-text"
      onTouchEnd={lookup.handleTouchEnd}
      onMouseUp={lookup.handleMouseUp}
      onKeyUp={lookup.handleKeyUp}
    >
      <ReactMarkdown
        components={TimelineMarkdownComponents}
        remarkPlugins={[remarkGfm]}
      >
        {formatNumbersInText(content)}
      </ReactMarkdown>
      <lookup.LookupButton />
      {lookup.showLookup && lookup.lookupTerm && (
        <LookupPanel
          term={lookup.lookupTerm}
          onClose={lookup.closeLookup}
          patientId={patientId}
          sessionId={sessionId}
        />
      )}
    </div>
  );
};

// Icon mapping for timeline events
const getTimelineIcon = (iconName: string) => {
  const icons: { [key: string]: any } = {
    'calendar': Calendar,
    'clock': Clock,
    'activity': Activity,
    'trending-up': TrendingUp,
    'alert-circle': AlertCircle,
    'file-text': FileText,
  };
  return icons[iconName] || Calendar;
};

// Color configuration for timeline events
const getColorConfig = (color: string) => {
  const configs: { [key: string]: { bg: string; border: string; icon: string; badge: string; line: string } } = {
    blue: {
      bg: 'bg-blue-50',
      border: 'border-blue-200',
      icon: 'text-blue-600',
      badge: 'bg-blue-100 text-blue-800',
      line: 'bg-blue-300'
    },
    green: {
      bg: 'bg-green-50',
      border: 'border-green-200',
      icon: 'text-green-600',
      badge: 'bg-green-100 text-green-800',
      line: 'bg-green-300'
    },
    orange: {
      bg: 'bg-orange-50',
      border: 'border-orange-200',
      icon: 'text-orange-600',
      badge: 'bg-orange-100 text-orange-800',
      line: 'bg-orange-300'
    },
    red: {
      bg: 'bg-red-50',
      border: 'border-red-200',
      icon: 'text-red-600',
      badge: 'bg-red-100 text-red-800',
      line: 'bg-red-300'
    },
    purple: {
      bg: 'bg-purple-50',
      border: 'border-purple-200',
      icon: 'text-purple-600',
      badge: 'bg-purple-100 text-purple-800',
      line: 'bg-purple-300'
    },
  };
  return configs[color] || configs.blue;
};

export const TimelineView: React.FC<TimelineViewProps> = ({
  events,
  isLoading = false,
  patientId,
  sessionId
}) => {
  const t = useTranslations('timeline');

  // Create separate lookup hooks for each event
  const lookupHooks = events.map(() => useLookup({ patientId, sessionId }));

  if (!events || events.length === 0) {
    return null;
  }

  return (
    <div className="mt-6 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <Clock className="h-6 w-6 text-blue-600" />
        <h3 className="text-xl font-semibold text-gray-900">Medical Timeline</h3>
      </div>

      {/* Timeline container */}
      <div className="relative">
        {/* Vertical line connecting events */}
        <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-300" />

        {/* Timeline events */}
        <div className="space-y-6">
          {events.map((event, idx) => {
            const Icon = getTimelineIcon(event.icon);
            const colorConfig = getColorConfig(event.color);
            const hasContent = event.content && event.content.trim() !== '';
            const lookup = lookupHooks[idx];

            return (
              <div key={idx} className="relative pl-16 animate-fade-in" style={{ animationDelay: `${idx * 100}ms` }}>
                {/* Icon circle */}
                <div className={`absolute left-3 w-8 h-8 rounded-full ${colorConfig.bg} ${colorConfig.border} border-2 flex items-center justify-center z-10 shadow-sm`}>
                  <Icon className={`h-4 w-4 ${colorConfig.icon}`} />
                </div>

                {/* Event card */}
                <Card className={`${colorConfig.border} border-2 hover:shadow-lg transition-all duration-200 ${colorConfig.bg}`}>
                  <CardContent className="p-4">
                    {/* Event header */}
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <h4 className="font-bold text-gray-900 text-base">{event.title}</h4>
                      </div>
                      <span className={`text-xs font-semibold px-2 py-1 rounded ${colorConfig.badge} whitespace-nowrap ml-2`}>
                        {event.timestamp}
                      </span>
                    </div>

                    {/* Event content */}
                    {isLoading && !hasContent ? (
                      <div className="flex items-center justify-center py-4">
                        <div className="animate-pulse text-sm text-gray-500">
                          Loading event details...
                        </div>
                      </div>
                    ) : hasContent ? (
                      <TimelineEventContent
                        content={event.content}
                        lookup={lookup}
                        isLoading={isLoading}
                        patientId={patientId}
                        sessionId={sessionId}
                      />
                    ) : (
                      <div className="text-sm text-gray-400 italic py-2">
                        No details available for this event
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            );
          })}
        </div>
      </div>

      {/* Info notice */}
      <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-sm text-blue-700 flex items-start leading-relaxed">
          <Clock className="h-4 w-4 inline mr-3 flex-shrink-0 mt-0.5" />
          <span>
            <strong>Timeline View</strong> displays key medical events in chronological order with relevant clinical information from patient records.
          </span>
        </p>
      </div>

      {/* Add fade-in animation */}
      <style jsx>{`
        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateX(-10px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }
        .animate-fade-in {
          animation: fade-in 0.5s ease-out forwards;
          opacity: 0;
        }
      `}</style>
    </div>
  );
};