/**
 * Client-side E2E encryption library for OptiMed
 * Implements AES-256-GCM encryption with RSA key exchange
 */

import { sanitizeUserId, sanitizePatientId, sanitizeSessionId, sanitizeDocumentId, logInfo, logError, logWarning } from '@/lib/logger';

export interface KeyExchangeRequest {
  session_id: string;
  client_public_key?: string;
}

export interface KeyExchangeResponse {
  session_id: string;
  server_public_key: string;
  encrypted_session_key?: string;
  encrypted: boolean;
  version: string;
}

export interface EncryptedData {
  encrypted: boolean;
  data: string;
  version: string;
  timestamp?: string;
}

export class E2EEncryptionClient {
  private keyPair: CryptoKeyPair | null = null;
  private sessionKeys: Map<string, CryptoKey> = new Map();
  private serverPublicKey: CryptoKey | null = null;

  constructor() {
    this.initializeKeyPair();
  }

  /**
   * Initialize client RSA key pair for secure key exchange
   */
  private async initializeKeyPair(): Promise<void> {
    try {
      this.keyPair = await window.crypto.subtle.generateKey(
        {
          name: "RSA-OAEP",
          modulusLength: 2048,
          publicExponent: new Uint8Array([1, 0, 1]),
          hash: "SHA-256",
        },
        true, // extractable
        ["encrypt", "decrypt"]
      );
    } catch (error) {
      logError("Failed to generate client key pair", error instanceof Error ? error : new Error(String(error)));
      throw new Error("Encryption initialization failed");
    }
  }

  /**
   * Get client public key in PEM format
   */
  private async getClientPublicKeyPEM(): Promise<string> {
    if (!this.keyPair) {
      await this.initializeKeyPair();
    }

    const publicKeyBuffer = await window.crypto.subtle.exportKey("spki", this.keyPair!.publicKey);
    const publicKeyBase64 = btoa(String.fromCharCode(...new Uint8Array(publicKeyBuffer)));

    return `-----BEGIN PUBLIC KEY-----\n${publicKeyBase64.match(/.{1,64}/g)?.join('\n')}\n-----END PUBLIC KEY-----`;
  }

  /**
   * Import server's public key from PEM format
   */
  private async importServerPublicKey(pemKey: string): Promise<CryptoKey> {
    const pemContents = pemKey
      .replace(/-----BEGIN PUBLIC KEY-----/, '')
      .replace(/-----END PUBLIC KEY-----/, '')
      .replace(/\s/g, '');

    const keyBuffer = Uint8Array.from(atob(pemContents), c => c.charCodeAt(0));

    return await window.crypto.subtle.importKey(
      "spki",
      keyBuffer,
      {
        name: "RSA-OAEP",
        hash: "SHA-256",
      },
      false,
      ["encrypt"]
    );
  }

  /**
   * Setup session encryption with key exchange
   */
  async setupSessionEncryption(sessionId: string): Promise<boolean> {
    try {
      // Get client public key
      const clientPublicKeyPEM = await this.getClientPublicKeyPEM();

      // Request key exchange
      const response = await fetch('/api/encryption/key-exchange', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId,
        },
        body: JSON.stringify({
          session_id: sessionId,
          client_public_key: clientPublicKeyPEM,
        }),
      });

      if (!response.ok) {
        throw new Error(`Key exchange failed: ${response.status}`);
      }

      const keyExchangeResponse: KeyExchangeResponse = await response.json();

      // Import server public key
      this.serverPublicKey = await this.importServerPublicKey(keyExchangeResponse.server_public_key);

      // Decrypt session key if provided
      if (keyExchangeResponse.encrypted_session_key) {
        const sessionKey = await this.decryptSessionKey(keyExchangeResponse.encrypted_session_key);
        this.sessionKeys.set(sessionId, sessionKey);
      }

