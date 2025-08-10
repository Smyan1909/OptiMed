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
  // Additional commonly encountered labs
  "2093-3": "codes.labs.cholesterol",
  "13457-7": "codes.labs.ldl",
  "2085-9": "codes.labs.hdl",
  "2571-8": "codes.labs.triglycerides",
  "17861-6": "codes.labs.calcium",
  "2075-0": "codes.labs.chloride",
  "2028-9": "codes.labs.co2",
  "10466-1": "codes.labs.anionGap",
  "19123-9": "codes.labs.magnesium",
  "2777-1": "codes.labs.phosphorus",
  "1742-6": "codes.labs.alt",
  "1920-8": "codes.labs.ast",
  "6768-6": "codes.labs.alp",
  "2324-2": "codes.labs.ggt",
  "1988-5": "codes.labs.crp",
  "4537-7": "codes.labs.esr",
  "3016-3": "codes.labs.tsh",
  "3024-7": "codes.labs.freeT4",
  "3051-0": "codes.labs.freeT3",
  "6301-6": "codes.labs.inr",
  "5902-2": "codes.labs.pt",
  "3173-2": "codes.labs.aptt",
  "30934-4": "codes.labs.bnp",
  "10839-9": "codes.labs.troponinI",
  "6598-7": "codes.labs.troponinT",
  "2524-7": "codes.labs.lactate",
  "2276-4": "codes.labs.ferritin",
  "48065-7": "codes.labs.ddimer",
};

// Additional clinical categories
export type ObservationCategory =
  | 'vitals'
  | 'labs'
  | 'imaging'
  | 'exam'
  | 'procedures'
  | 'social'
  | 'medications'
  | 'immunizations'
  | 'allergies'
  | 'diagnoses'
  | 'medicationStatement'
  | 'questionnaire'
  | 'encounters';

export const IMAGING_CODE_MAPPINGS: Record<string, string> = {
  "18726-0": "codes.imaging.radiologyReport",
  "18748-4": "codes.imaging.diagnosticImaging",
  "18747-6": "codes.imaging.ctScan",
  "36643-5": "codes.imaging.ultrasound",
  "30954-2": "codes.imaging.xray",
  "18745-0": "codes.imaging.cardiacCatheterization",
  "18746-8": "codes.imaging.colonoscopy",
};

export const EXAM_CODE_MAPPINGS: Record<string, string> = {
  "8716-3": "codes.exam.physicalExam",
  "10210-3": "codes.exam.physicalFindings",
  "8302-2": "codes.vitals.height",
  "29463-7": "codes.vitals.weight",
  "39156-5": "codes.exam.bmi",
  "8867-4": "codes.vitals.heartRate",
  "8480-6": "codes.vitals.systolicBP",
  "8462-4": "codes.vitals.diastolicBP",
  "8310-5": "codes.vitals.temperature",
  "33747-0": "codes.exam.generalAppearance",
};

export const PROCEDURE_CODE_MAPPINGS: Record<string, string> = {
  "47519-4": "codes.procedures.historyOfProcedures",
  "8716-3": "codes.procedures.surgicalProcedure",
  "18776-5": "codes.procedures.treatmentPlan",
  "33747-0": "codes.procedures.procedurePerformed",
  "72133-2": "codes.procedures.procedureIndication",
  "59776-5": "codes.procedures.procedureOutcome",
};

export const SOCIAL_HISTORY_CODE_MAPPINGS: Record<string, string> = {
  "72166-2": "codes.social.tobaccoSmokingStatus",
  "11331-6": "codes.social.occupationalExposure",
  "76689-9": "codes.social.sexAssignedAtBirth",
  "72133-2": "codes.social.socialHistory",
  "229819007": "codes.social.tobaccoUse",
  "160573003": "codes.social.alcoholIntake",
  "182836005": "codes.social.reviewOfSystems",
  "408512008": "codes.social.bodyPiercing",
  "228273003": "codes.social.drugMisuseFinding",
};

export const MEDICATION_CODE_MAPPINGS: Record<string, string> = {
  "10160-0": "codes.medications.historyOfMedicationUse",
  "8716-3": "codes.medications.medicationAdministration",
  "182836005": "codes.medications.drugTherapy",
};

