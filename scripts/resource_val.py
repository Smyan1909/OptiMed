import asyncio
import os
from pathlib import Path
from typing import List, Tuple
from typing import Any
import json
import time

from optimed.apps.orchestrator.factory import create_app_dependencies
from optimed.core.domain import ChatMessage, ChatRole, PatientContext
from optimed.core.ports import VectorStore, LLMClient
from optimed.embeddings.minilm import embed


# Default questions copied from the notebook
PATIENT_SUMMARY_QUESTIONS: List[str] = [
    "What chronic diagnoses are recorded for the patient?",
    "Which major cardiovascular procedure has the patient undergone, and when?",
    "What was the principal reason for the most recent hospital admission, and what were the admission and discharge dates?",
    "What is the most recent eGFR value (with units) and on what date was it measured?",
    "What is the highest creatinine documented during the recent admission (with units) and on what date?",
    "What is the latest HbA1c value (with units) and its measurement date?",
    "Provide the ED triage vital signs: blood pressure, heart rate, respiratory rate, and oxygen saturation (include units and time).",
    "What is the conclusion of the most recent chest radiograph?",
    "Is an enlarged ascending aorta documented? If yes, provide the size and the imaging date.",
    "List the patient’s current medications with their doses and frequencies.",
    "Does the patient have any medication allergies? Specify the allergen and reaction.",
    "What is the patient’s smoking status and cumulative pack-years?",
    "Which immunizations are documented for the patient in this record?",
    "Summarize the current care plan and any follow-up recommendations.",
    "What is the patient’s MRC Dyspnea grade, and is the patient interested in smoking cessation?",
    "Does the family history include premature myocardial infarction? If yes, who and at what age?",
    "List all encounters recorded in this case with their care setting (emergency, inpatient, ambulatory) and start/end dates.",
    "Is a diagnosis of stroke or cerebrovascular accident (CVA) documented?",
    "Is there any documented allergy to sulfonamide (‘sulfa’) medications?",
]


async def resolve_patients(engine_deps, base_patient_name: str, count: int) -> List[object]:
    engine, fhir_repo, *_ = engine_deps
    patients: List[object] = []
    for i in range(count):
        name = f"{base_patient_name}_{i} StudyCase"
        try:
            search = await fhir_repo.search_patients(name)
            if not search:
                print(f"No patient found for name: {name}")
                continue
            patient_id = search[0].patient_id
            ptcx = await fhir_repo.get_patient(patient_id)
            patients.append(ptcx)
            print(f"Added patient: {ptcx.name}")
        except Exception as e:
            print(f"Failed to add patient '{name}': {e}")
    return patients




