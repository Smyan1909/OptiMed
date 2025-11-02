'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Activity,
  PlayCircle,
  StopCircle,
  Circle,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';
import {
  getWatcherStatus,
  getRPAExecutionStatus,
  startRPAExtraction,
  stopRPAExtraction,
} from '@/lib/watcherService';
import { logInfo, logError } from '@/lib/logger';

interface WatcherStatus {
  isAvailable: boolean;
  hasSession: boolean;
  isExecuting: boolean;
  executionStatus: string;
  lastError?: string;
}

export function RPAControlDropdown() {
  const [status, setStatus] = useState<WatcherStatus>({
    isAvailable: false,
    hasSession: false,
    isExecuting: false,
    executionStatus: 'idle',
  });
  const [isOpen, setIsOpen] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);

  // Poll watcher status when dropdown is open
  useEffect(() => {
    if (!isOpen) return;

    const checkStatus = async () => {
      try {
        const [watcherStatus, executionStatus] = await Promise.all([
          getWatcherStatus(),
          getRPAExecutionStatus(),
        ]);

        setStatus({
          isAvailable: watcherStatus !== null,
          hasSession: watcherStatus?.has_session || false,
          isExecuting: executionStatus?.is_executing || false,
          executionStatus: executionStatus?.status || 'idle',
          lastError: executionStatus?.last_error,
        });
      } catch (error) {
        logError('RPA Control: Failed to check status', error);
      }
    };

    checkStatus();
    const interval = setInterval(checkStatus, 3000); // Poll every 3 seconds
    return () => clearInterval(interval);
  }, [isOpen]);

  // Also poll when executing (even if dropdown is closed)
  useEffect(() => {
    if (!status.isExecuting) return;

    const checkExecutionStatus = async () => {
      try {
        const executionStatus = await getRPAExecutionStatus();
        if (executionStatus) {
          setStatus((prev) => ({
            ...prev,
            isExecuting: executionStatus.is_executing,
            executionStatus: executionStatus.status,
            lastError: executionStatus.last_error,
          }));
        }
      } catch (error) {
        logError('RPA Control: Failed to check execution status', error);
      }
    };

    const interval = setInterval(checkExecutionStatus, 2000); // Poll faster during execution
    return () => clearInterval(interval);
  }, [status.isExecuting]);

  const getStatusColor = () => {
    if (!status.isAvailable) return 'text-gray-400';
    if (status.isExecuting) return 'text-yellow-500';
    if (status.executionStatus === 'completed') return 'text-green-500';
    if (status.executionStatus === 'failed' || status.executionStatus === 'cancelled')
      return 'text-red-500';
    if (status.hasSession) return 'text-green-500';
    return 'text-orange-500';
  };

  const getStatusText = () => {
    if (!status.isAvailable) return 'Offline';
    if (status.isExecuting) return 'Running';
    if (status.executionStatus === 'completed') return 'Completed';
    if (status.executionStatus === 'failed') return 'Failed';
    if (status.executionStatus === 'cancelled') return 'Cancelled';
    if (status.hasSession) return 'Ready';
    return 'No Session';
  };

  const getStatusBadgeVariant = () => {
    if (!status.isAvailable) return 'secondary';
    if (status.isExecuting) return 'warning';
    if (status.executionStatus === 'completed') return 'success';
    if (status.executionStatus === 'failed' || status.executionStatus === 'cancelled')
      return 'destructive';
    if (status.hasSession) return 'success';
    return 'outline';
  };

  const handleStartExtraction = async () => {
    setIsStarting(true);
    try {
      logInfo('RPA Control: Starting extraction...');
      const result = await startRPAExtraction();

      if (result.success) {
        logInfo('RPA Control: Extraction started successfully');
        // Update status immediately
        setStatus((prev) => ({
          ...prev,
          isExecuting: true,
          executionStatus: 'running',
          lastError: undefined,
        }));
      } else {
        logError('RPA Control: Failed to start extraction', result.error);
        setStatus((prev) => ({
          ...prev,
          lastError: result.error,
        }));
      }
    } catch (error) {
      logError('RPA Control: Error starting extraction', error);
    } finally {
      setIsStarting(false);
    }
  };

  const handleStopExtraction = async () => {
    setIsStopping(true);
    try {
      logInfo('RPA Control: Stopping extraction...');
      const result = await stopRPAExtraction();

      if (result.success) {
        logInfo('RPA Control: Extraction stopped successfully');
        // Update status immediately
        setStatus((prev) => ({
          ...prev,
          isExecuting: false,
          executionStatus: 'cancelled',
        }));
      } else {
        logError('RPA Control: Failed to stop extraction', result.error);
      }
    } catch (error) {
      logError('RPA Control: Error stopping extraction', error);
    } finally {
      setIsStopping(false);
    }
  };

  const canStartExtraction =
    status.isAvailable && status.hasSession && !status.isExecuting && !isStarting;
  const canStopExtraction = status.isAvailable && status.isExecuting && !isStopping;

  // Pulsing dots for running state
  const PulsingDots = () => (
    <div className="flex items-center gap-1">
      <div
        className="w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse"
        style={{ animationDelay: '0ms' }}
      />
      <div
        className="w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse"
        style={{ animationDelay: '150ms' }}
      />
      <div
        className="w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse"
        style={{ animationDelay: '300ms' }}
      />
    </div>
  );

  return (
    <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="relative h-10 px-3">
          <div className="flex items-center space-x-2">
            <Activity className="h-4 w-4" />
            <Circle className={`h-2 w-2 fill-current ${getStatusColor()}`} />
            <span className="hidden md:inline text-sm font-medium">RPA</span>
          </div>
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent className="w-80" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">CLARA Watcher</span>
              <Badge variant={getStatusBadgeVariant()}>{getStatusText()}</Badge>
            </div>

            {status.isAvailable && (
              <div className="text-xs text-muted-foreground space-y-1">
                <div className="flex items-center gap-2">
                  <Circle
                    className={`h-2 w-2 fill-current ${
                      status.hasSession ? 'text-green-500' : 'text-orange-500'
                    }`}
                  />
                  <span>Session: {status.hasSession ? 'Connected' : 'Not logged in'}</span>
                </div>
                {status.isExecuting && (
                  <div className="flex items-center gap-2">
                    <PulsingDots />
                    <span>Extraction in progress...</span>
                  </div>
                )}
                {status.executionStatus === 'completed' && (
                  <div className="flex items-center gap-2 text-green-600">
                    <CheckCircle className="h-3 w-3" />
                    <span>Last extraction completed successfully</span>
                  </div>
                )}
              </div>
            )}

            {!status.isAvailable && (
              <div className="text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Circle className="h-2 w-2 fill-current text-gray-400" />
                  <span>Watcher client not running</span>
                </div>
              </div>
            )}
          </div>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          className="cursor-pointer"
          onClick={handleStartExtraction}
          disabled={!canStartExtraction}
        >
          <PlayCircle className="mr-2 h-4 w-4" />
          <span>{isStarting ? 'Starting...' : 'Start Extraction'}</span>
        </DropdownMenuItem>

        {status.isExecuting && (
          <DropdownMenuItem
            className="cursor-pointer text-red-600"
            onClick={handleStopExtraction}
            disabled={!canStopExtraction}
          >
            <StopCircle className="mr-2 h-4 w-4" />
            <span>{isStopping ? 'Stopping...' : 'Stop Extraction'}</span>
          </DropdownMenuItem>
        )}

        {status.lastError && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-2 text-xs text-red-600">
              <AlertCircle className="inline h-3 w-3 mr-1" />
              {status.lastError}
            </div>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
