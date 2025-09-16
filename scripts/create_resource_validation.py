#!/usr/bin/env python3
# create_resource_validation.py
import json
import uuid
import argparse
import requests
import copy
import re
import itertools
import base64
import datetime
import os
import csv

# ---------- Helpers ----------
def rid(): return str(uuid.uuid4())
def ref(rt, _id): return f"{rt}/{_id}"
def now_iso(): return datetime.datetime(2025, 9, 3, 10, 0, 0).isoformat() + "+02:00"

# Factors (16) to mask
FACTORS = [
    "Patient","Encounter","Condition","Procedure","Observation","DiagnosticReport","ImagingStudy",
    "Medication","MedicationStatement","AllergyIntolerance","CarePlan","Appointment","DocumentReference",
    "FamilyMemberHistory","Immunization","QuestionnaireResponse"
]
TOP8 = ["Condition","DiagnosticReport","DocumentReference","Observation",
        "Medication","Encounter","CarePlan","ImagingStudy"]

def build_index_map():
    """
    0: baseline
    1..16: one-at-a-time masks (FACTORS order)
    17..136: all unordered pairs among 16
    137..192: all unordered triples among TOP8 (C(8,3)=56)
    """
    m = {0: []}
    idx = 1
    for f in FACTORS:
        m[idx] = [f]
        idx += 1
    for a,b in itertools.combinations(FACTORS, 2):
        m[idx] = [a,b]
        idx += 1
    for a,b,c in itertools.combinations(TOP8, 3):
        m[idx] = [a,b,c]
        idx += 1
    assert idx == 193, f"Got {idx} indices, expected 193"
    return m