async def intelligent_retrieve_chunks(patient_ctx: PatientContext, user_prompt: str, vector_store: VectorStore, journal_client: LLMClient) -> list[str]:
            """Intelligently retrieve and filter chunks based on LLM analysis with recency-aware filtering."""
            
           
            q_vec = await embed(user_prompt, "query")
            rows = await vector_store.similarity_search(
                q_vec,
                top_k=20,  # Increased to accommodate recency filtering
                filter_={
                    "namespace": "clinical", 
                    "patient_id": str(patient_ctx.patient_id)
                },
            )
            

            if not rows and patient_ctx:
                # Fallback to patient context
                retrieved_chunks = [patient_ctx.model_dump_json(indent=2)]
            # Step 2: Apply recency-based filtering and prepare chunks
            current_time = time.time() * 1000  # Current time in milliseconds
            candidate_chunks = []
            
            # Define recency thresholds for different data types (in milliseconds)
            # Only vitals, labs, and medications have time-based filtering
            recency_thresholds = {
                "vitals": 7 * 24 * 60 * 60 * 1000,        # 7 days - vitals change frequently
                "labs": 14 * 24 * 60 * 60 * 1000,         # 14 days - lab values change regularly
                "medications": 90 * 24 * 60 * 60 * 1000,   # 90 days - medication changes less frequent
                "journal_entry": float('inf'),              # Always relevant - clinical notes don't expire
                "demographics": float('inf'),               # Always relevant
                "allergies": float('inf'),                  # Always relevant
                "family_history": float('inf'),             # Always relevant
                "immunizations": float('inf'),              # Always relevant
                "complete_context": float('inf'),           # Always relevant as fallback
                "unknown": float('inf')                     # Default to always relevant for unknown types
            }
            
            for i, row in enumerate(rows):
                    # rows are (id, similarity, content)
                    chunk_text = row[2] if len(row) > 2 else row[1]
                    similarity_score = row[1] if len(row) > 1 else 0.0
                    
                    # Extract metadata if available (for data type identification)
                    metadata: dict[str, Any] = row[3] if len(row) > 3 else {}
                    data_type = metadata.get("data_type", "unknown") if isinstance(metadata, dict) else "unknown"
                    
                    # Get timestamp for recency evaluation
                    timestamp_str = metadata.get("timestamp") if isinstance(metadata, dict) else None
                    chunk_timestamp = None
                    is_recent = True  # Default to True for chunks without timestamps
                    days_old = None
                    
                    if timestamp_str:
                        try:
                            chunk_timestamp = int(timestamp_str)
                            time_diff = current_time - chunk_timestamp
                            threshold = recency_thresholds.get(data_type, recency_thresholds["unknown"])
                            is_recent = time_diff <= threshold
                            days_old = time_diff / (24 * 60 * 60 * 1000)
                            
                        except (ValueError, TypeError):
                            is_recent = True  # Default to including if timestamp parsing fails
                    
                    # Apply recency filter - skip old time-sensitive data
                    if not is_recent:
                        continue
                    
                    # Verify patient relevance
                    if patient_ctx:
                        patient_name = patient_ctx.name
                        if str(patient_ctx.patient_id) in chunk_text or patient_name in chunk_text:
                            
                            # Calculate recency-adjusted similarity score
                            adjusted_score = similarity_score
                            if chunk_timestamp and data_type in ["vitals", "labs", "medications"]:
                                # Boost score for more recent time-sensitive data (only for vitals, labs, medications)
                                time_diff = current_time - chunk_timestamp
                                threshold = recency_thresholds.get(data_type, recency_thresholds["unknown"])
                                if threshold != float('inf') and time_diff < threshold:
                                    # Apply recency boost: more recent = higher boost
                                    recency_factor = 1.0 + (0.3 * (1.0 - time_diff / threshold))
                                    adjusted_score = similarity_score * recency_factor # type: ignore
                            
                            candidate_chunks.append({
                                "id": f"chunk_{i}",
                                "content": chunk_text[:600],  # Increased limit for journal entries
                                "similarity_score": similarity_score,
                                "adjusted_score": adjusted_score,
                                "full_content": chunk_text,
                                "data_type": data_type,
                                "metadata": metadata,
                                "timestamp": chunk_timestamp,
                                "is_recent": is_recent,
                                "days_old": days_old
                            })
                        

            if not candidate_chunks:
                retrieved_chunks = []

            # Step 3: Simplified LLM-based chunk analysis
            chunk_analysis_prompt = f"""
            You are analyzing medical data chunks to determine which ones are relevant for answering this query:

            QUERY: "{user_prompt}"
            
            PATIENT CONTEXT: {patient_ctx.name if patient_ctx else "Unknown"} (ID: {patient_ctx.patient_id})
            
            AVAILABLE CHUNKS (including demographics, vitals, labs, and journal entries):
            {chr(10).join([f"CHUNK {chunk['id']} ({chunk.get('data_type', 'unknown')}): {chunk['content'][:400]}..." for chunk in candidate_chunks])}

            For each chunk, analyze:
            1. Relevance to the specific query (0-10 scale)
            2. Clinical importance for this case (0-10 scale)  
            3. Whether it contains information that directly helps answer the query
            4. Whether it provides necessary context or background

            CHUNK TYPES AVAILABLE:
            - demographics: Basic patient information
            - vitals: Current vital signs and measurements (recent values prioritized)
            - labs: Laboratory test results (recent values prioritized)
            - medications: Current medication regimen (recent changes prioritized)
            - journal_entry: Clinical notes, observations, treatments, diagnoses, assessments, and care plans
            - complete_context: Full patient overview

            Return a JSON response with:
            {{
                "selected_chunks": ["chunk_1", "chunk_3", ...],
                "reasoning": "Brief explanation of why these chunks were selected",
                "relevance_analysis": {{
                    "chunk_1": {{"relevance": 8, "importance": 7, "reason": "Contains recent clinical assessment"}},
                    "chunk_2": {{"relevance": 3, "importance": 4, "reason": "General background, not specific to query"}},
                    ...
                }},
                "query_type": "diagnostic|follow_up|general_inquiry|medication|test_results|care_planning|clinical_notes"
            }}

            RULES:
            - Select 3-6 most relevant chunks maximum
            - For vitals, labs, medications: Recent values are automatically prioritized
            - Journal entries are always relevant regardless of age
            - Always include patient demographics for context
            - For diagnostic queries, include recent journal entries, symptoms, vitals, and test results
            - For medication queries, focus on current medications, allergies, and relevant journal notes
            - For follow-up queries, include previous treatments/outcomes from journal entries
            - For care planning, prioritize recent assessments and treatment notes
            """

            try:
                analysis_response = await journal_client.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information analyst. Analyze and select the most relevant data chunks for clinical queries."),
                    ChatMessage(role=ChatRole.USER, content=chunk_analysis_prompt)
                ], json_mode=True)

                if not analysis_response or not analysis_response.content:
                    raise ValueError("Empty response from LLM")

                # Strip whitespace and check if content is empty
                response_content = analysis_response.content.strip()
                if not response_content:
                    raise ValueError("Empty content in response")

                # Remove markdown code block markers if present
                if response_content.startswith("```json"):
                    start_idx = response_content.find('\n') + 1
                    end_idx = response_content.rfind("```")
                    if start_idx > 0 and end_idx > start_idx:
                        response_content = response_content[start_idx:end_idx].strip()
                elif response_content.startswith("```"):
                    start_idx = response_content.find('\n') + 1
                    end_idx = response_content.rfind("```")
                    if start_idx > 0 and end_idx > start_idx:
                        response_content = response_content[start_idx:end_idx].strip()

                analysis_data = json.loads(response_content)
                
                # Extract selected chunks
                selected_chunk_ids = analysis_data.get("selected_chunks", [])
                selected_chunks = []
                
                for chunk in candidate_chunks:
                    if chunk["id"] in selected_chunk_ids:
                        selected_chunks.append(chunk["full_content"])

                retrieved_chunks = selected_chunks

            except Exception as e:
                # Fallback to top similarity scores, but prioritize journal entries and recent data
                journal_chunks = [chunk for chunk in candidate_chunks if chunk.get("data_type") == "journal_entry"]
                recent_time_sensitive = [chunk for chunk in candidate_chunks if chunk.get("data_type") in ["vitals", "labs", "medications"] and chunk.get("is_recent", True)]
                other_chunks = [chunk for chunk in candidate_chunks if chunk.get("data_type") not in ["journal_entry", "vitals", "labs", "medications"]]
                
                # Take top chunks from each category
                top_journal = sorted(journal_chunks, key=lambda x: x["similarity_score"], reverse=True)[:2]
                top_recent = sorted(recent_time_sensitive, key=lambda x: x.get("adjusted_score", x["similarity_score"]), reverse=True)[:2]
                top_other = sorted(other_chunks, key=lambda x: x["similarity_score"], reverse=True)[:2]
                
                fallback_chunks = top_journal + top_recent + top_other
                retrieved_chunks = [chunk["full_content"] for chunk in fallback_chunks]

            return retrieved_chunks

