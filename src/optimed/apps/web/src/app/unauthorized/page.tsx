'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Shield, ArrowLeft } from 'lucide-react';
import { useTranslations } from 'next-intl';

export default function UnauthorizedPage() {
  const t = useTranslations('unauthorized');
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <div className="flex justify-center mb-4">
            <div className="h-12 w-12 bg-red-100 rounded-full flex items-center justify-center">
              <Shield className="h-6 w-6 text-red-600" />
            </div>
          </div>
          <CardTitle className="text-xl font-bold">{t('title')}</CardTitle>
          <CardDescription>{t('description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/patients">
            <Button className="w-full">
              <ArrowLeft className="mr-2 h-4 w-4" />
              {t('backToPatients')}
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}