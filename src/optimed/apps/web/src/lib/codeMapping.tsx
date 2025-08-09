// Code mappings for display purposes
// NOTE: These are translation keys, not final display strings.
export const VITAL_CODE_MAPPINGS: Record<string, string> = {
  "8867-4": "codes.vitals.heartRate",
  "59408-5": "codes.vitals.respiratoryRate", 
  "8480-6": "codes.vitals.systolicBP",
  "8462-4": "codes.vitals.diastolicBP",
  "8310-5": "codes.vitals.temperature",
  "2708-6": "codes.vitals.oxygenSaturation",
  "9279-1": "codes.vitals.respiratoryRate",
  "8287-5": "codes.vitals.headCircumference",
  "29463-7": "codes.vitals.weight",
  "8302-2": "codes.vitals.height",
};

export const LAB_CODE_MAPPINGS: Record<string, string> = {
  "2823-3": "codes.labs.potassium",
  "2339-0": "codes.labs.glucose",
  "2951-2": "codes.labs.sodium", 
  "6298-4": "codes.labs.potassium",
  "33747-0": "codes.labs.hba1c",
  "718-7": "codes.labs.hemoglobin",
  "4544-3": "codes.labs.hematocrit",
  "6690-2": "codes.labs.wbc",
  "777-3": "codes.labs.platelets",
  "2160-0": "codes.labs.creatinine",
  "3094-0": "codes.labs.bun",
  "1751-7": "codes.labs.albumin",
  "1975-2": "codes.labs.bilirubin",
};

export function getDisplayName(code: string, type: 'vital' | 'lab' = 'vital'): string {
  const mappings = type === 'vital' ? VITAL_CODE_MAPPINGS : LAB_CODE_MAPPINGS;
  return mappings[code] || code;
}

export function formatLabValue(key: string, value: string): string {
  // Check if the value contains a number
  const match = value.match(/(\d+\.?\d*)/);
  
  if (match) {
    const numericValue = parseFloat(match[1]);
    const unit = value.replace(match[1], '').trim();
    
    if (!isNaN(numericValue)) {
      const formattedNumber = numericValue.toFixed(1).replace(/\.?0+$/, '');
      return unit ? `${formattedNumber} ${unit}` : formattedNumber;
    }
  }
  
  // Return original value if no number found
  return value;
}

export function formatVitalValue(key: string, value: string): string {
  // Check if the value contains a number
  const match = value.match(/(\d+\.?\d*)/);
  
  if (match) {
    const numericValue = parseFloat(match[1]);
    const unit = value.replace(match[1], '').trim();
    
    if (!isNaN(numericValue)) {
      const formattedNumber = numericValue.toFixed(1).replace(/\.?0+$/, '');
      return unit ? `${formattedNumber} ${unit}` : formattedNumber;
    }
  }
  
  // Return original value if no number found
  return value;
}

export function formatNumericalValue(value: string): string {
  // Check if the value contains a number
  const match = value.match(/(\d+\.?\d*)/);
  
  if (match) {
    const numericValue = parseFloat(match[1]);
    const unit = value.replace(match[1], '').trim();
    
    if (!isNaN(numericValue)) {
      const formattedNumber = numericValue.toFixed(1).replace(/\.?0+$/, '');
      return unit ? `${formattedNumber} ${unit}` : formattedNumber;
    }
  }
  
  // Return original value if no number found
  return value;
}

export function getSexKey(raw: string | undefined): string {
  const v = (raw || '').toString().toLowerCase();
  if (v.startsWith('m')) return 'common.sex.male';
  if (v.startsWith('f') || v.startsWith('kv')) return 'common.sex.female';
  if (v.includes('other')) return 'common.sex.other';
  if (v.includes('unknown')) return 'common.sex.unknown';
  return 'common.sex.unknown';
}