async def run_evaluation(engine_deps, vector_store, client, questions: List[str], patients: List[object], out_dir: Path) -> Tuple[Path, Path]:
    engine, *_ = engine_deps

    responses_path = out_dir / "responses.txt"
    skipped_path = out_dir / "skipped_cases.tsv"
    retrieved_context_path = out_dir / "retrieved_context.tsv"

    responses: List[str] = []
    skipped_rows: List[str] = ["patient_id\tquestion\terror"]
    retrieved_context_rows: List[str] = ["patient_id\tquestion\tretrieved_context"]

    for question in questions:
        for patient in patients:
            try:
                output = await engine.run(
                    patient=patient,
                    user_prompt=question,
                    chat_mode=False,
                    user_id="validation_user",
                    session_id=f"validation_session_{patient.patient_id}",
                )
                responses.append(str(output.get("final_response", "")))
                retrieved_context = await intelligent_retrieve_chunks(patient, question, vector_store, client)
                retrieved_context_rows.append(f"{patient.patient_id}\t{question}\t{retrieved_context}")
                print(f"Completed question '{question[:60]}...' for patient {patient.name}")
            except Exception as e:
                skipped_rows.append(f"{patient.patient_id}\t{question}\t{e}")
                print(
                    f"Skipping patient {patient.name} for question '{question[:60]}...': {e}"
                )

    out_dir.mkdir(parents=True, exist_ok=True)
    responses_path.write_text("\n".join(responses), encoding="utf-8")
    skipped_path.write_text("\n".join(skipped_rows), encoding="utf-8")
    retrieved_context_path.write_text("\n".join(retrieved_context_rows), encoding="utf-8")
    print(f"Responses saved to {responses_path}")
    print(f"Skipped details saved to {skipped_path}")
    print(f"Retrieved context saved to {retrieved_context_path}")
    return responses_path, skipped_path, retrieved_context_path


async def main() -> None:
    base_patient_name = os.getenv("RESOURCE_VAL_BASE_NAME", "patname")
    try:
        count = int(os.getenv("RESOURCE_VAL_COUNT", "193"))
    except ValueError:
        count = 193

    output_dir = Path(os.getenv("RESOURCE_VAL_OUTPUT_DIR", "outputs"))

    # Wire dependencies (loads .env implicitly via factory)
    (engine_deps,
    fhir,
    vector_store,
    user_repo,
    connection_repo,
    connection_service,
    create_image_service,
    image_analysis_engine,
    image_generation_service,
    generated_image_repo,
    journal_client,
    web_search_service)  = create_app_dependencies(use_smart=False)
    print("Dependencies wired")

    patients = await resolve_patients(engine_deps, base_patient_name, count)
    print("Patients resolved")
    if not patients:
        print("No patients resolved; exiting.")
        return

    await run_evaluation(engine_deps, vector_store, journal_client, PATIENT_SUMMARY_QUESTIONS, patients, output_dir)

if __name__ == "__main__":
    asyncio.run(main())


