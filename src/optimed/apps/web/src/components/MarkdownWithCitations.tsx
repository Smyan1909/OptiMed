"use client";

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Citation, CitationModal } from './CitationModal';

interface MarkdownWithCitationsProps {
  content: string;
  citations: Record<string, Citation>;
  className?: string;
  components?: any;
}

/**
 * Renders markdown content with clickable inline citations.
 *
 * Citation format: [1], [2], [3]
 * Renders as superscript links that open CitationModal on click
 */
export const MarkdownWithCitations: React.FC<MarkdownWithCitationsProps> = ({
  content,
  citations,
  className = '',
  components = {},
}) => {
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleCitationClick = (citationId: string) => {
    const citation = citations[citationId];
    if (citation) {
      setSelectedCitation(citation);
      setIsModalOpen(true);
    }
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setSelectedCitation(null);
  };

  // Helper function to process text and replace [1], [2], etc. with clickable citations
  const processCitations = (text: string): React.ReactNode[] => {
    if (!text || typeof text !== 'string') {
      return [text];
    }

    // Pattern to match [digit] or [digits]
    const citationPattern = /\[(\d+)\]/g;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match;

    while ((match = citationPattern.exec(text)) !== null) {
      const citationId = match[1];
      const matchIndex = match.index;

      // Add text before the citation
      if (matchIndex > lastIndex) {
        parts.push(text.substring(lastIndex, matchIndex));
      }

      // Add the citation as a clickable superscript
      if (citations[citationId]) {
        const citation = citations[citationId];
        parts.push(
          <sup
            key={`cite-${citationId}-${matchIndex}`}
            className="text-blue-600 hover:text-blue-800 cursor-pointer font-medium ml-0.5 transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              handleCitationClick(citationId);
            }}
            title={`Source: ${citation.document}${citation.page ? `, Page ${citation.page}` : ''}`}
            style={{ cursor: 'pointer' }}
          >
            [{citationId}]
          </sup>
        );
      } else {
        // Keep the original if citation not found
        parts.push(match[0]);
      }

      lastIndex = matchIndex + match[0].length;
    }

    // Add remaining text after last citation
    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : [text];
  };

  // Helper to process children recursively
  const processChildren = (children: any): any => {
    if (typeof children === 'string') {
      return processCitations(children);
    } else if (Array.isArray(children)) {
      return children.map((child, idx) => {
        if (typeof child === 'string') {
          return <React.Fragment key={idx}>{processCitations(child)}</React.Fragment>;
        } else if (React.isValidElement(child)) {
          return React.cloneElement(child, {
            ...child.props,
            children: processChildren(child.props.children),
            key: idx,
          } as any);
        }
        return child;
      });
    } else if (React.isValidElement(children)) {
      return React.cloneElement(children, {
        ...children.props,
        children: processChildren(children.props.children),
      } as any);
    }
    return children;
  };

  // Custom components that process citations in text content
  const citationComponents = {
    ...components,
    p: ({ children, ...props }: any) => {
      const Component = components.p || 'p';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    li: ({ children, ...props }: any) => {
      const Component = components.li || 'li';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    td: ({ children, ...props }: any) => {
      const Component = components.td || 'td';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    h1: ({ children, ...props }: any) => {
      const Component = components.h1 || 'h1';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    h2: ({ children, ...props }: any) => {
      const Component = components.h2 || 'h2';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    h3: ({ children, ...props }: any) => {
      const Component = components.h3 || 'h3';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
    strong: ({ children, ...props }: any) => {
      const Component = components.strong || 'strong';
      const processedChildren = processChildren(children);
      return <Component {...props}>{processedChildren}</Component>;
    },
  };

  return (
    <>
      <div className={className}>
        <ReactMarkdown
          components={citationComponents}
          remarkPlugins={[remarkGfm]}
        >
          {content}
        </ReactMarkdown>
      </div>

      <CitationModal
        citation={selectedCitation}
        isOpen={isModalOpen}
        onClose={handleCloseModal}
      />
    </>
  );
};