# ---------- Baseline bundle builder (R4) ----------
def build_baseline_bundle(patient_name="patname_0"):
    org_id, prac_id, pat_id = "org-1", "prac-1", "pat-0"
    enc_emer, enc_inp, enc_amb = "enc-emer", "enc-inp", "enc-amb"
    # Medication and MedicationStatement ids
    meds = {
        "Apixaban 5 mg": ("med-apixaban", "ms-apixaban", "BID"),
        "Furosemide 40 mg": ("med-furosemide", "ms-furosemide", "QD"),
        "Metoprolol 50 mg": ("med-metoprolol", "ms-metoprolol", "BID"),
        "Tiotropium inhaler 18 mcg": ("med-tiotropium", "ms-tiotropium", "QD"),
        "Salbutamol 100 mcg": ("med-salbutamol", "ms-salbutamol", "PRN"),
        "Metformin 1000 mg": ("med-metformin", "ms-metformin", "BID"),
        "Insulin glargine 18 units": ("med-glargine", "ms-glargine", "HS"),
        "Pantoprazole 20 mg": ("med-pantoprazole", "ms-pantoprazole", "QD")
    }

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "id": "baseline-collection",
        "timestamp": now_iso(),
        "entry": [
            {"resource": {"resourceType": "Organization", "id": org_id, "name": "Synthetic University Hospital", "address": [{"city": "Stockholm", "country": "SE"}]}},
            {"resource": {"resourceType": "Practitioner", "id": prac_id, "name": [{"family": "Lindgren", "given": ["Karin"]}]}},
            {"resource": {"resourceType": "Patient", "id": pat_id, "identifier": [{"system": "http://example.org/pid", "value": "19780315-1234"}],
                          "name": [{"family": "StudyCase", "given": [patient_name]}], "gender": "male", "birthDate": "1978-03-15",
                          "address": [{"line": ["Examplevägen 12"], "city": "Stockholm", "country": "SE"}],
                          "generalPractitioner": [{"reference": ref("Practitioner", prac_id)}],
                          "managingOrganization": {"reference": ref("Organization", org_id)}}},
            # Encounters
            {"resource": {"resourceType": "Encounter", "id": enc_emer, "status": "finished", "class": {"code": "EMER", "display": "emergency"},
                          "subject": {"reference": ref("Patient", pat_id)}, "period": {"start": "2025-08-18T12:30:00+02:00", "end": "2025-08-18T18:15:00+02:00"},
                          "serviceProvider": {"reference": ref("Organization", org_id)}}},
            {"resource": {"resourceType": "Encounter", "id": enc_inp, "status": "finished", "class": {"code": "IMP", "display": "inpatient"},
                          "subject": {"reference": ref("Patient", pat_id)}, "period": {"start": "2025-08-18T18:30:00+02:00", "end": "2025-08-23T10:00:00+02:00"},
                          "serviceProvider": {"reference": ref("Organization", org_id)}}},
            {"resource": {"resourceType": "Encounter", "id": enc_amb, "status": "finished", "class": {"code": "AMB", "display": "ambulatory"},
                          "subject": {"reference": ref("Patient", pat_id)}, "period": {"start": "2025-09-01T14:00:00+02:00", "end": "2025-09-01T14:30:00+02:00"},
                          "serviceProvider": {"reference": ref("Organization", org_id)}}},
            # Conditions (diagnoses)
            {"resource": {"resourceType": "Condition", "id": "cond-t2dm", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes mellitus"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                          "onsetDateTime": "2018-01-10"}},
            {"resource": {"resourceType": "Condition", "id": "cond-copd", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "84114007", "display": "Chronic obstructive pulmonary disease"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}}},
            {"resource": {"resourceType": "Condition", "id": "cond-ihd", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "42343007", "display": "Chronic ischemic heart disease"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}}},
            {"resource": {"resourceType": "Condition", "id": "cond-af", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "13645005", "display": "Atrial fibrillation"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}}},
            {"resource": {"resourceType": "Condition", "id": "cond-ckd3b", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "709044004", "display": "Chronic kidney disease stage 3b"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}}},
            {"resource": {"resourceType": "Condition", "id": "cond-copd-exac", "subject": {"reference": ref("Patient", pat_id)},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "84114007", "display": "COPD exacerbation"}]},
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}}},
            # Observations (vitals)
            {"resource": {"resourceType": "Observation", "id": "obs-sbp", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 158, "unit": "mmHg"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-dbp", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 94, "unit": "mmHg"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-hr", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 110, "unit": "/min"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-rr", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "9279-1", "display": "Respiratory rate"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 24, "unit": "/min"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-spo2", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "59408-5", "display": "Oxygen saturation in Arterial blood by Pulse oximetry"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 89, "unit": "%"}}},

            # Observations (labs)
            {"resource": {"resourceType": "Observation", "id": "obs-egfr", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "38483-4", "display": "eGFR"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-19T07:30:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_inp)}, "valueQuantity": {"value": 38, "unit": "mL/min/1.73m2"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-creat", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-19T07:30:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_inp)}, "valueQuantity": {"value": 158, "unit": "µmol/L"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-hba1c", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "1988-5", "display": "HBA1c"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-10T09:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_amb)}, "valueQuantity": {"value": 64, "unit": "mmol/mol"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-fev1", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "11557-6", "display": "FEV1"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-20T09:00:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_inp)}, "valueQuantity": {"value": 58, "unit": "%pred"}}},

            # Observations (exam & social-history)
            {"resource": {"resourceType": "Observation", "id": "obs-exam-narr", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "exam"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "29545-1", "display": "Physical findings narrative"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:30:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}}},
            {"resource": {"resourceType": "Observation", "id": "obs-wheeze", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "exam"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "36681-3", "display": "Wheezes [Presence] in Chest by Auscultation"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T13:30:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 1, "unit": "{presence}"}}},
            {"resource": {"resourceType": "Observation", "id": "obs-smoke", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "social-history"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "72166-2", "display": "Tobacco smoking status"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T12:45:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}}},
            {"resource": {"resourceType": "Observation", "id": "obs-packyears", "status": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "social-history"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "11366-2", "display": "Pack years Tobacco"}]},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T12:45:00+02:00",
                          "encounter": {"reference": ref("Encounter", enc_emer)}, "valueQuantity": {"value": 25, "unit": "pack-years"}}},

            # ImagingStudy & DiagnosticReports
            {"resource": {"resourceType": "ImagingStudy", "id": "img-cxr", "status": "available", "subject": {"reference": ref("Patient", pat_id)},
                          "started": "2025-08-18T15:00:00+02:00", "description": "Portable AP chest radiograph"}},
            {"resource": {"resourceType": "DiagnosticReport", "id": "dr-cxr", "status": "final",
                          "category": [{"coding": [{"system": "http://loinc.org", "code": "LP29684-5", "display": "Radiology"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "30746-2", "display": "Radiology study observation [Imaging]"}], "text": "Chest radiograph"},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2025-08-18T15:00:00+02:00",
                          "imagingStudy": [{"reference": ref("ImagingStudy", "img-cxr")}],
                          "conclusion": "Hyperinflated lungs consistent with COPD. No focal consolidation."}},
            {"resource": {"resourceType": "DiagnosticReport", "id": "dr-cta", "status": "final",
                          "category": [{"coding": [{"system": "http://loinc.org", "code": "LP29684-5", "display": "Radiology"}]}],
                          "code": {"coding": [{"system": "http://loinc.org", "code": "46385-0", "display": "CT Angiogram chest"}], "text": "CT Angiogram Chest"},
                          "subject": {"reference": ref("Patient", pat_id)}, "effectiveDateTime": "2022-11-12T10:00:00+01:00",
                          "conclusion": "Ascending aorta measures 4.6 cm; recommend 6-month follow-up imaging."}},
            {"resource": {"resourceType": "DiagnosticReport", "id": "dr-labs", "status": "final",
                          "category": [{"coding": [{"system": "http://loinc.org", "code": "LP29627-3", "display": "Laboratory medicine"}]}],
                          "code": {"text": "Basic Metabolic Panel"}, "subject": {"reference": ref("Patient", pat_id)},
                          "effectiveDateTime": "2025-08-19T07:30:00+02:00",
                          "result": [{"reference": ref("Observation", "obs-egfr")}, {"reference": ref("Observation", "obs-creat")}]}},

            # Procedure
            {"resource": {"resourceType": "Procedure", "id": "proc-pci", "status": "completed",
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "415070008", "display": "Percutaneous coronary intervention"}], "text": "PCI to LAD"},
                          "subject": {"reference": ref("Patient", pat_id)}, "performedDateTime": "2019-05-21"}},

            # Medications + MedicationStatements
            *[
                {"resource": {"resourceType": "Medication", "id": m_id, "code": {"text": m_name},
                              "form": {"text": "tablet" if "inhaler" not in m_name and "glargine" not in m_name else ("inhalation" if "inhaler" in m_name else "injection")},
                              "ingredient": [{"itemCodeableConcept": {"text": m_name.split()[0].lower()}}]}}
                for m_name, (m_id, ms_id, _dose) in meds.items()
            ],
            *[
                {"resource": {"resourceType": "MedicationStatement", "id": ms_id, "status": "active",
                              "medicationReference": {"reference": ref("Medication", m_id)},
                              "subject": {"reference": ref("Patient", pat_id)}, "effectivePeriod": {"start": "2025-08-23"},
                              "dosage": [{"text": dose}]}}
                for m_name, (m_id, ms_id, dose) in meds.items()
            ],

            # Allergy, Family history, Immunization
            {"resource": {"resourceType": "AllergyIntolerance", "id": "alg-pen",
                          "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
                          "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]},
                          "code": {"coding": [{"system": "http://snomed.info/sct", "code": "7982", "display": "Penicillin"}], "text": "Penicillin"},
                          "patient": {"reference": ref("Patient", pat_id)}, "reaction": [{"manifestation": [{"text": "Rash"}]}]}},
            {"resource": {"resourceType": "FamilyMemberHistory", "id": "famhx-1", "status": "completed",
                          "patient": {"reference": ref("Patient", pat_id)}, "relationship": {"text": "Father"},
                          "condition": [{"code": {"text": "Myocardial infarction at 54"}}]}},
            {"resource": {"resourceType": "Immunization", "id": "imm-1", "status": "completed", "vaccineCode": {"text": "Influenza, quadrivalent"},
                          "patient": {"reference": ref("Patient", pat_id)}, "occurrenceDateTime": "2024-10-01"}},

            # CarePlan
            {"resource": {"resourceType": "CarePlan", "id": "cp-1", "status": "active", "intent": "plan",
                          "subject": {"reference": ref("Patient", pat_id)}, "title": "COPD management plan",
                          "description": "Inhaler technique review, smoking cessation counseling, pulmonary rehab referral",
                          "period": {"start": "2025-08-23"}}},

            # Appointment (follow-up)
            {"resource": {"resourceType": "Appointment", "id": "appt-1", "status": "booked", "start": "2025-09-15T10:00:00+02:00", "end": "2025-09-15T10:20:00+02:00",
                          "participant": [{"actor": {"reference": ref("Patient", pat_id)}, "status": "accepted"},
                                          {"actor": {"reference": ref("Practitioner", prac_id)}, "status": "accepted"}],
                          "reasonCode": [{"text": "Post-discharge review"}]}},

            # Questionnaire + Response (canonical fix)
            {"resource": {"resourceType": "Questionnaire", "id": "q-1",
                          "url": "http://example.org/fhir/Questionnaire/q-1",
                          "title": "COPD Assessment (Simplified)", "item": [
                              {"linkId": "1", "text": "MRC Dyspnea Grade", "type": "choice", "answerOption": [{"valueCoding": {"code": str(i), "display": f"Grade {i}"}} for i in range(1, 6)]},
                              {"linkId": "2", "text": "Smoking cessation interest", "type": "choice", "answerOption": [{"valueCoding": {"code": "Y", "display": "Yes"}}, {"valueCoding": {"code": "N", "display": "No"}}]}
                          ]}},
            {"resource": {"resourceType": "QuestionnaireResponse", "id": "qr-1",
                          "questionnaire": "http://example.org/fhir/Questionnaire/q-1",
                          "status": "completed", "subject": {"reference": ref("Patient", pat_id)}, "authored": "2025-08-21T09:00:00+02:00",
                          "item": [{"linkId": "1", "answer": [{"valueCoding": {"code": "3", "display": "Grade 3"}}]},
                                   {"linkId": "2", "answer": [{"valueCoding": {"code": "Y", "display": "Yes"}}]}]}},

            # DocumentReference (unstructured notes)
            {"resource": {"resourceType": "DocumentReference", "id": "doc-admit", "status": "current", "docStatus": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/document-reference-category", "code": "clinical-note", "display": "Clinical Note"}]}],
                          "type": {"coding": [{"system": "http://loinc.org", "code": "34745-0", "display": "Admission note"}], "text": "Admission note"},
                          "subject": {"reference": ref("Patient", pat_id)}, "author": [
                              {"reference": ref("Practitioner", prac_id)},
                              {"reference": ref("Organization", org_id)}
                          ], "custodian": {"reference": ref("Organization", org_id)},
                          "date": "2025-08-18T13:30:00+02:00",
                          "context": {"encounter": [{"reference": ref("Encounter", enc_emer)}]},
                          "content": [{"attachment": {"contentType": "text/plain", "language": "en", "title": "ED Admission Note",
                                                     "creation": "2025-08-18T13:30:00+02:00",
                                                     "data": base64.b64encode(
                                                         (
                                                             "ED Admission Note (2025-08-18):\n"
                                                             "56M with COPD, AF on apixaban, DM2, CKD3b presents with worsening dyspnea, cough with sputum, "
                                                             "and wheeze. SpO2 89% RA, RR 24, HR 110, BP 158/94. CXR: hyperinflation, no consolidation. "
                                                             "Plan: oxygen, nebulized salbutamol/ipratropium, prednisolone 50 mg x5 days, antibiotics deferred."
                                                         ).encode('utf-8')
                                                     ).decode('ascii')}}]}},

            {"resource": {"resourceType": "DocumentReference", "id": "doc-progress", "status": "current", "docStatus": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/document-reference-category", "code": "clinical-note", "display": "Clinical Note"}]}],
                          "type": {"coding": [{"system": "http://loinc.org", "code": "11504-8", "display": "Progress note"}], "text": "Progress note"},
                          "subject": {"reference": ref("Patient", pat_id)}, "author": [
                              {"reference": ref("Practitioner", prac_id)},
                              {"reference": ref("Organization", org_id)}
                          ], "custodian": {"reference": ref("Organization", org_id)},
                          "date": "2025-08-20T10:15:00+02:00",
                          "context": {"encounter": [{"reference": ref("Encounter", enc_inp)}]},
                          "content": [{"attachment": {"contentType": "text/plain", "language": "en", "title": "Inpatient Progress Note",
                                                     "creation": "2025-08-20T10:15:00+02:00",
                                                     "data": base64.b64encode(
                                                         (
                                                             "Inpatient Progress (2025-08-20):\n"
                                                             "Improving after bronchodilators and steroids. FEV1 58%pred. Creatinine peaked 158 µmol/L, eGFR 38. "
                                                             "Glycemia elevated; start basal insulin. Review prior CT Angio (2022-11-12): ascending aorta 4.6 cm; "
                                                             "no documented follow-up. Arrange outpatient echo/CT aorta in 3 months."
                                                         ).encode('utf-8')
                                                     ).decode('ascii')}}]}},

            {"resource": {"resourceType": "DocumentReference", "id": "doc-discharge", "status": "current", "docStatus": "final",
                          "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/document-reference-category", "code": "clinical-note", "display": "Clinical Note"}]}],
                          "type": {"coding": [{"system": "http://loinc.org", "code": "18842-5", "display": "Discharge summary"}], "text": "Discharge summary"},
                          "subject": {"reference": ref("Patient", pat_id)}, "author": [
                              {"reference": ref("Practitioner", prac_id)},
                              {"reference": ref("Organization", org_id)}
                          ], "custodian": {"reference": ref("Organization", org_id)},
                          "date": "2025-08-23T09:30:00+02:00",
                          "context": {"encounter": [{"reference": ref("Encounter", enc_inp)}]},
                          "content": [{"attachment": {"contentType": "text/plain", "language": "en", "title": "Discharge Summary",
                                                     "creation": "2025-08-23T09:30:00+02:00",
                                                     "data": base64.b64encode(
                                                         (
                                                             "Discharge Summary (2025-08-23):\n"
                                                             "Principal diagnosis: COPD exacerbation. Secondary: AF, DM2, CKD3b, CAD s/p PCI 2019. "
                                                             "Treatments: O2, nebulized bronchodilators, oral steroids. "
                                                             "Discharge meds: apixaban 5 mg BID, metoprolol 50 mg BID, furosemide 40 mg QD, tiotropium QD, "
                                                             "salbutamol PRN, metformin 1 g BID, insulin glargine 18 U HS, pantoprazole 20 mg QD. "
                                                             "Follow-up: GP in 2 weeks; cardiology for AF rate control; imaging to re-evaluate ascending aorta in 3 months."
                                                         ).encode('utf-8')
                                                     ).decode('ascii')}}]}},

            # Ground-truth for eval (parked in Basic)
            {"resource": {"resourceType": "Basic", "id": "basic-groundtruth", "code": {"text": "ground-truth-eval"},
                          "extension": [{"url": "http://example.org/fhir/StructureDefinition/ground-truth", "valueString": json.dumps({
                              "discharge_summary_template_slots": {
                                  "principal_diagnosis": "COPD exacerbation",
                                  "secondary_diagnoses": ["Atrial fibrillation", "Type 2 diabetes mellitus", "Chronic kidney disease stage 3b", "Chronic ischemic heart disease"],
                                  "key_procedures": ["Oxygen therapy", "Nebulized bronchodilators", "Oral corticosteroids"],
                                  "meds_at_discharge": list(meds.keys()),
                                  "allergies": ["Penicillin"],
                                  "notable_findings_requiring_followup": ["Ascending aorta 4.6 cm on CT Angio 2022; re-image in 3 months"],
                                  "follow_up_plan": ["GP visit in 2 weeks", "Cardiology review for AF rate control", "CT/echo aorta in 3 months"],
                                  "disposition": "Home"
                              },
                              "patient_summary_key_facts": [
                                  "56-year-old male with COPD, AF, DM2, CKD3b, CAD s/p PCI (2019)",
                                  "Recent admission 2025-08-18 to 2025-08-23 for COPD exacerbation",
                                  "eGFR 38 mL/min/1.73m2; creatinine 158 µmol/L during admission",
                                  "HbA1c 64 mmol/mol (poor control)",
                                  "Penicillin allergy (rash)",
                                  "Imaging 2022 showed ascending aorta 4.6 cm; follow-up pending",
                                  "Active meds include apixaban, metoprolol, furosemide, tiotropium, insulin glargine",
                                  "Smoking cessation and pulmonary rehab recommended"
                              ]
                          })}]}}
        ]
    }
    return bundle