      logInfo(`[E2E] Session encryption setup complete for session: ${sanitizeSessionId(sessionId)}`);
      return true;
    } catch (error) {
      logError("Session encryption setup failed", error instanceof Error ? error : new Error(String(error)));
      return false;
    }
  }

  /**
   * Decrypt session key using client's private key
   */
  private async decryptSessionKey(encryptedSessionKey: string): Promise<CryptoKey> {
    if (!this.keyPair) {
      throw new Error("Client key pair not initialized");
    }

    const encryptedKeyBuffer = Uint8Array.from(atob(encryptedSessionKey), c => c.charCodeAt(0));

    const sessionKeyBuffer = await window.crypto.subtle.decrypt(
      {
        name: "RSA-OAEP",
      },
      this.keyPair.privateKey,
      encryptedKeyBuffer
    );

    // Import the decrypted session key as AES-GCM key
    return await window.crypto.subtle.importKey(
      "raw",
      sessionKeyBuffer,
      { name: "AES-GCM" },
      false,
      ["encrypt", "decrypt"]
    );
  }

  /**
   * Encrypt data using session key with AES-256-GCM
   */
  async encryptData(data: any, sessionId: string): Promise<EncryptedData> {
    const sessionKey = this.sessionKeys.get(sessionId);
    if (!sessionKey) {
      throw new Error(`No session key found for session: ${sessionId}`);
    }

    try {
      // Convert data to JSON string
      const jsonData = JSON.stringify(data);
      const dataBuffer = new TextEncoder().encode(jsonData);

      // Generate random IV (12 bytes for GCM)
      const iv = window.crypto.getRandomValues(new Uint8Array(12));

      // Encrypt data
      const encryptedBuffer = await window.crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv: iv,
        },
        sessionKey,
        dataBuffer
      );

      // Combine IV and encrypted data
      const combinedBuffer = new Uint8Array(iv.length + encryptedBuffer.byteLength);
      combinedBuffer.set(iv, 0);
      combinedBuffer.set(new Uint8Array(encryptedBuffer), iv.length);

      // Base64 encode
      const encryptedBase64 = btoa(String.fromCharCode(...combinedBuffer));

      return {
        encrypted: true,
        data: encryptedBase64,
        version: "2.0",
        timestamp: Date.now().toString(),
      };
    } catch (error) {
      logError("Data encryption failed", error instanceof Error ? error : new Error(String(error)));
      throw new Error("Failed to encrypt data");
    }
  }

  /**
   * Decrypt data using session key
   */
  async decryptData(encryptedData: EncryptedData, sessionId: string): Promise<any> {
    const sessionKey = this.sessionKeys.get(sessionId);
    if (!sessionKey) {
      throw new Error(`No session key found for session: ${sessionId}`);
    }

    try {
      // Decode base64
      const combinedBuffer = Uint8Array.from(atob(encryptedData.data), c => c.charCodeAt(0));

      // Extract IV and encrypted data
      const iv = combinedBuffer.slice(0, 12);
      const encrypted = combinedBuffer.slice(12);

      // Decrypt data
      const decryptedBuffer = await window.crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: iv,
        },
        sessionKey,
        encrypted
      );

      // Convert back to JSON
      const jsonString = new TextDecoder().decode(decryptedBuffer);
      return JSON.parse(jsonString);
    } catch (error) {
      logError("Data decryption failed", error instanceof Error ? error : new Error(String(error)));
      throw new Error("Failed to decrypt data");
    }
  }

  /**
   * Decrypt streaming chunk
   */
  async decryptStreamChunk(encryptedChunk: string, sessionId: string): Promise<string> {
    const sessionKey = this.sessionKeys.get(sessionId);
    if (!sessionKey) {
      logWarning(`No session key found for session: ${sanitizeSessionId(sessionId)}, returning raw chunk`);
      return encryptedChunk;
    }

    try {
      // Parse the SSE data
      let chunkData;
      try {
        chunkData = JSON.parse(encryptedChunk);
      } catch {
        return encryptedChunk; // Not JSON, return as-is
      }

      if (!chunkData.encrypted || !chunkData.data) {
        return encryptedChunk; // Not encrypted, return as-is
      }

      // Decrypt the data
      const decryptedData = await this.decryptData(chunkData, sessionId);
      return typeof decryptedData === 'string' ? decryptedData : JSON.stringify(decryptedData);
    } catch (error) {
      logError("Stream chunk decryption failed", error instanceof Error ? error : new Error(String(error)));
      return encryptedChunk; // Return original on error
    }
  }

  /**
   * Check if session has encryption setup
   */
  hasSessionKey(sessionId: string): boolean {
    return this.sessionKeys.has(sessionId);
  }

  /**
   * Clear session encryption key
   */
  clearSessionKey(sessionId: string): void {
    this.sessionKeys.delete(sessionId);
  }

  /**
   * Clear all session keys
   */
  clearAllSessionKeys(): void {
    this.sessionKeys.clear();
  }
}

// Global instance
let globalEncryptionClient: E2EEncryptionClient | null = null;

export function getEncryptionClient(): E2EEncryptionClient {
  if (!globalEncryptionClient) {
    globalEncryptionClient = new E2EEncryptionClient();
  }
  return globalEncryptionClient;
}

/**
 * Utility function to automatically handle encrypted API responses
 */
export async function makeEncryptedRequest(
  url: string,
  options: RequestInit,
  sessionId?: string
): Promise<Response> {
  const encryptionClient = getEncryptionClient();

  // If we have a session ID and session key, encrypt the request body
  if (sessionId && encryptionClient.hasSessionKey(sessionId) && options.body) {
    try {
      const bodyData = JSON.parse(options.body as string);
      const encryptedBody = await encryptionClient.encryptData(bodyData, sessionId);

      options.body = JSON.stringify(encryptedBody);
      options.headers = {
        ...options.headers,
        'Content-Type': 'application/json',
        'X-Encrypted': 'true',
        'X-Session-ID': sessionId,
      };
    } catch (error) {
      logWarning("Failed to encrypt request body");
    }
  }

  return fetch(url, options);
}

/**
 * Utility function to handle encrypted API responses
 */
export async function handleEncryptedResponse(
  response: Response,
  sessionId?: string
): Promise<any> {
  const encryptionClient = getEncryptionClient();

  // Check if response is encrypted
  if (response.headers.get('X-Encrypted') === 'true' && sessionId) {
    try {
      const encryptedData = await response.json();
      return await encryptionClient.decryptData(encryptedData, sessionId);
    } catch (error) {
      logError("Failed to decrypt response", error instanceof Error ? error : new Error(String(error)));
      throw new Error("Failed to decrypt server response");
    }
  }

  return response.json();
}