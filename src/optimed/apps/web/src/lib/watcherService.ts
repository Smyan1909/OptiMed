/**
 * CLARA File Watcher Integration Service
 *
 * This service handles communication with the local CLARA file watcher agent
 * running on localhost:9999. All methods fail gracefully if the watcher is
 * not running (which is expected for users who don't have it installed).
 */

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
      console.log('✅ Session sent to CLARA watcher');
      return true;
    } else {
      console.log('⚠️ CLARA watcher responded with error');
      return false;
    }
  } catch (error) {
    // Silently fail - watcher not running is expected for most users
    if (error instanceof Error && error.name === 'AbortError') {
      console.log('⏱️ CLARA watcher connection timeout (not running)');
    } else {
      console.log('ℹ️ CLARA watcher not available (optional feature)');
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
      console.log('✅ Session cleared from CLARA watcher');
      return true;
    } else {
      console.log('⚠️ CLARA watcher clear session failed');
      return false;
    }
  } catch (error) {
    // Silently fail - watcher not running is expected
    console.log('ℹ️ CLARA watcher not available for session clear');
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
      console.log('✅ CLARA watcher is running:', data);
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
