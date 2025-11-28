"""
Streaming status messages for real-time updates during clinical information retrieval.

This module provides language-agnostic status messages for all streaming steps,
supporting both English and Swedish. Messages are designed to be:
- Conversational and clear
- Action-oriented (present continuous tense)
- Contextual with relevant details
- Concise and jargon-free

GDPR-compliant: No PHI included in raw messages. Use sanitization functions
for any patient/user identifiers included via formatting.
"""

from typing import Any


STREAMING_MESSAGES = {
    "en": {
        "prepare_context": {
            "starting": "Preparing context...",
            "in_progress": "Setting up language and system instructions...",
            "completed": "Context prepared"
        },
        # Loading and fetching
        "load_user_context": {
            "starting": "Loading your profile...",
            "completed": "Profile loaded: {user_name} ({user_role})",
            "completed_anonymous": "Continuing as anonymous user"
        },
        "fetch_patient": {
            "starting": "Retrieving patient records...",
            "completed": "Loaded patient: {patient_name}, {patient_age} years, {patient_sex}",
            "failed": "Could not retrieve patient data"
        },
        "fetch_pdfs": {
            "starting": "Loading PDF documents...",
            "completed": "Loaded {count} PDF document(s)",
            "failed": "No PDF documents available"
        },
        "fetch_xmls": {
            "starting": "Loading XML documents...",
            "completed": "Loaded {count} XML document(s)",
            "failed": "No XML documents available"
        },

        # Storage operations
        "store_patient_chunks": {
            "starting": "Organizing patient information...",
            "completed": "Organized patient data (demographics, vitals, labs, notes)"
        },

        # Intelligent retrieval
        "intelligent_retrieve_chunks": {
            "starting": "Searching clinical records for: \"{query}\"",
            "completed": "Found {chunk_count} relevant items from {total_processed} records",
            "completed_with_reasoning": "Found {chunk_count} relevant items. {reasoning}",
            "refining": "Refining search (attempt {attempt}) with {query_count} new queries...",
            "refining_with_reason": "Insufficient results found: {reason}... Refining search strategy (attempt {attempt}/{max_attempts})...",
            "retrieval": "Retrieving relevant information from records...",
            "processing": "Processing journal information..."
        },

        # Evaluation steps
        "evaluate_web_search_need": {
            "starting": "Checking if latest medical literature is needed...",
            "completed_needed": "Will search latest medical literature",
            "completed_not_needed": "Sufficient information available locally"
        },
        "perform_web_search": {
            "starting": "Searching medical literature for: \"{query}\"",
            "completed": "Found {count} relevant medical sources",
            "failed": "No relevant sources found"
        },
        "evaluate_image_generation_need": {
            "starting": "Checking if visual illustration would help...",
            "completed_needed": "Will generate medical illustration",
            "completed_not_needed": "Visual illustration not needed"
        },
        "generate_image": {
            "starting": "Creating medical illustration...",
            "completed": "Generated medical illustration",
            "failed": "Could not generate illustration"
        },
        "evaluate_query_complexity": {
            "starting": "Analyzing your question...",
            "completed_full": "Question requires detailed analysis",
            "completed_simple": "Question can be answered directly"
        },
        "evaluate_icd_parsing_need": {
            "starting": "Checking if differential diagnoses are needed...",
            "completed_needed": "Will generate differential diagnoses",
            "completed_not_needed": "Differential diagnoses not needed"
        },

        # History and session
        "load_current_session_history": {
            "starting": "Loading conversation history...",
            "completed": "Loaded {count} previous messages"
        },
        "load_history": {
            "starting": "Loading conversation history...",
            "in_progress": "Loading {count} previous messages from session...",
            "completed": "Loaded {count} previous messages"
        },
        "evaluate_cross_session_history_need": {
            "starting": "Checking if previous conversations are relevant...",
            "completed_needed": "Will search previous conversations",
            "completed_not_needed": "Current context is sufficient"
        },
        "search_cross_session_history": {
            "starting": "Searching previous conversations...",
            "completed": "Found {count} relevant messages from past sessions"
        },

        # Analysis and diagnosis
        "diagnose": {
            "starting": "Analyzing clinical information...",
            "completed": "Analysis complete"
        },
        "parse_icd": {
            "starting": "Computing differential diagnoses using Bayesian analysis...",
            "completed": "Generated {count} differential diagnoses: {diagnoses}",
            "completed_none": "No differential diagnoses generated"
        },

        # Storage operations
        "store_user_message": {
            "starting": "Saving your message...",
            "completed": "Message saved to history"
        },
        "store_assistant_response": {
            "starting": "Saving response...",
            "completed": "Response saved to history",
            "completed_with_reasoning": "Response saved with reasoning",
            "completed_with_image": "Response saved with image"
        },

        # SBAR flow
        "sbar_parallel_dispatcher": {
            "starting": "Generating all 4 SBAR components in parallel (Situation, Background, Assessment, Recommendation)...",
            "completed": "SBAR components ready"
        },
        "retrieve_situation_chunks": {
            "starting": "Gathering current situation data...",
            "completed": "Situation data retrieved"
        },
        "retrieve_background_chunks": {
            "starting": "Gathering patient background...",
            "completed": "Background information retrieved"
        },
        "retrieve_assessment_chunks": {
            "starting": "Gathering assessment data...",
            "completed": "Assessment data retrieved"
        },
        "retrieve_recommendation_chunks": {
            "starting": "Gathering recommendation context...",
            "completed": "Recommendation context retrieved"
        },
        "generate_sbar_situation": {
            "starting": "Analyzing current situation...",
            "completed": "Situation analysis complete"
        },
        "generate_sbar_background": {
            "starting": "Analyzing patient background...",
            "completed": "Background analysis complete"
        },
        "generate_sbar_assessment": {
            "starting": "Generating clinical assessment...",
            "completed": "Assessment generated"
        },
        "generate_sbar_recommendation": {
            "starting": "Generating recommendations...",
            "completed": "Recommendations generated"
        },
        "merge_sbar_results": {
            "starting": "Formatting SBAR summary...",
            "completed": "SBAR summary ready"
        },

        # General summary flow
        "general_summary_parallel_dispatcher": {
            "starting": "Generating all summary components in parallel (Snapshot, Problems, Medications, Trends, History, Risks, Encounters, Deep-dive)...",
            "completed": "Summary components ready"
        },
        "retrieve_snapshot_chunks": {
            "starting": "Gathering current snapshot data...",
            "completed": "Snapshot data retrieved"
        },
        "retrieve_problems_chunks": {
            "starting": "Gathering problem list...",
            "completed": "Problem list retrieved"
        },
        "retrieve_medications_chunks": {
            "starting": "Gathering medication data...",
            "completed": "Medication information retrieved"
        },
        "retrieve_trends_chunks": {
            "starting": "Analyzing clinical trends...",
            "completed": "Trend analysis complete"
        },
        "retrieve_history_chunks": {
            "starting": "Gathering medical history...",
            "completed": "Medical history retrieved"
        },
        "retrieve_risks_chunks": {
            "starting": "Analyzing risk factors...",
            "completed": "Risk analysis complete"
        },
        "retrieve_encounters_chunks": {
            "starting": "Gathering encounter history...",
            "completed": "Encounter history retrieved"
        },
        "retrieve_deepdive_chunks": {
            "starting": "Performing deep analysis...",
            "completed": "Deep analysis complete"
        },
        "generate_snapshot_summary": {
            "starting": "Creating current snapshot...",
            "completed": "Snapshot summary generated"
        },
        "generate_problems_summary": {
            "starting": "Summarizing problems...",
            "completed": "Problem summary generated"
        },
        "generate_medications_summary": {
            "starting": "Summarizing medications...",
            "completed": "Medication summary generated"
        },
        "generate_trends_summary": {
            "starting": "Summarizing clinical trends...",
            "completed": "Trend summary generated"
        },
        "generate_history_summary": {
            "starting": "Summarizing medical history...",
            "completed": "History summary generated"
        },
        "generate_risks_summary": {
            "starting": "Summarizing risk factors...",
            "completed": "Risk summary generated"
        },
        "generate_encounters_summary": {
            "starting": "Summarizing encounters...",
            "completed": "Encounter summary generated"
        },
        "generate_deepdive_summary": {
            "starting": "Creating detailed analysis...",
            "completed": "Detailed analysis complete"
        },
        "merge_general_summary_results": {
            "starting": "Formatting comprehensive summary...",
            "completed": "Comprehensive summary ready"
        },

        # Focused summary flow
        "focused_summary_parallel_dispatcher": {
            "starting": "Preparing focused analysis...",
            "completed": "Focused analysis components ready"
        },
        "identify_aspect_and_retrieve": {
            "starting": "Identifying key aspects...",
            "completed": "Key aspects identified"
        },
        "retrieve_focused_diagnoses_chunks": {
            "starting": "Gathering diagnosis information...",
            "completed": "Diagnosis information retrieved"
        },
        "generate_diagnoses_section": {
            "starting": "Analyzing diagnoses...",
            "completed": "Diagnosis section generated"
        },
        "retrieve_focused_events_chunks": {
            "starting": "Gathering clinical events...",
            "completed": "Clinical events retrieved"
        },
        "generate_events_section": {
            "starting": "Analyzing clinical events...",
            "completed": "Events section generated"
        },
        "retrieve_focused_medications_chunks": {
            "starting": "Gathering medication details...",
            "completed": "Medication details retrieved"
        },
        "generate_medications_section": {
            "starting": "Analyzing medications...",
            "completed": "Medication section generated"
        },
        "retrieve_focused_objective_data_chunks": {
            "starting": "Gathering objective data...",
            "completed": "Objective data retrieved"
        },
        "generate_objective_data_section": {
            "starting": "Analyzing objective findings...",
            "completed": "Objective data section generated"
        },
        "retrieve_focused_assessment_chunks": {
            "starting": "Gathering assessment data...",
            "completed": "Assessment data retrieved"
        },
        "generate_assessment_section": {
            "starting": "Creating clinical assessment...",
            "completed": "Assessment section generated"
        },
        "retrieve_focused_next_steps_chunks": {
            "starting": "Gathering next steps information...",
            "completed": "Next steps information retrieved"
        },
        "generate_next_steps_section": {
            "starting": "Planning next steps...",
            "completed": "Next steps section generated"
        },
        "merge_focused_summary_results": {
            "starting": "Formatting focused summary...",
            "completed": "Focused summary ready"
        },

        # Timeline flow
        "extract_timeline_events": {
            "starting": "Identifying key medical events...",
            "completed": "Identified {count} timeline events"
        },
        "retrieve_timeline_chunks": {
            "starting": "Retrieving details for all timeline events in parallel...",
            "completed": "Timeline event details retrieved"
        },
        "generate_timeline_bubbles": {
            "starting": "Creating timeline with citations...",
            "completed": "Timeline generated with sources"
        },
        "merge_timeline_results": {
            "starting": "Formatting timeline display...",
            "completed": "Timeline ready"
        },

        # Note generation flow
        "load_note_template": {
            "starting": "Loading {template_type} template...",
            "completed": "Loaded template: {template_name}"
        },
        "generate_note_section": {
            "starting": "Generating note sections...",
            "completed": "Generated {section_count} sections ({char_count} characters)"
        },
        "format_note_response": {
            "starting": "Formatting clinical note...",
            "completed": "Note formatted with {citation_count} citations"
        },
        "store_note_metadata": {
            "starting": "Recording note metadata...",
            "completed": "Metadata stored"
        },

        # Query classification
        "contextualize_query_for_classification": {
            "starting": "Understanding your question...",
            "completed": "Question understood"
        },
        "classify_query_intent": {
            "starting": "Determining best approach...",
            "completed": "Approach determined: {intent}"
        },

        # Information provision
        "provide_information": {
            "starting": "Preparing response...",
            "in_progress": "AI model analyzing information and formulating answer...",
            "completed": "Response ready"
        },
        "process_clinical_data": {
            "starting": "Processing clinical data...",
            "in_progress": "Analyzing {count} relevant clinical records...",
            "completed": "Clinical data processed"
        },
        "integrate_web_sources": {
            "starting": "Integrating web sources...",
            "in_progress": "Including {count} external medical sources...",
            "completed": "Web sources integrated"
        },
        # Aliases for step names with spaces (normalized to lowercase)
        "processing clinical data": {
            "starting": "Processing clinical data...",
            "in_progress": "Analyzing {count} relevant clinical records...",
            "completed": "Clinical data processed"
        },
        "integrating web sources": {
            "starting": "Integrating web sources...",
            "in_progress": "Including {count} external medical sources...",
            "completed": "Web sources integrated"
        },
        "generating response": {
            "starting": "Preparing response...",
            "in_progress": "AI model analyzing information and formulating answer...",
            "completed": "Response ready"
        },

        # Default/fallback
        "default": {
            "starting": "Processing...",
            "completed": "Step complete"
        }
    },

    "sv": {
        "prepare_context": {
            "starting": "Förbereder kontext...",
            "in_progress": "Sätter upp språk och systeminstruktioner...",
            "completed": "Kontext förberedd"
        },
        # Loading and fetching
        "load_user_context": {
            "starting": "Laddar din profil...",
            "completed": "Profil laddad: {user_name} ({user_role})",
            "completed_anonymous": "Fortsätter som anonym användare"
        },
        "fetch_patient": {
            "starting": "Hämtar patientjournaler...",
            "completed": "Laddade patient: {patient_name}, {patient_age} år, {patient_sex}",
            "failed": "Kunde inte hämta patientdata"
        },
        "fetch_pdfs": {
            "starting": "Laddar PDF-dokument...",
            "completed": "Laddade {count} PDF-dokument",
            "failed": "Inga PDF-dokument tillgängliga"
        },
        "fetch_xmls": {
            "starting": "Laddar XML-dokument...",
            "completed": "Laddade {count} XML-dokument",
            "failed": "Inga XML-dokument tillgängliga"
        },

        # Storage operations
        "store_patient_chunks": {
            "starting": "Organiserar patientinformation...",
            "completed": "Organiserade patientdata (demografi, vitalparametrar, labbsvar, anteckningar)"
        },

        # Intelligent retrieval
        "intelligent_retrieve_chunks": {
            "starting": "Söker i kliniska journaler efter: \"{query}\"",
            "completed": "Hittade {chunk_count} relevanta poster från {total_processed} journaler",
            "completed_with_reasoning": "Hittade {chunk_count} relevanta poster. {reasoning}",
            "refining": "Förfinar sökning (försök {attempt}) med {query_count} nya frågor...",
            "refining_with_reason": "Otillräckliga resultat: {reason}... Förfinar sökstrategi (försök {attempt}/{max_attempts})...",
            "retrieval": "Letar efter relevant information från journaler...",
            "processing": "Behandlar journaldata..."
        },

        # Evaluation steps
        "evaluate_web_search_need": {
            "starting": "Kontrollerar om senaste medicinska litteratur behövs...",
            "completed_needed": "Kommer söka senaste medicinska litteratur",
            "completed_not_needed": "Tillräcklig information finns lokalt"
        },
        "perform_web_search": {
            "starting": "Söker medicinsk litteratur för: \"{query}\"",
            "completed": "Hittade {count} relevanta medicinska källor",
            "failed": "Inga relevanta källor hittades"
        },
        "evaluate_image_generation_need": {
            "starting": "Kontrollerar om visuell illustration behövs...",
            "completed_needed": "Kommer generera medicinsk illustration",
            "completed_not_needed": "Visuell illustration behövs inte"
        },
        "generate_image": {
            "starting": "Skapar medicinsk illustration...",
            "completed": "Genererade medicinsk illustration",
            "failed": "Kunde inte generera illustration"
        },
        "evaluate_query_complexity": {
            "starting": "Analyserar din fråga...",
            "completed_full": "Frågan kräver detaljerad analys",
            "completed_simple": "Frågan kan besvaras direkt"
        },
        "evaluate_icd_parsing_need": {
            "starting": "Kontrollerar om differentialdiagnoser behövs...",
            "completed_needed": "Kommer generera differentialdiagnoser",
            "completed_not_needed": "Differentialdiagnoser behövs inte"
        },

        # History and session
        "load_current_session_history": {
            "starting": "Laddar konversationshistorik...",
            "completed": "Laddade {count} tidigare meddelanden"
        },
        "load_history": {
            "starting": "Laddar konversationshistorik...",
            "in_progress": "Laddar {count} tidigare meddelanden från sessionen...",
            "completed": "Laddade {count} tidigare meddelanden"
        },
        "evaluate_cross_session_history_need": {
            "starting": "Kontrollerar om tidigare konversationer är relevanta...",
            "completed_needed": "Kommer söka i tidigare konversationer",
            "completed_not_needed": "Nuvarande kontext är tillräcklig"
        },
        "search_cross_session_history": {
            "starting": "Söker i tidigare konversationer...",
            "completed": "Hittade {count} relevanta meddelanden från tidigare sessioner"
        },

        # Analysis and diagnosis
        "diagnose": {
            "starting": "Analyserar klinisk information...",
            "completed": "Analys klar"
        },
        "parse_icd": {
            "starting": "Beräknar differentialdiagnoser med Bayesiansk analys...",
            "completed": "Genererade {count} differentialdiagnoser: {diagnoses}",
            "completed_none": "Inga differentialdiagnoser genererade"
        },

        # Storage operations
        "store_user_message": {
            "starting": "Sparar ditt meddelande...",
            "completed": "Meddelande sparat i historik"
        },
        "store_assistant_response": {
            "starting": "Sparar svar...",
            "completed": "Svar sparat i historik",
            "completed_with_reasoning": "Svar sparat med resonemang",
            "completed_with_image": "Svar sparat med bild"
        },

        # SBAR flow
        "sbar_parallel_dispatcher": {
            "starting": "Genererar alla 4 SBAR-komponenter parallellt (Situation, Bakgrund, Bedömning, Rekommendation)...",
            "completed": "SBAR-komponenter klara"
        },
        "retrieve_situation_chunks": {
            "starting": "Samlar aktuell situationsdata...",
            "completed": "Situationsdata hämtad"
        },
        "retrieve_background_chunks": {
            "starting": "Samlar patientens bakgrund...",
            "completed": "Bakgrundsinformation hämtad"
        },
        "retrieve_assessment_chunks": {
            "starting": "Samlar bedömningsdata...",
            "completed": "Bedömningsdata hämtad"
        },
        "retrieve_recommendation_chunks": {
            "starting": "Samlar rekommendationskontext...",
            "completed": "Rekommendationskontext hämtad"
        },
        "generate_sbar_situation": {
            "starting": "Analyserar aktuell situation...",
            "completed": "Situationsanalys klar"
        },
        "generate_sbar_background": {
            "starting": "Analyserar patientbakgrund...",
            "completed": "Bakgrundsanalys klar"
        },
        "generate_sbar_assessment": {
            "starting": "Genererar klinisk bedömning...",
            "completed": "Bedömning genererad"
        },
        "generate_sbar_recommendation": {
            "starting": "Genererar rekommendationer...",
            "completed": "Rekommendationer genererade"
        },
        "merge_sbar_results": {
            "starting": "Formaterar SBAR-sammanfattning...",
            "completed": "SBAR-sammanfattning klar"
        },

        # General summary flow
        "general_summary_parallel_dispatcher": {
            "starting": "Genererar alla sammanfattningskomponenter parallellt (Snapshot, Problem, Läkemedel, Trender, Historia, Risker, Vårdkontakter, Djupanalys)...",
            "completed": "Sammanfattningskomponenter klara"
        },
        "retrieve_snapshot_chunks": {
            "starting": "Samlar aktuell snapshot-data...",
            "completed": "Snapshot-data hämtad"
        },
        "retrieve_problems_chunks": {
            "starting": "Samlar problemlista...",
            "completed": "Problemlista hämtad"
        },
        "retrieve_medications_chunks": {
            "starting": "Samlar läkemedelsdata...",
            "completed": "Läkemedelsinformation hämtad"
        },
        "retrieve_trends_chunks": {
            "starting": "Analyserar kliniska trender...",
            "completed": "Trendanalys klar"
        },
        "retrieve_history_chunks": {
            "starting": "Samlar sjukdomshistoria...",
            "completed": "Sjukdomshistoria hämtad"
        },
        "retrieve_risks_chunks": {
            "starting": "Analyserar riskfaktorer...",
            "completed": "Riskanalys klar"
        },
        "retrieve_encounters_chunks": {
            "starting": "Samlar vårdkontakthistorik...",
            "completed": "Vårdkontakthistorik hämtad"
        },
        "retrieve_deepdive_chunks": {
            "starting": "Utför djupanalys...",
            "completed": "Djupanalys klar"
        },
        "generate_snapshot_summary": {
            "starting": "Skapar aktuell snapshot...",
            "completed": "Snapshot-sammanfattning genererad"
        },
        "generate_problems_summary": {
            "starting": "Sammanfattar problem...",
            "completed": "Problemsammanfattning genererad"
        },
        "generate_medications_summary": {
            "starting": "Sammanfattar läkemedel...",
            "completed": "Läkemedelssammanfattning genererad"
        },
        "generate_trends_summary": {
            "starting": "Sammanfattar kliniska trender...",
            "completed": "Trendsammanfattning genererad"
        },
        "generate_history_summary": {
            "starting": "Sammanfattar sjukdomshistoria...",
            "completed": "Historiksammanfattning genererad"
        },
        "generate_risks_summary": {
            "starting": "Sammanfattar riskfaktorer...",
            "completed": "Risksammanfattning genererad"
        },
        "generate_encounters_summary": {
            "starting": "Sammanfattar vårdkontakter...",
            "completed": "Vårdkontaktsammanfattning genererad"
        },
        "generate_deepdive_summary": {
            "starting": "Skapar detaljerad analys...",
            "completed": "Detaljerad analys klar"
        },
        "merge_general_summary_results": {
            "starting": "Formaterar omfattande sammanfattning...",
            "completed": "Omfattande sammanfattning klar"
        },

        # Focused summary flow
        "focused_summary_parallel_dispatcher": {
            "starting": "Förbereder fokuserad analys...",
            "completed": "Fokuserade analyskomponenter klara"
        },
        "identify_aspect_and_retrieve": {
            "starting": "Identifierar nyckelaspekter...",
            "completed": "Nyckelaspekter identifierade"
        },
        "retrieve_focused_diagnoses_chunks": {
            "starting": "Samlar diagnosinformation...",
            "completed": "Diagnosinformation hämtad"
        },
        "generate_diagnoses_section": {
            "starting": "Analyserar diagnoser...",
            "completed": "Diagnossektion genererad"
        },
        "retrieve_focused_events_chunks": {
            "starting": "Samlar kliniska händelser...",
            "completed": "Kliniska händelser hämtade"
        },
        "generate_events_section": {
            "starting": "Analyserar kliniska händelser...",
            "completed": "Händelsesektion genererad"
        },
        "retrieve_focused_medications_chunks": {
            "starting": "Samlar läkemedelsdetaljer...",
            "completed": "Läkemedelsdetaljer hämtade"
        },
        "generate_medications_section": {
            "starting": "Analyserar läkemedel...",
            "completed": "Läkemedelssektion genererad"
        },
        "retrieve_focused_objective_data_chunks": {
            "starting": "Samlar objektiva data...",
            "completed": "Objektiva data hämtade"
        },
        "generate_objective_data_section": {
            "starting": "Analyserar objektiva fynd...",
            "completed": "Objektiv datasektion genererad"
        },
        "retrieve_focused_assessment_chunks": {
            "starting": "Samlar bedömningsdata...",
            "completed": "Bedömningsdata hämtad"
        },
        "generate_assessment_section": {
            "starting": "Skapar klinisk bedömning...",
            "completed": "Bedömningssektion genererad"
        },
        "retrieve_focused_next_steps_chunks": {
            "starting": "Samlar information om nästa steg...",
            "completed": "Information om nästa steg hämtad"
        },
        "generate_next_steps_section": {
            "starting": "Planerar nästa steg...",
            "completed": "Nästa steg-sektion genererad"
        },
        "merge_focused_summary_results": {
            "starting": "Formaterar fokuserad sammanfattning...",
            "completed": "Fokuserad sammanfattning klar"
        },

        # Timeline flow
        "extract_timeline_events": {
            "starting": "Identifierar viktiga medicinska händelser...",
            "completed": "Identifierade {count} tidslinjehändelser"
        },
        "retrieve_timeline_chunks": {
            "starting": "Hämtar detaljer för alla tidslinjehändelser parallellt...",
            "completed": "Tidslinjehändelsedetaljer hämtade"
        },
        "generate_timeline_bubbles": {
            "starting": "Skapar tidslinje med citeringar...",
            "completed": "Tidslinje genererad med källor"
        },
        "merge_timeline_results": {
            "starting": "Formaterar tidslinjevisning...",
            "completed": "Tidslinje klar"
        },

        # Note generation flow
        "load_note_template": {
            "starting": "Laddar {template_type}-mall...",
            "completed": "Laddade mall: {template_name}"
        },
        "generate_note_section": {
            "starting": "Genererar anteckningssektioner...",
            "completed": "Genererade {section_count} sektioner ({char_count} tecken)"
        },
        "format_note_response": {
            "starting": "Formaterar klinisk anteckning...",
            "completed": "Anteckning formaterad med {citation_count} citeringar"
        },
        "store_note_metadata": {
            "starting": "Registrerar anteckningsmetadata...",
            "completed": "Metadata lagrad"
        },

        # Query classification
        "contextualize_query_for_classification": {
            "starting": "Förstår din fråga...",
            "completed": "Fråga förstådd"
        },
        "classify_query_intent": {
            "starting": "Bestämmer bästa tillvägagångssätt...",
            "completed": "Tillvägagångssätt bestämt: {intent}"
        },

        # Information provision
        "provide_information": {
            "starting": "Förbereder svar...",
            "in_progress": "AI-modell analyserar information och formulerar svar...",
            "completed": "Svar klart"
        },
        "process_clinical_data": {
            "starting": "Bearbetar kliniska data...",
            "in_progress": "Analyserar {count} relevanta kliniska journaler...",
            "completed": "Kliniska data bearbetade"
        },
        "integrate_web_sources": {
            "starting": "Integrerar webbkällor...",
            "in_progress": "Inkluderar {count} externa medicinska källor...",
            "completed": "Webbkällor integrerade"
        },
        # Aliases for step names with spaces (normalized to lowercase)
        "processing clinical data": {
            "starting": "Bearbetar kliniska data...",
            "in_progress": "Analyserar {count} relevanta kliniska journaler...",
            "completed": "Kliniska data bearbetade"
        },
        "integrating web sources": {
            "starting": "Integrerar webbkällor...",
            "in_progress": "Inkluderar {count} externa medicinska källor...",
            "completed": "Webbkällor integrerade"
        },
        "generating response": {
            "starting": "Förbereder svar...",
            "in_progress": "AI-modell analyserar information och formulerar svar...",
            "completed": "Svar klart"
        },

        # Default/fallback
        "default": {
            "starting": "Bearbetar...",
            "completed": "Steg klart"
        }
    }
}


