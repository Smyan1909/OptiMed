'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';

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

function useModeOptions(): ModeOption[] {
  const t = useTranslations('modeSelector.options');
  return [
    {
      id: 'post_meet',
      name: t('postMeet.name'),
      description: t('postMeet.description'),
      icon: '🔍',
      defaultPrompt: t('postMeet.defaultPrompt')
    },
    {
      id: 'pre_meet',
      name: t('preMeet.name'),
      description: t('preMeet.description'),
      icon: '📚',
      defaultPrompt: t('preMeet.defaultPrompt')
    },
    {
      id: 'research',
      name: t('research.name'),
      description: t('research.description'),
      icon: '🔬',
      defaultPrompt: t('research.defaultPrompt')
    }
  ];
}

export default function ModeSelector({ selectedMode, onModeChange, disabled = false, layout = 'horizontal' }: ModeSelectorProps) {
  const t = useTranslations('modeSelector');
  const MODE_OPTIONS = useModeOptions();
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-medium text-gray-600 text-center">{t('header')}</div>
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

export { };
export type { ModeOption };
