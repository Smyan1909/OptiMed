import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { useTranslations } from 'next-intl';
import { lookupTerm, LookupResponse } from '@/lib/api';

interface LookupPanelProps {
  term: string;
  onClose: () => void;
  patientId?: string;
  sessionId?: string | null;
}

export const LookupPanel: React.FC<LookupPanelProps> = ({ term, onClose, patientId, sessionId }) => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LookupResponse | null>(null);
  const t = useTranslations('chatBox');
  const tCommon = useTranslations('common');

  useEffect(() => {
    let canceled = false;
    const run = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await lookupTerm({ term, patient_id: patientId, session_id: sessionId || undefined });
        if (!canceled) setResult(data);
      } catch (e: any) {
        if (!canceled) setError(e?.message || 'Lookup failed');
      } finally {
        if (!canceled) setLoading(false);
      }
    };
    run();
    return () => { canceled = true; };
  }, [term, patientId, sessionId]);

  return (
    <div className="fixed bottom-6 right-6 z-50 w-full max-w-md shadow-2xl border border-gray-200 bg-white rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
        <div className="font-semibold text-gray-800">{t('lookup.title')}: <span className="text-blue-700">{term}</span></div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-800">✕</button>
      </div>
      <div className="p-4 max-h-96 overflow-y-auto text-sm text-gray-900">
        {loading && (<div className="text-gray-600">{tCommon('searching')}</div>)}
        {error && (<div className="text-red-600">{t('lookup.error')}</div>)}
        {!loading && !error && result && (
          <div className="space-y-3">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown
                components={{
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
                  h1: ({ children }: any) => (
                    <h1 className="text-lg font-bold text-gray-900 mb-2">{children}</h1>
                  ),
                  h2: ({ children }: any) => (
                    <h2 className="text-md font-semibold text-gray-900 mb-1">{children}</h2>
                  ),
                  h3: ({ children }: any) => (
                    <h3 className="text-sm font-medium text-gray-900 mb-1">{children}</h3>
                  ),
                  p: ({ children }: any) => (
                    <p className="text-sm text-gray-700 mb-2">{children}</p>
                  ),
                  ul: ({ children }: any) => (
                    <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>
                  ),
                  ol: ({ children }: any) => (
                    <ol className="list-decimal list-inside space-y-1 mb-2">{children}</ol>
                  ),
                  li: ({ children }: any) => (
                    <li className="text-sm text-gray-700">{children}</li>
                  ),
                  code: ({ inline, children }: any) => {
                    if (inline) {
                      return <code className="bg-gray-100 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
                    }
                    return (
                      <pre className="bg-gray-100 text-gray-800 p-2 rounded text-xs font-mono overflow-x-auto mb-2">
                        <code>{children}</code>
                      </pre>
                    );
                  },
                  blockquote: ({ children }: any) => (
                    <blockquote className="border-l-2 border-gray-300 pl-2 italic text-gray-700 mb-2">
                      {children}
                    </blockquote>
                  ),
                  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
                  em: ({ children }: any) => <em className="italic text-gray-700">{children}</em>,
                }}
              >
                {result.summary || 'No information found.'}
              </ReactMarkdown>
            </div>

            {result.sources && result.sources.length > 0 && (
              <div className="border-t border-gray-200 pt-3">
                <div className="text-xs font-semibold text-gray-600 mb-2">{t('lookup.sources')}:</div>
                <div className="space-y-1">
                  {result.sources.map((source, index) => (
                    <div key={index} className="text-xs text-gray-500">
                      • <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800 underline">
                          {source.title}
                        </a>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};