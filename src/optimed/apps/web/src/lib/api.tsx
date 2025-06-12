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


export async function fetchPatients(q = ""): Promise<Patient[]> {
  const url = q ? `/api/patients?q=${encodeURIComponent(q)}` : `/api/patients`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load patients");
  return res.json();
}

export async function fetchPatient(id: string): Promise<PatientDetail> {
  const res = await fetch(`/api/patients/${id}`);
  if (!res.ok) throw new Error(`Failed to load patient ${id}`);
  return res.json();
}