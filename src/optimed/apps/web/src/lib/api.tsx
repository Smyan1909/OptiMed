export type Patient = { id: string; name: string; dob?: string; age?: number };
export type PatientDetail = {
  id: string
  name: string
  age: number
  sex: string
  care_unit: string
  vitals: Record<string,string>
  labs:   Record<string,string>
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
  user_id?: string;
  session_id?: string;
};

export type LoginRequest = {
  username: string;
  password: string;
};

export type LoginResponse = {
  user: User;
  session_id: string;
  message: string;
};

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