import asyncio
import os
from tqdm import tqdm
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.embeddings.minilm import embed
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from dotenv import load_dotenv
import json

load_dotenv()
DSN = os.getenv("PGVECTOR_DSN")

async def process_patient(repo: HAPIFHIRRepository, store: PGVectorAdapter, patient_id: str) -> bool:
    """Process a single patient and return success status."""
    try:
        # Get patient data
        patient = await repo.get_patient(patient_id)
        text = patient.model_dump_json()
        
        # Validate JSON format
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON for patient {patient_id}: {e}")
            return False
        
        # Generate embedding
        embedding = await embed(text)
        
        # Ensure embedding is a list of numbers
        if not isinstance(embedding, (list, tuple)):
            embedding = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
        
        # Prepare data for database
        content_for_db = json.dumps(parsed_json)
        metadata = {"namespace": "clinical"}
        
        # Store in vector database
        await store.upsert(
            embedding_id=f"patient:{patient_id}",
            embedding=embedding,
            object_type="PatientContext",
            object_id=patient_id,
            content=content_for_db,
            metadata=metadata,
        )
        
        print(f"✅ Successfully processed patient {patient_id} (embedding: {len(embedding)} dims)")
        return True
        
    except Exception as e:
        print(f"❌ Error processing patient {patient_id}: {e}")
        return False

async def main():
    """Main function to process multiple patients."""
    repo = HAPIFHIRRepository()
    store = PGVectorAdapter(DSN)
    
    # Known working patient IDs from HAPI FHIR demo server
    patient_ids = [
        "example",
        "pat1",
        "pat2",
        "pat3",
        "pat4",
        "f001",
        "f201",
        "xcda",
        "xds",
        "proband",
        "glossy"
    ]
    
    print(f"🚀 Starting to process {len(patient_ids)} patients...")
    
    successful = 0
    failed = 0
    
    for patient_id in tqdm(patient_ids, desc="Processing patients"):
        success = await process_patient(repo, store, patient_id)
        if success:
            successful += 1
        else:
            failed += 1
    
    print("\n📊 Processing complete:")
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📈 Success rate: {successful / len(patient_ids) * 100:.1f}%")
    
    # Clean up
    await store.close()

if __name__ == "__main__":
    asyncio.run(main())