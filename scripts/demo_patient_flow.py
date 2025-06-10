import asyncio, pprint
from dotenv import load_dotenv


# --------------------------------------------------------------------
# Load env and import the engine
# --------------------------------------------------------------------
load_dotenv()                          # PGVECTOR_DSN, Claude key, etc.

from optimed.apps.orchestrator.patient_flow import (
    LangGraphDiagnosticEngine,
    compiled_graph,
    _fhir,                             # re-use the singleton repo for demo
)

# --------------------------------------------------------------------
# 1️⃣  Streaming demo
# --------------------------------------------------------------------
async def run_stream_demo(patient_id: str):
    engine = LangGraphDiagnosticEngine(
        default_prompt="Provide the most likely diagnosis for this patient"
    )
    patient = await _fhir.get_patient(patient_id)

    print("🔄 streaming updates...\n")
    async for delta in engine.run_stream(patient):
        pprint.pp(delta)

    print("\n✅ stream finished\n")

# --------------------------------------------------------------------
# 2️⃣  Render the graph
# --------------------------------------------------------------------
def draw_graph():
    """Generate and save a visual representation of the workflow graph."""
    try:
        # For LangGraph, use get_graph() and then draw methods
        graph = compiled_graph.get_graph()
        
        # Try different visualization methods
        try:
            # Method 1: Using draw_ascii (simple text representation)
            ascii_repr = graph.draw_ascii()
            print("Graph structure (ASCII):")
            print(ascii_repr)
        except AttributeError:
            print("ASCII drawing not available")
        
        try:
            # Method 2: Using draw_mermaid (Mermaid diagram format)
            mermaid_repr = graph.draw_mermaid()
            print("\nGraph structure (Mermaid):")
            print(mermaid_repr)
            
            # Save to file
            with open("patient_flow_graph.mmd", "w") as f:
                f.write(mermaid_repr)
            print("Mermaid diagram saved to patient_flow_graph.mmd")
            
        except AttributeError:
            print("Mermaid drawing not available")
            
        try:
            # Method 3: Using draw_png (if graphviz is installed)
            png_data = graph.draw_png()
            with open("patient_flow_graph.png", "wb") as f:
                f.write(png_data)
            print("PNG diagram saved to patient_flow_graph.png")
            
        except (AttributeError, ImportError) as e:
            print(f"PNG drawing not available: {e}")
            
    except Exception as e:
        print(f"Error generating graph visualization: {e}")
        # Fallback: Print node and edge information
        print("\nGraph structure (manual):")
        print("Nodes:")
        for node in ["fetch_patient", "retrieve_chunks", "diagnose"]:
            print(f"  - {node}")
        print("Edges:")
        print("  - fetch_patient -> retrieve_chunks")
        print("  - retrieve_chunks -> diagnose") 
        print("  - diagnose -> END")

# --------------------------------------------------------------------
# 3️⃣  CLI entry
# --------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Demo patient flow graph")
    parser.add_argument("--patient", default="example", help="Patient ID to test")
    args = parser.parse_args()

    asyncio.run(run_stream_demo(args.patient))
    draw_graph()