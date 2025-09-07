'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, User, Lock, Stethoscope, Hospital, Shield } from 'lucide-react';
import { initiateEHRLogin } from '@/lib/api';
import { useTranslations } from 'next-intl';


export default function LoginPage() {
  const t = useTranslations('login');
  // Regular login state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  // EHR login state - FIXED: Use space-separated scopes (no commas!)
  const [ehrServerUrl, setEhrServerUrl] = useState(process.env.NEXT_PUBLIC_DEFAULT_FHIR_SERVER || 'https://launch.smarthealthit.org/v/r4/fhir');
  const [ehrClientId, setEhrClientId] = useState(process.env.NEXT_PUBLIC_DEFAULT_CLIENT_ID || 'optimed');
  const [ehrScope, setEhrScope] = useState(process.env.NEXT_PUBLIC_DEFAULT_EHR_SCOPE || 'user/*.cruds');
  const [isEhrConnecting, setIsEhrConnecting] = useState(false);
  
  const [authError, setAuthError] = useState<string | null>(null);
  
  const { login, isAuthenticated, error, isLoading } = useUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  
  useEffect(() => {
    // Check for error in URL params when component mounts
    const errorParam = searchParams.get('error');
    if (errorParam) {
      setAuthError(decodeURIComponent(errorParam));
      // Clear the error from URL after showing it
      const url = new URL(window.location.href);
      url.searchParams.delete('error');
      window.history.replaceState({}, '', url.toString());
    }
  }, [searchParams]);

  useEffect(() => {
    if (isAuthenticated) {
      router.push('/patients');
    }
  }, [isAuthenticated, router]);

  const handleRegularLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;

    setIsSubmitting(true);
    setAuthError(null); // Clear any previous EHR errors
    try {
      await login(username, password);
      router.push('/patients');
    } catch (err) {
      // Error handled by context
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEhrLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ehrServerUrl || !ehrClientId) return;

    setIsEhrConnecting(true);
    setAuthError(null); // Clear any previous errors
    try {
      // Store EHR parameters in localStorage for the launch page
      localStorage.setItem('ehr_client_id', ehrClientId);
      localStorage.setItem('ehr_scope', ehrScope);
      const backendBase = (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '');
      const redirectUri = backendBase ? `${backendBase}/auth/ehr-callback` : '';
      if (redirectUri) {
        localStorage.setItem('ehr_redirect_uri', redirectUri);
      }
      
      const result = await initiateEHRLogin(
        ehrServerUrl,
        ehrClientId,
        ehrScope
      );
      
      // Store connection info and state for callback
      localStorage.setItem('ehr_login_connection_id', result.connection_id);
      localStorage.setItem('ehr_state', result.state);
      
      // Redirect to authorization server
      window.location.href = result.authorization_url;
    } catch (err: any) {
      console.error('EHR login error:', err);
      setAuthError('Failed to initiate EHR login: ' + err.message);
    } finally {
      setIsEhrConnecting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-white p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center space-y-4">
          <div className="flex justify-center">
            <div className="h-12 w-12 bg-blue-600 rounded-full flex items-center justify-center">
              <Stethoscope className="h-6 w-6 text-white" />
            </div>
          </div>
          <div>
            <CardTitle className="text-2xl font-bold text-gray-900">{t('title')}</CardTitle>
            <CardDescription className="text-gray-600">{t('subtitle')}</CardDescription>
          </div>
          
          {/* Display EHR authentication errors */}
          {authError && (
            <Alert variant="destructive" className="mt-4">
              <AlertDescription>
                {authError}
              </AlertDescription>
            </Alert>
          )}
        </CardHeader>
        
        <CardContent>
          <Tabs defaultValue="regular" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="regular" className="flex items-center gap-2">
                <Shield className="h-4 w-4" />
                {t('tabs.regular')}
              </TabsTrigger>
              <TabsTrigger value="ehr" className="flex items-center gap-2">
                <Hospital className="h-4 w-4" />
                {t('tabs.ehr')}
              </TabsTrigger>
            </TabsList>
            
            <TabsContent value="regular" className="space-y-4 mt-6">
              <div className="text-center mb-4">
                <h3 className="text-lg font-semibold text-gray-900">{t('regular.title')}</h3>
                <p className="text-sm text-gray-600">{t('regular.subtitle')}</p>
              </div>
              
              <form onSubmit={handleRegularLogin} className="space-y-4">
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                
                <div className="space-y-2">
                  <Label htmlFor="username">{t('regular.username')}</Label>
                  <div className="relative">
                    <User className="absolute left-3 top-3 h-4 w-4 text-blue-400" />
                    <Input
                      id="username"
                      type="text"
                      placeholder={t('regular.usernamePlaceholder')}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="pl-10"
                      required
                    />
                  </div>
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="password">{t('regular.password')}</Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-3 h-4 w-4 text-blue-400" />
                    <Input
                      id="password"
                      type="password"
                      placeholder={t('regular.passwordPlaceholder')}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="pl-10"
                      required
                    />
                  </div>
                </div>
                
                <Button 
                  type="submit" 
                  className="w-full" 
                  disabled={!username || !password || isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t('regular.signingIn')}
                    </>
                  ) : (
                    t('regular.signIn')
                  )}
                </Button>
              </form>
              
              <div className="mt-6 p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-600 font-medium mb-2">{t('regular.demo.title')}</p>
                <div className="space-y-1 text-xs text-gray-500">
                  <div>👨‍⚕️ {t('regular.demo.doctor')}: <code>dr.smith</code></div>
                  <div>👩‍⚕️ {t('regular.demo.nurse')}: <code>nurse.johnson</code></div>
                  <div>🔧 {t('regular.demo.admin')}: <code>admin</code></div>
                </div>
              </div>
            </TabsContent>
            
            <TabsContent value="ehr" className="space-y-4 mt-6">
              <div className="text-center mb-4">
                <h3 className="text-lg font-semibold text-gray-900">{t('ehr.title')}</h3>
                <p className="text-sm text-gray-600">{t('ehr.subtitle')}</p>
              </div>
              
              <form onSubmit={handleEhrLogin} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="ehrServerUrl">{t('ehr.fhirUrl')}</Label>
                  <div className="relative">
                    <Hospital className="absolute left-3 top-3 h-4 w-4 text-blue-400" />
                    <Input
                      id="ehrServerUrl"
                      type="url"
                      placeholder={t('ehr.fhirPlaceholder')}
                      value={ehrServerUrl}
                      onChange={(e) => setEhrServerUrl(e.target.value)}
                      className="pl-10"
                      required
                    />
                  </div>
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="ehrClientId">{t('ehr.clientId')}</Label>
                  <Input
                    id="ehrClientId"
                    type="text"
                    placeholder=""
                    value={ehrClientId}
                    onChange={(e) => setEhrClientId(e.target.value)}
                    required
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="ehrScope">{t('ehr.scope')}</Label>
                  <Input
                    id="ehrScope"
                    type="text"
                    placeholder=""
                    value={ehrScope}
                    onChange={(e) => setEhrScope(e.target.value)}
                    required
                  />
                </div>
                
                <Button 
                  type="submit" 
                  className="w-full bg-green-600 hover:bg-green-700" 
                  disabled={!ehrServerUrl || !ehrClientId || isEhrConnecting}
                >
                  {isEhrConnecting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t('ehr.connecting')}
                    </>
                  ) : (
                    <>
                      <Hospital className="mr-2 h-4 w-4" />
                      {t('ehr.connect')}
                    </>
                  )}
                </Button>
              </form>
              
              <div className="mt-4 p-4 bg-green-50 rounded-lg">
                <p className="text-sm text-green-700 font-medium mb-2">{t('ehr.secure')}</p>
                <div className="space-y-1 text-xs text-green-600">
                  {t.raw('ehr.secureBullets').map((line: string, idx: number) => (
                    <div key={idx}>• {line}</div>
                  ))}
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}