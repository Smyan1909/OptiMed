export type Patient = { id: string; name: string; dob?: string; age?: number; sex?: string };
export type PatientDetail = {
  id: string;
  name: string;
  age: number;
  sex: string;
  care_unit: string;
  vitals: Record<string,string>;
  labs:   Record<string,string>;
  exam: Record<string,string>;
  procedure: Record<string,string>;
  imaging_observations: Record<string,string>;
  procedure_observations: Record<string,string>;
  social_history: Record<string,string>;
  medications: Record<string,string>;
  allergies: Record<string,string>;
  diagnoses: Record<string,string>;
  immunizations: Record<string,string>;
  diagnostic_reports: Record<string,string>;
  medication_statement: Record<string,string>;
  questionnaire_response: Record<string,string>;
  // Timestamp fields
  vitals_timestamps: Record<string,string>;
  labs_timestamps: Record<string,string>;
  exam_timestamps: Record<string,string>;
  procedure_timestamps: Record<string,string>;
  imaging_observations_timestamps: Record<string,string>;
  procedure_observations_timestamps: Record<string,string>;
  social_history_timestamps: Record<string,string>;
  medications_timestamps: Record<string,string>;
  allergies_timestamps: Record<string,string>;
  diagnoses_timestamps: Record<string,string>;
  immunizations_timestamps: Record<string,string>;
  diagnostic_reports_timestamps: Record<string,string>;
  medication_statement_timestamps: Record<string,string>;
  questionnaire_response_timestamps: Record<string,string>;
  // Encounters
  encounters: Record<string,string>;
  encounters_timestamps: Record<string,string>;
}

export type User = {
  user_id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  status: string;
  department?: string;
  license_number?: string;
  phone?: string;
  full_name: string;
  display_name: string;
};

export type ChatRequest = {
  patient_id?: string;
  user_prompt?: string;
  chat_mode?: boolean;
  diagnostic_mode?: string;
  user_id?: string;
  session_id?: string;
};

export interface JournalEntry {
  entry_id: string;
  patient_id: string;
  title: string;
  content: string;
  entry_type: JournalEntryType;
  created_by: string;
  created_at: string;
  updated_at: string;
  author_name: string;
  author_role: string;
}

export enum JournalEntryType {
  NOTE = "note",
  OBSERVATION = "observation",
  TREATMENT = "treatment",
  DIAGNOSIS = "diagnosis",
  ASSESSMENT = "assessment",
  PLAN = "plan"
}

export interface JournalEntryCreate {
  patient_id: string;
  title: string;
  content: string;
  entry_type: JournalEntryType;
}

export type LoginRequest = {
  username: string;
  password: string;
};

export type LoginResponse = {
  user: User;
  session_id: string;
  message: string;
};

export type Session = {
  session_id: string;
  patient_id: string | null;
  created_by_user_id: string;
  participants: string[];
  created_at: string;
  last_message_at: string;
  session_title: string;
  message_count: number;
  mode: string;
  is_active: boolean;
  last_participant_id: string | null;
  user_can_join: boolean;
};

export type SessionListRequest = {
  patient_id?: string | null;
  user_id?: string | null;
  include_all_patient_sessions?: boolean;
};

export type SessionCreateRequest = {
  patient_id?: string | null;
  mode?: string;
  session_title?: string | null;
};

export interface AutocompleteRequest {
  text: string;
  entry_type: string;
  cursor_position: number;
  max_tokens?: number;
}

export interface AutocompleteResponse {
  completion: string;
  cursor_position: number;
}

export interface JournalGenerationRequest {
  prompt: string;
  entry_type: string;
  patient_id?: string;
  language?: string;
}

export interface JournalGenerationResponse {
  title: string;
  content: string;
  entry_type: string;
  generated_at: string;
  prompt: string;
}


interface DICOMImage {
  image_id: string;
  patient_id?: string;
  user_id: string;
  filename: string;
  file_size: number;
  metadata: Record<string, string>;
  dimensions: {
    width: number;
    height: number;
    depth?: number;
    pixel_spacing_x?: number;
    pixel_spacing_y?: number;
    slice_thickness?: number;
  };
  default_window_level: {
    center: number;
    width: number;
  };
  status: string;
  uploaded_at: string;
  processed_at?: string;
  storage_path?: string;
}