def get_message(step_name: str, status: str, language: str = "en", **kwargs: Any) -> str:
    """
    Get a localized streaming message for a given step and status.

    Args:
        step_name: The step identifier (e.g., "fetch_patient", "intelligent_retrieve_chunks")
        status: The status of the step ("starting", "completed", etc.)
        language: Language code ("en" or "sv")
        **kwargs: Additional formatting parameters (e.g., count, query, patient_name)

    Returns:
        Localized message string with formatting applied

    Example:
        >>> get_message("fetch_patient", "completed", "en",
        ...             patient_name="John Doe", patient_age=45, patient_sex="Male")
        "Loaded patient: John Doe, 45 years, Male"
    """
    # Normalize language code
    lang = language.lower()
    if lang not in STREAMING_MESSAGES:
        lang = "en"  # Fallback to English

    # Normalize step name
    step_key = step_name.lower()

    # Get messages for this language
    lang_messages = STREAMING_MESSAGES[lang]

    # Get step messages
    if step_key not in lang_messages:
        # Fallback to default
        step_messages = lang_messages.get("default", {"starting": "Processing...", "completed": "Complete"})
    else:
        step_messages = lang_messages[step_key]

    # Get specific message
    message_template = step_messages.get(status, step_messages.get("starting", "Processing..."))

    # Format with provided kwargs
    try:
        return message_template.format(**kwargs)
    except (KeyError, ValueError):
        # If formatting fails, return unformatted message
        return message_template


def get_step_display_name(step_name: str, language: str = "en") -> str:
    """
    Get a human-readable display name for a step.

    Args:
        step_name: The step identifier
        language: Language code ("en" or "sv")

    Returns:
        Human-readable step name
    """
    # Use the starting message as display name
    return get_message(step_name, "starting", language)
