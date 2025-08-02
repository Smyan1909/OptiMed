'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface ModeOption {
  id: string;
  name: string;
  description: string;
  icon: string;
  defaultPrompt: string;
}

interface ModeSelectorProps {
  selectedMode: string;
  onModeChange: (mode: string, defaultPrompt: string) => void;
  disabled?: boolean;
  layout?: 'horizontal' | 'vertical';
}

const MODE_OPTIONS: ModeOption[] = [
  {
    id: 'post_meet',
    name: 'Post-Encounter',
    description: 'Analyze clinical findings and create care plans',
    icon: '🔍',
    defaultPrompt: 'Following a patient encounter, I need to analyze the clinical data and findings. Please help me review the patient information, examination findings, and any relevant background data to support clinical decision-making and documentation.'
  },
  {
    id: 'pre_meet',
    name: 'Pre-Encounter',
    description: 'Prepare for upcoming patient visit',
    icon: '📚',
    defaultPrompt: 'I\'m preparing for an upcoming patient encounter. Please help me review the patient\'s background information, including their medical history, current conditions, medications, and any recent test results or clinical notes that would be relevant for the encounter.'
  },
  {
    id: 'research',
    name: 'Research',
    description: 'Deep analysis and literature review',
    icon: '🔬',
    defaultPrompt: 'I need to research clinical information related to this patient\'s case. Please help me gather relevant medical literature, treatment guidelines, and evidence-based information that could inform clinical decisions.'
  }
];

export default function ModeSelector({ selectedMode, onModeChange, disabled = false, layout = 'horizontal' }: ModeSelectorProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-medium text-gray-600 text-center">Mode</div>
      <div className="flex flex-col gap-1">
        {MODE_OPTIONS.map((mode) => (
          <button
            key={mode.id}
            onClick={() => onModeChange(mode.id, mode.defaultPrompt)}
            disabled={disabled}
            title={`${mode.name}: ${mode.description}`}
            className={cn(
              "px-2 py-2 rounded text-xs font-medium transition-all duration-200",
              "flex flex-col items-center gap-1 min-w-[80px]",
              selectedMode === mode.id
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          >
            <span className="text-sm">{mode.icon}</span>
            <span className="text-xs leading-tight text-center">{mode.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export { MODE_OPTIONS };
export type { ModeOption };