# ---------- Masking ----------
def mask_resource(res):
    rt = res.get("resourceType")
    r = copy.deepcopy(res)
    # Generic trim
    for k in ["text","note","interpretation","conclusion","category","presentedForm","component"]:
        r.pop(k, None)
    # Per-type redactions to remove informative content but keep resource alive
    if rt == "Patient":
        r["name"] = [{"family":"Masked","given":["masked"]}]
        for k in ["gender","birthDate","address","identifier","generalPractitioner","managingOrganization","communication","contact"]:
            r.pop(k, None)
    elif rt == "Encounter":
        for k in ["period","class","type","reasonCode","diagnosis","serviceProvider"]:
            r.pop(k, None)
    elif rt == "Condition":
        for k in ["code","clinicalStatus","verificationStatus","onsetDateTime","category","stage","evidence"]:
            r.pop(k, None)
    elif rt == "Procedure":
        for k in ["code","performedDateTime","performedPeriod","reasonCode","outcome"]:
            r.pop(k, None)
    elif rt == "Observation":
        for k in ["code","valueQuantity","valueString","valueCodeableConcept","effectiveDateTime","dataAbsentReason","encounter"]:
            r.pop(k, None)
        r.pop("category", None)
    elif rt == "DiagnosticReport":
        for k in ["code","conclusion","result","effectiveDateTime","imagingStudy"]:
            r.pop(k, None)
    elif rt == "ImagingStudy":
        for k in ["description","series","started","endpoint"]:
            r.pop(k, None)
    elif rt == "Medication":
        for k in ["code","form","ingredient"]:
            r.pop(k, None)
    elif rt == "MedicationStatement":
        for k in ["medicationReference","medicationCodeableConcept","effectivePeriod","dosage","status"]:
            r.pop(k, None)
    elif rt == "AllergyIntolerance":
        for k in ["code","reaction","criticality","category","verificationStatus","clinicalStatus"]:
            r.pop(k, None)
    elif rt == "CarePlan":
        for k in ["title","description","activity","goal","period"]:
            r.pop(k, None)
    elif rt == "Appointment":
        for k in ["reasonCode","start","end","description"]:
            r.pop(k, None)
    elif rt == "DocumentReference":
        for k in ["type","date","context","content"]:
            r.pop(k, None)
    elif rt == "FamilyMemberHistory":
        for k in ["condition","relationship","bornDate"]:
            r.pop(k, None)
    elif rt == "Immunization":
        for k in ["vaccineCode","occurrenceDateTime","doseQuantity"]:
            r.pop(k, None)
    elif rt == "QuestionnaireResponse":
        for k in ["questionnaire","item","authored"]:
            r.pop(k, None)
    return r