export const ALLERGY_CODE_MAPPINGS: Record<string, string> = {
  "48765-2": "codes.allergies.allergiesAndAdverseReactions",
  "10155-0": "codes.allergies.historyOfAllergicReaction",
  "420134006": "codes.allergies.propensityToAdverseReactions",
};

export const DIAGNOSIS_CODE_MAPPINGS: Record<string, string> = {
  "11348-0": "codes.diagnoses.historyOfPastIllness",
  "10154-3": "codes.diagnoses.chiefComplaint",
  "46239-0": "codes.diagnoses.reasonForEncounter",
  "8716-3": "codes.diagnoses.problemList",
};

export const MEDICATION_STATEMENT_CODE_MAPPINGS: Record<string, string> = {
  "182840001": "codes.medicationStatement.drugTreatment",
  "182836005": "codes.medicationStatement.reviewOfMedication",
  "432102000": "codes.medicationStatement.administrationOfSubstance",
  "182849000": "codes.medicationStatement.drugTherapyDiscontinued",
  "182842009": "codes.medicationStatement.drugTreatmentStarted",
  "182843004": "codes.medicationStatement.drugTreatmentStopped",
};

export const QUESTIONNAIRE_CODE_MAPPINGS: Record<string, string> = {
  "273879006": "codes.questionnaire.patientQuestionnaire",
  "162673000": "codes.questionnaire.generalExamination",
  "225336008": "codes.questionnaire.suicideRiskAssessment",
  "273724008": "codes.questionnaire.qualityOfLifeAssessment",
  "225358003": "codes.questionnaire.painAssessment",
  "386053000": "codes.questionnaire.evaluationProcedure",
  "710830005": "codes.questionnaire.assessmentOfAnxiety",
};

export const IMMUNIZATION_CODE_MAPPINGS: Record<string, string> = {
  "33879002": "codes.immunizations.immunizationProcedure",
  "127786006": "codes.immunizations.injectionOfVaccine",
  "170433008": "codes.immunizations.administrationOfVaccine",
  "396429000": "codes.immunizations.covid19Vaccination",
  "72093006": "codes.immunizations.influenzaVaccination",
  "16290008": "codes.immunizations.hepatitisBVaccination",
  "408864009": "codes.immunizations.pneumococcalVaccination",
  "396430005": "codes.immunizations.tetanusVaccination",
  "16584000": "codes.immunizations.pertussisVaccination",
  "396431009": "codes.immunizations.diphtheriaVaccination",
  "396432002": "codes.immunizations.polioVaccination",
  "396433007": "codes.immunizations.mmrVaccination",
};

export const ENCOUNTER_CODE_MAPPINGS: Record<string, string> = {
  "308335008": "codes.encounters.patientEncounterProcedure",
  "185349003": "codes.encounters.encounterForCheckUp",
  "270427003": "codes.encounters.patientInitiatedEncounter",
  "50849002": "codes.encounters.emergencyRoomVisit",
  "183807002": "codes.encounters.inpatientStay",
  "185345009": "codes.encounters.outpatientVisit",
};

