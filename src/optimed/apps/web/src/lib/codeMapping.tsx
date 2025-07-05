// Code mappings for display purposes
export const VITAL_CODE_MAPPINGS: Record<string, string> = {
  "8867-4": "Heart Rate",
  "59408-5": "Respiratory Rate", 
  "8480-6": "Systolic Blood Pressure",
  "8462-4": "Diastolic Blood Pressure",
  "8310-5": "Body Temperature",
  "2708-6": "Oxygen Saturation",
  "9279-1": "Respiratory Rate",
  "8287-5": "Head Circumference",
  "29463-7": "Body Weight",
  "8302-2": "Body Height",
};

export const LAB_CODE_MAPPINGS: Record<string, string> = {
  "2823-3": "Potassium",
  "2339-0": "Glucose",
  "2951-2": "Sodium", 
  "6298-4": "Potassium",
  "33747-0": "Hemoglobin A1c",
  "718-7": "Hemoglobin",
  "4544-3": "Hematocrit",
  "6690-2": "White Blood Cells",
  "777-3": "Platelets",
  "2160-0": "Creatinine",
  "3094-0": "Blood Urea Nitrogen",
  "1751-7": "Albumin",
  "1975-2": "Bilirubin",
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
      const formattedNumber = numericValue.toFixed(2).replace(/\.?0+$/, '');
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
      const formattedNumber = numericValue.toFixed(2).replace(/\.?0+$/, '');
      return unit ? `${formattedNumber} ${unit}` : formattedNumber;
    }
  }
  
  // Return original value if no number found
  return value;
}