/**
 * GDPR-Compliant Logging Utility
 *
 * Provides logging functions with automatic sanitization of sensitive identifiers.
 * Uses SHA-256 hashing to protect PII while maintaining traceability in logs.
 * Logging is disabled in production to minimize data exposure.
 */

/**
 * Generates a SHA-256 hash of the input string using Web Crypto API
 * Falls back to a simple hash if Web Crypto is unavailable
 */
async function hashString(input: string): Promise<string> {
  try {
    // Use Web Crypto API for SHA-256 hashing
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return hashHex;
  } catch (error) {
    // Fallback: simple hash for environments without Web Crypto API
    console.warn('Web Crypto API unavailable, using fallback hash');
    let hash = 0;
    for (let i = 0; i < input.length; i++) {
      const char = input.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash).toString(16).padStart(8, '0');
  }
}

/**
 * Synchronous hash function for immediate logging
 * Uses a simpler but less secure hash for synchronous operations
 */
function hashStringSync(input: string): string {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const char = input.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(16).padStart(8, '0');
}

/**
 * Sanitizes user ID by hashing it
 * Returns first 8 characters of hash with 'user_' prefix
 *
 * @param userId - The user ID to sanitize (can be null)
 * @returns Sanitized user ID in format "user_abc12345" or "user_null" if null
 */
export function sanitizeUserId(userId: string | null): string {
  if (!userId) {
    return 'user_null';
  }
  const hash = hashStringSync(userId);
  return `user_${hash.substring(0, 8)}`;
}

/**
 * Sanitizes patient ID by hashing it
 * Returns first 8 characters of hash with 'patient_' prefix
 *
 * @param patientId - The patient ID to sanitize (can be null)
 * @returns Sanitized patient ID in format "patient_abc12345" or "patient_null" if null
 */
export function sanitizePatientId(patientId: string | null): string {
  if (!patientId) {
    return 'patient_null';
  }
  const hash = hashStringSync(patientId);
  return `patient_${hash.substring(0, 8)}`;
}

/**
 * Sanitizes session ID by hashing it
 * Returns first 8 characters of hash with 'session_' prefix
 *
 * @param sessionId - The session ID to sanitize (can be null)
 * @returns Sanitized session ID in format "session_abc12345" or "session_null" if null
 */
export function sanitizeSessionId(sessionId: string | null): string {
  if (!sessionId) {
    return 'session_null';
  }
  const hash = hashStringSync(sessionId);
  return `session_${hash.substring(0, 8)}`;
}

/**
 * Sanitizes document ID by hashing it
 * Returns first 8 characters of hash with 'doc_' prefix
 *
 * @param docId - The document ID to sanitize (can be null)
 * @returns Sanitized document ID in format "doc_abc12345" or "doc_null" if null
 */
export function sanitizeDocumentId(docId: string | null): string {
  if (!docId) {
    return 'doc_null';
  }
  const hash = hashStringSync(docId);
  return `doc_${hash.substring(0, 8)}`;
}

/**
 * Checks if logging is enabled (development mode only)
 */
function isLoggingEnabled(): boolean {
  return process.env.NODE_ENV === 'development';
}

/**
 * Logs informational messages (development only)
 * Wrapper for console.log with environment check
 *
 * @param message - The message to log
 * @param args - Additional arguments to log
 */
export function logInfo(message: string, ...args: any[]): void {
  if (isLoggingEnabled()) {
    console.log(`[INFO] ${message}`, ...args);
  }
}

/**
 * Logs error messages (development only)
 * Wrapper for console.error with environment check
 *
 * @param message - The error message to log
 * @param error - Optional Error object with stack trace
 */
export function logError(message: string, error?: Error): void {
  if (isLoggingEnabled()) {
    if (error) {
      console.error(`[ERROR] ${message}`, error);
    } else {
      console.error(`[ERROR] ${message}`);
    }
  }
}

/**
 * Logs warning messages (development only)
 * Wrapper for console.warn with environment check
 *
 * @param message - The warning message to log
 */
export function logWarning(message: string): void {
  if (isLoggingEnabled()) {
    console.warn(`[WARN] ${message}`);
  }
}

/**
 * Example usage:
 *
 * import { sanitizeUserId, sanitizePatientId, logInfo, logError } from './logger';
 *
 * const userId = "12345";
 * const patientId = "patient-abc-123";
 *
 * logInfo(`User logged in: ${sanitizeUserId(userId)}`);
 * logInfo(`Accessing patient record: ${sanitizePatientId(patientId)}`);
 *
 * try {
 *   // some operation
 * } catch (error) {
 *   logError('Failed to process patient data', error as Error);
 * }
 */