def apply_masks(bundle, mask_types):
    newb = copy.deepcopy(bundle)
    for e in newb["entry"]:
        res = e["resource"]
        if res.get("resourceType") in mask_types:
            e["resource"] = mask_resource(res)
    newb["entry"].append({"resource":{
        "resourceType":"Basic","id":rid(),"code":{"text":"mask-info"},
        "extension":[{"url":"http://example.org/mask","valueString": json.dumps(mask_types)}]
    }})
    return newb

# ---------- Transaction converter & uploader ----------
def to_transaction(collection_bundle):
    tx = {"resourceType":"Bundle","type":"transaction","entry":[]}
    idmap = {}
    for ent in collection_bundle.get("entry", []):
        res = ent["resource"]
        idmap[(res["resourceType"], res.get("id"))] = f"urn:uuid:{uuid.uuid4()}"
    def rewrite(o):
        if isinstance(o, dict):
            for k,v in list(o.items()):
                if k == "reference" and isinstance(v, str):
                    m = re.match(r"^([A-Za-z]+)\/([A-Za-z0-9\-\.\_]{1,64})$", v)
                    if m and (m.group(1), m.group(2)) in idmap:
                        o[k] = idmap[(m.group(1), m.group(2))]
                else:
                    rewrite(v)
        elif isinstance(o, list):
            for it in o:
                rewrite(it)
    for ent in collection_bundle.get("entry", []):
        res = copy.deepcopy(ent["resource"])
        rt, rid_ = res["resourceType"], res.get("id")
        fullUrl = idmap[(rt, rid_)]
        res.pop("id", None)
        rewrite(res)
        # Ensure required fields for server acceptance
        if rt == "ImagingStudy" and "status" not in res:
            res["status"] = "available"
        tx["entry"].append({"fullUrl":fullUrl,"resource":res,"request":{"method":"POST","url":rt}})
    return tx

