-- Migration 005: Create Note Templates and Generation Metadata Tables
-- Purpose: Support clinical note generation feature with GDPR compliance
-- NO PHI/NOTE CONTENT STORED - Only templates and metadata

-- Note Templates Table (structure only, no PHI)
CREATE TABLE IF NOT EXISTS note_templates (
    template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('sv', 'en')),
    template_type TEXT NOT NULL,
    template_structure JSONB NOT NULL,
    is_system_template BOOLEAN DEFAULT FALSE,
    file_format TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_note_templates_user ON note_templates(user_id);
CREATE INDEX idx_note_templates_type ON note_templates(template_type);
CREATE INDEX idx_note_templates_language ON note_templates(language);
CREATE INDEX idx_note_templates_system ON note_templates(is_system_template);

-- RLS Policies for multi-tenant security
ALTER TABLE note_templates ENABLE ROW LEVEL SECURITY;

-- Users can see their own templates and system templates
CREATE POLICY note_templates_user_access ON note_templates
    FOR ALL
    USING (
        user_id = current_setting('app.user_id', true)::VARCHAR
        OR is_system_template = TRUE
    );

-- Generation Metadata Table (GDPR-safe, NO CONTENT)
-- This table stores ONLY metadata about note generation for audit/analytics
-- The actual generated note content is NEVER persisted
CREATE TABLE IF NOT EXISTS note_generation_metadata (
    generation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    patient_id UUID,  -- Reference only, no PHI
    template_id UUID NOT NULL REFERENCES note_templates(template_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    template_name TEXT NOT NULL,
    template_type TEXT NOT NULL,
    language TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    context_prompt_hash TEXT,  -- SHA256 hash for analytics
    chunks_used_count INT DEFAULT 0,
    conversation_turns_included INT DEFAULT 0,
    export_method TEXT,  -- 'clipboard', 'download', 'ehr', 'cancelled'
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Indexes for analytics and reporting
CREATE INDEX idx_note_gen_user ON note_generation_metadata(user_id);
CREATE INDEX idx_note_gen_patient ON note_generation_metadata(patient_id);
CREATE INDEX idx_note_gen_created ON note_generation_metadata(created_at DESC);
CREATE INDEX idx_note_gen_status ON note_generation_metadata(generation_status);
CREATE INDEX idx_note_gen_template ON note_generation_metadata(template_id);

-- Insert System Templates
-- These are pre-defined templates available to all users

-- Swedish Templates
INSERT INTO note_templates (user_id, name, language, template_type, template_structure, is_system_template, file_format) VALUES
-- 1. Journalanteckning (Journal Entry) - Swedish
('system', 'Journalanteckning', 'sv', 'journal_entry',
 '{
   "fields": [
     {"name": "anamnes", "label": "Anamnes", "type": "text", "description": "Patientens berättelse och symtom"},
     {"name": "status", "label": "Status", "type": "text", "description": "Kliniska fynd och undersökningsresultat"},
     {"name": "bedomning", "label": "Bedömning", "type": "text", "description": "Klinisk bedömning och diagnos"},
     {"name": "atgard", "label": "Åtgärd", "type": "text", "description": "Vidtagna åtgärder och behandling"},
     {"name": "plan", "label": "Plan", "type": "text", "description": "Behandlingsplan och uppföljning"}
   ]
 }'::jsonb, TRUE, 'json'),

-- 2. Remiss (Referral) - Swedish
('system', 'Remiss', 'sv', 'referral',
 '{
   "fields": [
     {"name": "remissorsak", "label": "Remissorsak", "type": "text", "description": "Anledning till remiss"},
     {"name": "aktuellt", "label": "Aktuellt", "type": "text", "description": "Aktuell sjukdomsbild"},
     {"name": "tidigare_sjukdomar", "label": "Tidigare sjukdomar", "type": "text", "description": "Relevant sjukdomshistorik"},
     {"name": "mediciner", "label": "Mediciner", "type": "list", "description": "Aktuell medicinering"},
     {"name": "status", "label": "Status", "type": "text", "description": "Kliniskt status"},
     {"name": "fragestallning", "label": "Frågeställning", "type": "text", "description": "Klinisk fråga"}
   ]
 }'::jsonb, TRUE, 'json'),

-- 3. SBAR - Swedish
('system', 'SBAR', 'sv', 'sbar',
 '{
   "fields": [
     {"name": "situation", "label": "Situation", "type": "text", "description": "Nuvarande situation"},
     {"name": "bakgrund", "label": "Bakgrund", "type": "text", "description": "Relevant bakgrundsinformation"},
     {"name": "aktuellt_tillstand", "label": "Aktuellt tillstånd", "type": "text", "description": "Patientens aktuella tillstånd"},
     {"name": "rekommendation", "label": "Rekommendation", "type": "text", "description": "Rekommendationer och åtgärder"}
   ]
 }'::jsonb, TRUE, 'json'),

-- English Templates

-- 4. SOAP Note - English
('system', 'SOAP Note', 'en', 'soap',
 '{
   "fields": [
     {"name": "subjective", "label": "Subjective", "type": "text", "description": "Patient history and symptoms"},
     {"name": "objective", "label": "Objective", "type": "text", "description": "Clinical findings and test results"},
     {"name": "assessment", "label": "Assessment", "type": "text", "description": "Clinical assessment and diagnosis"},
     {"name": "plan", "label": "Plan", "type": "text", "description": "Treatment plan and follow-up"}
   ]
 }'::jsonb, TRUE, 'json'),

-- 5. Progress Note - English
('system', 'Progress Note', 'en', 'progress_note',
 '{
   "fields": [
     {"name": "current_status", "label": "Current Status", "type": "text", "description": "Patient current condition"},
     {"name": "changes_since_last", "label": "Changes Since Last Visit", "type": "text", "description": "Changes in condition"},
     {"name": "response_to_treatment", "label": "Response to Treatment", "type": "text", "description": "Treatment efficacy"},
     {"name": "plan", "label": "Plan", "type": "text", "description": "Ongoing treatment plan"}
   ]
 }'::jsonb, TRUE, 'json'),

-- 6. Referral Letter - English
('system', 'Referral Letter', 'en', 'referral',
 '{
   "fields": [
     {"name": "reason", "label": "Reason for Referral", "type": "text", "description": "Reason for referral"},
     {"name": "clinical_summary", "label": "Clinical Summary", "type": "text", "description": "Relevant clinical history"},
     {"name": "current_management", "label": "Current Management", "type": "text", "description": "Current treatment"},
     {"name": "question", "label": "Clinical Question", "type": "text", "description": "Specific clinical question"}
   ]
 }'::jsonb, TRUE, 'json'),

-- 7. Consultation Note - English
('system', 'Consultation Note', 'en', 'consultation',
 '{
   "fields": [
     {"name": "reason_for_consultation", "label": "Reason for Consultation", "type": "text", "description": "Why consultation requested"},
     {"name": "history", "label": "History", "type": "text", "description": "Relevant history"},
     {"name": "findings", "label": "Findings", "type": "text", "description": "Clinical findings"},
     {"name": "recommendations", "label": "Recommendations", "type": "text", "description": "Clinical recommendations"}
   ]
 }'::jsonb, TRUE, 'json');

-- Comments for GDPR compliance
COMMENT ON TABLE note_templates IS 'Template structures for clinical note generation - NO PHI STORED';
COMMENT ON TABLE note_generation_metadata IS 'GDPR-compliant metadata about note generation - NO ACTUAL NOTE CONTENT STORED';
COMMENT ON COLUMN note_generation_metadata.context_prompt_hash IS 'SHA256 hash of context prompt for analytics only - original prompt not stored';