interface DICOMPixelData {
  image_id: string;
  image_data_base64: string;
  original_dtype: string;
  photometric_interpretation?: string;
  statistics: Record<string, any>;
}

export interface GeneratedImageInfo {
  image_generated: boolean;
  image_id?: string;
  image_prompt?: string;
  generation_metadata?: Record<string, any>;
  model_info?: Record<string, any>;
}

export interface ImageGenerationRequest {
  prompt: string;
  width?: number;
  height?: number;
  patient_id?: string;
}

export interface GeneratedImageResponse {
  success: boolean;
  image_id: string;
  prompt: string;
  created_at: string;
  metadata: Record<string, any>;
  model_info: Record<string, any>;
}

export interface LookupRequest {
  term: string;
  term_type?: 'medication' | 'diagnosis' | 'vital' | 'lab' | 'general' | string;
  patient_id?: string;
  session_id?: string;
}

export interface LookupResponse {
  term: string;
  summary: string;
  sources: { title: string; url: string }[];
  raw_results?: { title: string; url: string; snippet?: string; score?: number }[];
}



// Session management functions
export async function listSessions(request: SessionListRequest): Promise<Session[]> {
  const res = await fetch('/api/sessions/list', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to list sessions: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function createSession(request: SessionCreateRequest): Promise<{ session_id: string; message: string }> {
  const res = await fetch('/api/sessions/create', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to create session: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function joinSession(sessionId: string): Promise<{ message: string; session_id: string }> {
  const res = await fetch(`/api/sessions/${sessionId}/join`, {
    method: 'POST',
    headers: getSessionHeaders()
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to join session: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function initiateEHRLogin(
  fhirServerUrl: string,
  clientId: string,
  scope: string
): Promise<{ authorization_url: string; connection_id: string; state: string }> {
  const response = await fetch('/api/auth/ehr-login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      fhir_server_url: fhirServerUrl,
      client_id: clientId,
      scope: scope,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || 'Failed to initiate EHR login');
  }

  return response.json();
}
export async function completeEHRLogin(
  connectionId: string,
  code: string,
  state: string
): Promise<{ user: User; session_id: string; message: string }> {
  const res = await fetch('/api/auth/ehr-callback', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      connection_id: connectionId,
      code: code,
      state: state
    })
  });
  
  if (!res.ok) throw new Error('Failed to complete EHR login');
  return res.json();
}


export async function fetchPatients(q = ""): Promise<Patient[]> {
  const url = q ? `/api/patients?q=${encodeURIComponent(q)}` : `/api/patients`;
  const res = await fetch(url, {
    headers: getSessionHeaders()
  });
  if (!res.ok) throw new Error("Failed to load patients");
  return res.json();
}

// Update fetchPatient to use session headers:
export async function fetchPatient(id: string): Promise<PatientDetail> {
  const res = await fetch(`/api/patients/${id}`, {
    headers: getSessionHeaders()
  });
  if (!res.ok) throw new Error(`Failed to load patient ${id}`);
  return res.json();
}

function getSessionHeaders(excludeContentType = false): Record<string, string> {
  const headers: Record<string, string> = {};
  
  if (!excludeContentType) {
    headers['Content-Type'] = 'application/json';
  }
  
  if (typeof window !== 'undefined') {
    const sessionId = localStorage.getItem('session_id');
    if (sessionId) {
      headers['X-Session-ID'] = sessionId;
    }

    // Attach the current UI locale as Accept-Language for backend language handling
    try {
      const localeCookie = document.cookie
        .split('; ')
        .find(row => row.startsWith('NEXT_LOCALE='))
        ?.split('=')[1];
      if (localeCookie) {
        headers['Accept-Language'] = localeCookie;
      }
    } catch {}
  }
  
  return headers;
}

export async function clearPatientChatHistory(patientId: string): Promise<void> {
  const res = await fetch(`/api/patients/${patientId}/chat-history`, {
    method: 'DELETE',
    headers: getSessionHeaders()
  });
  
  if (!res.ok) throw new Error('Failed to clear chat history');
}

// Authentication functions
export async function getCurrentUser(): Promise<User | null> {
  try {
    const res = await fetch('/api/auth/me', {
      headers: getSessionHeaders()
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function loginUser(username: string, password: string): Promise<{ user: User; session: { session_id: string } }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) throw new Error('Login failed');
  
  const data = await res.json();
  return {
    user: data.user,
    session: { session_id: data.session_id }
  };
}

export async function logoutUser(): Promise<void> {
  await fetch('/api/auth/logout', { 
    method: 'POST',
    headers: getSessionHeaders()
  });
}

// New user-aware functions
export async function diagnoseWithUser(request: ChatRequest): Promise<any> {
  const res = await fetch('/api/diagnose', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Diagnosis failed: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function chatWithUser(request: ChatRequest): Promise<any> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Chat failed: ${res.status} - ${errorText}`);
  }
  return res.json();
}


export async function uploadDICOMImage(file: File, patientId?: string): Promise<{ image_id: string; message: string; image: DICOMImage }> {
  const formData = new FormData();
  formData.append('file', file);
  if (patientId) {
    formData.append('patient_id', patientId);
  }

  const res = await fetch('/api/dicom/upload', {
    method: 'POST',
    headers: getSessionHeaders(true), // Pass true to exclude Content-Type for FormData
    body: formData,
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Upload failed: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function listDICOMImages(): Promise<{ images: DICOMImage[] }> {
  const res = await fetch('/api/dicom/images', {
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to load images: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function getDICOMImage(imageId: string): Promise<DICOMImage> {
  const res = await fetch(`/api/dicom/images/${imageId}`, {
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to load image: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function getDICOMPixelData(
  imageId: string, 
  windowCenter?: number, 
  windowWidth?: number
): Promise<DICOMPixelData> {
  const params = new URLSearchParams();
  if (windowCenter !== undefined) params.set('window_center', windowCenter.toString());
  if (windowWidth !== undefined) params.set('window_width', windowWidth.toString());
  
  const queryString = params.toString();
  const url = `/api/dicom/images/${imageId}/pixel-data${queryString ? '?' + queryString : ''}`;

  const res = await fetch(url, {
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to load pixel data: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function deleteDICOMImage(imageId: string): Promise<{ message: string }> {
  const res = await fetch(`/api/dicom/images/${imageId}`, {
    method: 'DELETE',
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to delete image: ${res.status} - ${errorText}`);
  }
  return res.json();
}

export async function analyzeDICOMImage(imageId: string, query: string, patientId?: string) {
  const body: any = { query };
  if (patientId) {
    body.patient_id = patientId;
  }

  const res = await fetch(`/api/dicom/images/${imageId}/analyze`, {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(body)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Analysis failed: ${res.status} - ${errorText}`);
  }
  
  return res.json();
}

export async function findSimilarDICOMImages(imageId: string, limit: number = 5) {
  const res = await fetch(`/api/dicom/images/${imageId}/similar?limit=${limit}`, {
    headers: getSessionHeaders()
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Search failed: ${res.status} - ${errorText}`);
  }
  
  return res.json();
}

export async function fetchPatientJournalEntries(patientId: string): Promise<JournalEntry[]> {
  const res = await fetch(`/api/patients/${patientId}/journal`, {
    headers: getSessionHeaders()
  });
  if (!res.ok) {
    const errorText = await res.text();
    console.error('Failed to fetch journal entries:', res.status, errorText);
    throw new Error(`Failed to load journal entries: ${errorText}`);
  }
  return res.json();
}

export async function createJournalEntry(patientId: string, entry: JournalEntryCreate): Promise<JournalEntry> {
  const res = await fetch(`/api/patients/${patientId}/journal`, {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(entry)
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to create journal entry: ${errorText}`);
  }
  return res.json();
}

export async function getJournalAutocomplete(request: AutocompleteRequest): Promise<AutocompleteResponse> {
  const res = await fetch('/api/journal/autocomplete', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to get autocomplete: ${errorText}`);
  }
  
  return res.json();
}

export async function fetchJournalEntry(patientId: string, entryId: string): Promise<JournalEntry> {
  const res = await fetch(`/api/patients/${patientId}/journal/${entryId}`, {
    headers: getSessionHeaders()
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to load journal entry: ${errorText}`);
  }
  return res.json();
}

export async function generateJournalEntry(request: JournalGenerationRequest): Promise<JournalGenerationResponse> {
  const res = await fetch('/api/journal/generate', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to generate journal entry: ${errorText}`);
  }
  
  return res.json();
}

export async function generateImage(request: ImageGenerationRequest): Promise<GeneratedImageResponse> {
  const res = await fetch('/api/images/generate', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });
  
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Image generation failed: ${res.status} - ${errorText}`);
  }
  
  return res.json();
}

export async function getGeneratedImageUrl(imageId: string): Promise<string> {
  // For generated images, we can directly use the API route with session headers
  return `/api/images/generated/${imageId}`;
}

export async function downloadGeneratedImage(imageId: string, filename?: string): Promise<void> {
  try {
    // Create request with proper headers
    const response = await fetch(`/api/images/generated/${imageId}`, {
      headers: getSessionHeaders()
    });
    
    if (!response.ok) {
      throw new Error(`Failed to download image: ${response.status}`);
    }
    
    const blob = await response.blob();
    
    // Create a temporary anchor element and trigger download
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || `generated_image_${imageId}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  } catch (error) {
    console.error('Error downloading image:', error);
    throw error;
  }
}

export async function checkImageGenerationStatus(): Promise<{ enabled: boolean; available: boolean; message: string }> {
  const res = await fetch('/api/images/service/status', {
    headers: getSessionHeaders()
  });
  
  if (!res.ok) {
    return { enabled: false, available: false, message: 'Service check failed' };
  }
  
  return res.json();
}

export async function lookupTerm(request: LookupRequest): Promise<LookupResponse> {
  const res = await fetch('/api/lookup', {
    method: 'POST',
    headers: getSessionHeaders(),
    body: JSON.stringify(request)
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Lookup failed: ${res.status} - ${errorText}`);
  }

  return res.json();
}

// PDF Document Types
export type PDFDocument = {
  document_id: string;
  filename: string;
  file_size: number;
  status: 'UPLOADED' | 'PROCESSING' | 'READY' | 'ERROR';
  uploaded_at: string;
  processed_at?: string;
  patient_id?: string;
  metadata?: {
    title?: string;
    author?: string;
    subject?: string;
    page_count?: number;
  };
  processing_info?: {
    extracted_text_length: number;
    chunk_count: number;
    extraction_method: string;
  };
};

export type PDFUploadResponse = {
  document_id: string;
  filename: string;
  file_size: number;
  status: string;
  uploaded_at: string;
  patient_id?: string;
};

export type PDFListResponse = {
  documents: PDFDocument[];
  total_count: number;
  patient_specific_count: number;
  general_count: number;
};

// PDF Document API Functions
export async function uploadPDFDocument(file: File, patientId?: string): Promise<PDFUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (patientId) {
    formData.append('patient_id', patientId);
  }

  const res = await fetch('/api/documents/upload', {
    method: 'POST',
    headers: getSessionHeaders(true), // Excludes Content-Type for FormData
    body: formData,
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`PDF upload failed: ${res.status} - ${errorText}`);
  }

  return res.json();
}

export async function listPDFDocuments(patientId?: string): Promise<PDFListResponse> {
  const url = patientId
    ? `/api/documents?patient_id=${encodeURIComponent(patientId)}`
    : '/api/documents';

  const res = await fetch(url, {
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to list PDF documents: ${res.status} - ${errorText}`);
  }

  return res.json();
}

export async function getPDFDocument(documentId: string): Promise<PDFDocument> {
  const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}`, {
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to get PDF document: ${res.status} - ${errorText}`);
  }

  return res.json();
}

export async function deletePDFDocument(documentId: string): Promise<void> {
  const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
    headers: getSessionHeaders(),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to delete PDF document: ${res.status} - ${errorText}`);
  }
}