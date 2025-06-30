"use client";
import { useState, useEffect } from 'react';
import { Button } from "@/components/ui/button";
import { useRouter } from 'next/navigation';

type SMARTLauncherProps = {
  clientId: string;
  scope: string;
  fhirServerUrl: string;
  redirectUri: string;
}

export default function SMARTLauncher({ 
  clientId, 
  scope, 
  fhirServerUrl, 
  redirectUri 
}: SMARTLauncherProps) {
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  // Generate a random state parameter to prevent CSRF
  const generateState = () => {
    return Math.random().toString(36).substring(2, 15) + 
           Math.random().toString(36).substring(2, 15);
  };

  const launchSMART = () => {
    setIsLoading(true);
    
    const state = generateState();
    // Store state in localStorage to verify when we return
    localStorage.setItem('smart_auth_state', state);
    
    // Construct the authorization URL
    const authUrl = new URL(`${fhirServerUrl}/authorize`);
    authUrl.searchParams.append('response_type', 'code');
    authUrl.searchParams.append('client_id', clientId);
    authUrl.searchParams.append('redirect_uri', redirectUri);
    authUrl.searchParams.append('scope', scope);
    authUrl.searchParams.append('state', state);
    
    // Redirect to the authorization server
    window.location.href = authUrl.toString();
  };

  return (
    <Button 
      onClick={launchSMART} 
      disabled={isLoading} 
      className="bg-blue-600 hover:bg-blue-700"
    >
      {isLoading ? "Connecting..." : "Connect to EHR System"}
    </Button>
  );
}