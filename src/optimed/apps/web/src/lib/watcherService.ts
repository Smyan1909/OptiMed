/**
 * CLARA File Watcher Integration Service
 *
 * This service handles communication with the local CLARA file watcher agent
 * running on localhost:9999. All methods fail gracefully if the watcher is
 * not running (which is expected for users who don't have it installed).
 */

import { logInfo, logWarning } from './logger';

const WATCHER_BASE_URL = 'http://localhost:9999';
const WATCHER_TIMEOUT = 2000; // 2 seconds

/**
 * Send session ID to the local watcher
 * Fails silently if watcher is not running
 */
export async function sendSessionToWatcher(sessionId: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/set-session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      logInfo('Watcher Service: Session sent to CLARA watcher');
      return true;
    } else {
      logWarning('Watcher Service: CLARA watcher responded with error');
      return false;
    }
  } catch (error) {
    // Silently fail - watcher not running is expected for most users
    if (error instanceof Error && error.name === 'AbortError') {
      logInfo('Watcher Service: CLARA watcher connection timeout (not running)');
    } else {
      logInfo('Watcher Service: CLARA watcher not available (optional feature)');
    }
    return false;
  }
}

/**
 * Clear session from the local watcher
 * Fails silently if watcher is not running
 */
export async function clearSessionFromWatcher(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/clear-session`, {
      method: 'POST',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      logInfo('Watcher Service: Session cleared from CLARA watcher');
      return true;
    } else {
      logWarning('Watcher Service: CLARA watcher clear session failed');
      return false;
    }
  } catch (error) {
    // Silently fail - watcher not running is expected
    logInfo('Watcher Service: CLARA watcher not available for session clear');
    return false;
  }
}

/**
 * Check if the local watcher is running and get its status
 * Returns null if watcher is not available
 */
export async function getWatcherStatus(): Promise<{
  status: string;
  has_session: boolean;
  session_preview?: string;
} | null> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/status`, {
      method: 'GET',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      const data = await response.json();
      logInfo('Watcher Service: CLARA watcher is running', data);
      return data;
    } else {
      return null;
    }
  } catch (error) {
    // Watcher not running
    return null;
  }
}

/**
 * Check if watcher is available (simple ping)
 */
export async function isWatcherAvailable(): Promise<boolean> {
  const status = await getWatcherStatus();
  return status !== null;
}

/**
 * Get RPA execution status from the watcher
 * Returns null if watcher is not available
 */
export async function getRPAExecutionStatus(): Promise<{
  is_executing: boolean;
  status: string;
  started_at?: string;
  last_error?: string;
} | null> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/execution-status`, {
      method: 'GET',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      const data = await response.json();
      return data;
    } else {
      return null;
    }
  } catch (error) {
    // Watcher not running
    return null;
  }
}

/**
 * Start RPA extraction workflow on the local watcher
 * Returns true if successfully started, false otherwise
 */
export async function startRPAExtraction(): Promise<{
  success: boolean;
  error?: string;
}> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/start-extraction`, {
      method: 'POST',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      logInfo('Watcher Service: RPA extraction started successfully');
      return { success: true };
    } else {
      const data = await response.json().catch(() => ({}));
      const error = data.error || 'Failed to start extraction';
      logWarning(`Watcher Service: Failed to start RPA extraction: ${error}`);
      return { success: false, error };
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { success: false, error: 'Watcher connection timeout' };
    }
    return { success: false, error: 'Watcher not available' };
  }
}

/**
 * Start doctor notes extraction workflow on the local watcher
 * Returns true if successfully started, false otherwise
 */
export async function startDoctorNotesExtraction(): Promise<{
  success: boolean;
  error?: string;
}> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/start-doctor-notes-extraction`, {
      method: 'POST',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      logInfo('Watcher Service: Doctor notes extraction started successfully');
      return { success: true };
    } else {
      const data = await response.json().catch(() => ({}));
      const error = data.error || 'Failed to start doctor notes extraction';
      logWarning(`Watcher Service: Failed to start doctor notes extraction: ${error}`);
      return { success: false, error };
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { success: false, error: 'Watcher connection timeout' };
    }
    return { success: false, error: 'Watcher not available' };
  }
}

/**
 * Stop/cancel the currently running RPA extraction
 * Returns true if successfully stopped, false otherwise
 */
export async function stopRPAExtraction(): Promise<{
  success: boolean;
  error?: string;
}> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WATCHER_TIMEOUT);

    const response = await fetch(`${WATCHER_BASE_URL}/stop-extraction`, {
      method: 'POST',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      logInfo('Watcher Service: RPA extraction stopped successfully');
      return { success: true };
    } else {
      const data = await response.json().catch(() => ({}));
      const error = data.error || 'Failed to stop extraction';
      logWarning(`Watcher Service: Failed to stop RPA extraction: ${error}`);
      return { success: false, error };
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { success: false, error: 'Watcher connection timeout' };
    }
    return { success: false, error: 'Watcher not available' };
  }
}
