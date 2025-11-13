'use client';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { HelpCircle, Mail, Phone } from 'lucide-react';
import { useTranslations } from 'next-intl';

export function HelpContactDropdown() {
  const t = useTranslations();

  const handleEmailClick = () => {
    window.location.href = `mailto:${t('help.email.value')}`;
  };

  const handlePhoneClick = () => {
    window.location.href = `tel:${t('help.phone.value').replace(/\s/g, '')}`;
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-10 w-10 p-0 rounded-full hover:bg-gray-100">
          <HelpCircle className="h-5 w-5 text-gray-600" />
          <span className="sr-only">{t('help.title')}</span>
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent className="w-72" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <span className="text-sm font-semibold text-gray-900">{t('help.title')}</span>
            <span className="text-xs text-gray-500">{t('help.subtitle')}</span>
          </div>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          className="cursor-pointer flex items-center gap-3 py-3"
          onClick={handleEmailClick}
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-50">
            <Mail className="h-4 w-4 text-blue-600" />
          </div>
          <div className="flex flex-col">
            <span className="text-xs text-gray-500">{t('help.email.label')}</span>
            <span className="text-sm font-medium text-gray-900">{t('help.email.value')}</span>
          </div>
        </DropdownMenuItem>

        <DropdownMenuItem
          className="cursor-pointer flex items-center gap-3 py-3"
          onClick={handlePhoneClick}
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-green-50">
            <Phone className="h-4 w-4 text-green-600" />
          </div>
          <div className="flex flex-col">
            <span className="text-xs text-gray-500">{t('help.phone.label')}</span>
            <span className="text-sm font-medium text-gray-900">{t('help.phone.value')}</span>
          </div>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