def write_bundles(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    index_map = build_index_map()
    base = build_baseline_bundle("patname_0")
    for i in range(193):
        b = base if i==0 else apply_masks(base, index_map[i])
        # set patient name
        for e in b["entry"]:
            if e["resource"]["resourceType"] == "Patient":
                e["resource"]["name"] = [{"family":"StudyCase","given":[f"patname_{i}"]}]
                break
        path = os.path.join(out_dir, f"fhir_bundle_patname_{i}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(b, f, indent=2, ensure_ascii=False)
    # mask maps
    with open(os.path.join(out_dir, "mask_map.json"), "w", encoding="utf-8") as f:
        json.dump(index_map, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "mask_map.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index","masked_types"])
        for i in range(193):
            w.writerow([i, ";".join(index_map[i])])

def upload_bundles(out_dir, fhir_url, glob_prefix="fhir_bundle_patname_", session=None):
    sess = session or requests.Session()
    for i in range(193):
        p = os.path.join(out_dir, f"{glob_prefix}{i}.json")
        with open(p, "r", encoding="utf-8") as f:
            coll = json.load(f)
        tx = to_transaction(coll)
        r = sess.post(fhir_url.rstrip("/"), json=tx, headers={"Content-Type":"application/fhir+json"})
        if r.status_code < 200 or r.status_code >= 300:
            raise RuntimeError(f"Upload failed for index {i}: {r.status_code} {r.text}")
        else:
            print(f"Uploaded index {i} OK ({r.status_code})")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="./bundles", help="Where to write bundles")
    ap.add_argument("--fhir-url", default=None, help="FHIR base URL to upload to (e.g., http://localhost:8080/fhir)")
    ap.add_argument("--generate-only", action="store_true", help="Only generate files, do not upload")
    args = ap.parse_args()

    print("Generating 193 bundles + mask maps…")
    write_bundles(args.out_dir)
    print(f"Wrote bundles to {args.out_dir}")

    if args.fhir_url and not args.generate_only:
        print(f"Uploading to {args.fhir_url}…")
        upload_bundles(args.out_dir, args.fhir_url)
        print("Upload complete.")
    else:
        print("Skipping upload (no --fhir-url or --generate-only set).")