// Map backend English displays to translation keys by category
export const DISPLAY_TO_KEY_MAPPINGS: Record<ObservationCategory, Record<string, string>> = {
  vitals: {
    "Heart rate": "codes.vitals.heartRate",
    "Respiratory rate": "codes.vitals.respiratoryRate",
    "Systolic BP": "codes.vitals.systolicBP",
    "Diastolic BP": "codes.vitals.diastolicBP",
    "Systolic blood pressure": "codes.vitals.systolicBP",
    "Diastolic blood pressure": "codes.vitals.diastolicBP",
    "Body temperature": "codes.vitals.temperature",
    "Oxygen saturation": "codes.vitals.oxygenSaturation",
    "Head circumference": "codes.vitals.headCircumference",
    "Body weight": "codes.vitals.weight",
    "Body height": "codes.vitals.height",
  },
  labs: {
    "Potassium": "codes.labs.potassium",
    "Glucose": "codes.labs.glucose",
    "Sodium": "codes.labs.sodium",
    "Hemoglobin A1c": "codes.labs.hba1c",
    "Hemoglobin": "codes.labs.hemoglobin",
    "Hematocrit": "codes.labs.hematocrit",
    "White blood cells": "codes.labs.wbc",
    "Platelets": "codes.labs.platelets",
    "Creatinine": "codes.labs.creatinine",
    "BUN": "codes.labs.bun",
    "Albumin": "codes.labs.albumin",
    "Bilirubin": "codes.labs.bilirubin",
  },
  imaging: {
    "Radiology report": "codes.imaging.radiologyReport",
    "Diagnostic imaging study": "codes.imaging.diagnosticImaging",
    "CT scan": "codes.imaging.ctScan",
    "Ultrasound": "codes.imaging.ultrasound",
    "X-ray": "codes.imaging.xray",
    "Cardiac catheterization": "codes.imaging.cardiacCatheterization",
    "Colonoscopy": "codes.imaging.colonoscopy",
  },
  exam: {
    "Physical examination": "codes.exam.physicalExam",
    "Physical findings": "codes.exam.physicalFindings",
    "Body mass index": "codes.exam.bmi",
    "General appearance": "codes.exam.generalAppearance",
    "Heart rate": "codes.vitals.heartRate",
    "Systolic blood pressure": "codes.vitals.systolicBP",
    "Diastolic blood pressure": "codes.vitals.diastolicBP",
    "Body temperature": "codes.vitals.temperature",
    "Body weight": "codes.vitals.weight",
    "Body height": "codes.vitals.height",
    "Systolic BP": "codes.vitals.systolicBP",
    "Diastolic BP": "codes.vitals.diastolicBP",
  },
  procedures: {
    "History of procedures": "codes.procedures.historyOfProcedures",
    "Surgical procedure": "codes.procedures.surgicalProcedure",
    "Treatment plan": "codes.procedures.treatmentPlan",
    "Procedure performed": "codes.procedures.procedurePerformed",
    "Procedure indication": "codes.procedures.procedureIndication",
    "Procedure outcome": "codes.procedures.procedureOutcome",
  },
  social: {
    "Tobacco smoking status": "codes.social.tobaccoSmokingStatus",
    "History of occupational exposure": "codes.social.occupationalExposure",
    "Sex assigned at birth": "codes.social.sexAssignedAtBirth",
    "Social history": "codes.social.socialHistory",
    "Tobacco use": "codes.social.tobaccoUse",
    "Alcohol intake": "codes.social.alcoholIntake",
    "Review of systems": "codes.social.reviewOfSystems",
    "Body piercing": "codes.social.bodyPiercing",
    "Finding relating to drug misuse": "codes.social.drugMisuseFinding",
  },
  medications: {
    "History of medication use": "codes.medications.historyOfMedicationUse",
    "Medication administration": "codes.medications.medicationAdministration",
    "Drug therapy": "codes.medications.drugTherapy",
    "Medication": "codes.medications.historyOfMedicationUse",
  },
  immunizations: {
    "Immunization procedure": "codes.immunizations.immunizationProcedure",
    "Injection of vaccine product": "codes.immunizations.injectionOfVaccine",
    "Administration of vaccine": "codes.immunizations.administrationOfVaccine",
    "Vaccination for COVID-19": "codes.immunizations.covid19Vaccination",
    "Influenza vaccination": "codes.immunizations.influenzaVaccination",
    "Hepatitis B vaccination": "codes.immunizations.hepatitisBVaccination",
    "Pneumococcal vaccination": "codes.immunizations.pneumococcalVaccination",
    "Tetanus vaccination": "codes.immunizations.tetanusVaccination",
    "Pertussis vaccination": "codes.immunizations.pertussisVaccination",
    "Diphtheria vaccination": "codes.immunizations.diphtheriaVaccination",
    "Polio vaccination": "codes.immunizations.polioVaccination",
    "MMR vaccination": "codes.immunizations.mmrVaccination",
  },
  allergies: {
    "Allergies and adverse reactions": "codes.allergies.allergiesAndAdverseReactions",
    "History of allergic reaction": "codes.allergies.historyOfAllergicReaction",
    "Propensity to adverse reactions": "codes.allergies.propensityToAdverseReactions",
  },
  diagnoses: {
    "History of past illness": "codes.diagnoses.historyOfPastIllness",
    "Chief complaint": "codes.diagnoses.chiefComplaint",
    "Reason for encounter": "codes.diagnoses.reasonForEncounter",
    "Problem list": "codes.diagnoses.problemList",
  },
  medicationStatement: {
    "Drug treatment": "codes.medicationStatement.drugTreatment",
    "Review of medication": "codes.medicationStatement.reviewOfMedication",
    "Administration of substance": "codes.medicationStatement.administrationOfSubstance",
    "Drug therapy discontinued": "codes.medicationStatement.drugTherapyDiscontinued",
    "Drug treatment started": "codes.medicationStatement.drugTreatmentStarted",
    "Drug treatment stopped": "codes.medicationStatement.drugTreatmentStopped",
  },
  questionnaire: {
    "Patient questionnaire": "codes.questionnaire.patientQuestionnaire",
    "General examination of patient": "codes.questionnaire.generalExamination",
    "Suicide risk assessment": "codes.questionnaire.suicideRiskAssessment",
    "Quality of life assessment": "codes.questionnaire.qualityOfLifeAssessment",
    "Pain assessment": "codes.questionnaire.painAssessment",
    "Evaluation procedure": "codes.questionnaire.evaluationProcedure",
    "Assessment of anxiety": "codes.questionnaire.assessmentOfAnxiety",
  },
  encounters: {
    "Patient encounter procedure": "codes.encounters.patientEncounterProcedure",
    "Encounter for check up": "codes.encounters.encounterForCheckUp",
    "Patient-initiated encounter": "codes.encounters.patientInitiatedEncounter",
    "Emergency room visit": "codes.encounters.emergencyRoomVisit",
    "Inpatient stay": "codes.encounters.inpatientStay",
    "Outpatient visit": "codes.encounters.outpatientVisit",
  },
};

const CATEGORY_TO_CODE_MAP: Record<ObservationCategory, Record<string, string>> = {
  vitals: VITAL_CODE_MAPPINGS,
  labs: LAB_CODE_MAPPINGS,
  imaging: IMAGING_CODE_MAPPINGS,
  exam: EXAM_CODE_MAPPINGS,
  procedures: PROCEDURE_CODE_MAPPINGS,
  social: SOCIAL_HISTORY_CODE_MAPPINGS,
  medications: MEDICATION_CODE_MAPPINGS,
  immunizations: IMMUNIZATION_CODE_MAPPINGS,
  allergies: ALLERGY_CODE_MAPPINGS,
  diagnoses: DIAGNOSIS_CODE_MAPPINGS,
  medicationStatement: MEDICATION_STATEMENT_CODE_MAPPINGS,
  questionnaire: QUESTIONNAIRE_CODE_MAPPINGS,
  encounters: ENCOUNTER_CODE_MAPPINGS,
};

export function getDisplayKey(inputKey: string, category: ObservationCategory): string {
  // Try LOINC/SNOMED code mapping first
  const byCode = CATEGORY_TO_CODE_MAP[category]?.[inputKey];
  if (byCode) return byCode;
  // Then try English display mapping from backend
  const displayMap = DISPLAY_TO_KEY_MAPPINGS[category] || {};
  if (displayMap[inputKey]) return displayMap[inputKey];
  // Case-insensitive exact match
  const lower = inputKey.toLowerCase();
  for (const [k, v] of Object.entries(displayMap)) {
    if (k.toLowerCase() === lower) return v;
  }
  // Heuristics
  if (category === 'vitals') {
    if (lower.includes('systolic')) return 'codes.vitals.systolicBP';
    if (lower.includes('diastolic')) return 'codes.vitals.diastolicBP';
    if (/(heart\s*rate|pulse)/.test(lower)) return 'codes.vitals.heartRate';
    if (lower.includes('respiratory rate')) return 'codes.vitals.respiratoryRate';
    if (lower.includes('temperature')) return 'codes.vitals.temperature';
    if (/(oxygen\s*saturation|spo2)/.test(lower)) return 'codes.vitals.oxygenSaturation';
    if (lower.includes('height')) return 'codes.vitals.height';
    if (lower.includes('weight')) return 'codes.vitals.weight';
  }
  if (category === 'labs') {
    const contains = (term: string) => lower.includes(term);
    if (contains('glucose')) return 'codes.labs.glucose';
    if (contains('potassium') || /\bk\b/.test(lower)) return 'codes.labs.potassium';
    if (contains('sodium') || /\bna\b/.test(lower)) return 'codes.labs.sodium';
    if (contains('hemoglobin a1c') || contains('hba1c')) return 'codes.labs.hba1c';
    if (contains('hemoglobin')) return 'codes.labs.hemoglobin';
    if (contains('hematocrit')) return 'codes.labs.hematocrit';
    if (contains('white blood') || contains('wbc')) return 'codes.labs.wbc';
    if (contains('platelet')) return 'codes.labs.platelets';
    if (contains('creatinine')) return 'codes.labs.creatinine';
    if (contains('urea') || contains('bun')) return 'codes.labs.bun';
    if (contains('albumin')) return 'codes.labs.albumin';
    if (contains('bilirubin')) return 'codes.labs.bilirubin';
    if (contains('cholesterol')) return 'codes.labs.cholesterol';
    if (contains('ldl')) return 'codes.labs.ldl';
    if (contains('hdl')) return 'codes.labs.hdl';
    if (contains('triglyceride')) return 'codes.labs.triglycerides';
    if (contains('calcium')) return 'codes.labs.calcium';
    if (contains('chloride')) return 'codes.labs.chloride';
    if (contains('carbon dioxide') || contains('co2')) return 'codes.labs.co2';
    if (contains('anion gap')) return 'codes.labs.anionGap';
    if (contains('magnesium')) return 'codes.labs.magnesium';
    if (contains('phosphorus') || contains('phosphate')) return 'codes.labs.phosphorus';
    if (contains('alt')) return 'codes.labs.alt';
    if (contains('ast')) return 'codes.labs.ast';
    if (contains('alkaline phosphatase') || contains('alp')) return 'codes.labs.alp';
    if (contains('gamma-glutamyl') || contains('ggt')) return 'codes.labs.ggt';
    if (contains('c-reactive') || contains('crp')) return 'codes.labs.crp';
    if (contains('erythrocyte sedimentation') || contains('esr')) return 'codes.labs.esr';
    if (contains('tsh')) return 'codes.labs.tsh';
    if (contains('free t4')) return 'codes.labs.freeT4';
    if (contains('free t3')) return 'codes.labs.freeT3';
    if (contains('inr')) return 'codes.labs.inr';
    if (contains('prothrombin') || /\bpt\b/.test(lower)) return 'codes.labs.pt';
    if (contains('aptt') || contains('partial thromboplastin')) return 'codes.labs.aptt';
    if (contains('bnp')) return 'codes.labs.bnp';
    if (contains('troponin t')) return 'codes.labs.troponinT';
    if (contains('troponin i') || contains('troponin')) return 'codes.labs.troponinI';
    if (contains('lactate')) return 'codes.labs.lactate';
    if (contains('ferritin')) return 'codes.labs.ferritin';
    if (contains('d-dimer') || contains('d dimer')) return 'codes.labs.ddimer';
  }
  if (category === 'immunizations') {
    if (/covid|sars\s*-?cov-?2/i.test(lower)) return 'codes.immunizations.covid19Vaccination';
    if (/influenza|flu/i.test(lower)) return 'codes.immunizations.influenzaVaccination';
    if (/hepatitis\s*b/i.test(lower)) return 'codes.immunizations.hepatitisBVaccination';
    if (/pneumococ/i.test(lower)) return 'codes.immunizations.pneumococcalVaccination';
    if (/tetan(us)?|\btd\b/i.test(lower)) return 'codes.immunizations.tetanusVaccination';
    if (/pertussis|whooping/i.test(lower)) return 'codes.immunizations.pertussisVaccination';
    if (/diphtheria/i.test(lower)) return 'codes.immunizations.diphtheriaVaccination';
    if (/polio/i.test(lower)) return 'codes.immunizations.polioVaccination';
    if (/mmr|measles|mumps|rubella/i.test(lower)) return 'codes.immunizations.mmrVaccination';
    if (/zoster|shingle/i.test(lower)) return 'codes.immunizations.zosterVaccination' as any;
  }
  return inputKey; // fallback
}

// Deprecated: prefer getDisplayKey(key, category)
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
  if (v.startsWith('m')) return 'common.Sex.male';
  if (v.startsWith('f') || v.startsWith('kv')) return 'common.Sex.female';
  if (v.includes('other')) return 'common.Sex.other';
  if (v.includes('unknown')) return 'common.Sex.unknown';
  return 'common.Sex.unknown';
}