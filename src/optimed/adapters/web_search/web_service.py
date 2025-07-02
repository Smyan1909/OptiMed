import uuid
import time
from typing import List, Optional
import httpx

from optimed.core.ports import WebSearchService, LLMClient
from optimed.core.domain import WebSearchQuery, WebSearchResult, WebSearchResponse
from optimed.core.domain import ChatMessage, ChatRole


class TavilyWebSearchService(WebSearchService):
    """Tavily-based web search implementation."""
    
    def __init__(self, api_key: str, llm_client: LLMClient, base_url: str = "https://api.tavily.com"):
        self.api_key = api_key
        self.base_url = base_url
        self.llm_client = llm_client
        self.client = httpx.AsyncClient()
    
    async def evaluate_search_need(
        self, 
        user_query: str, 
        patient_context: Optional[str] = None,
        chat_history: Optional[List[str]] = None
    ) -> bool:
        """Use LLM to evaluate if web search is needed."""
        
        context_info = ""
        if patient_context:
            context_info += f"\nPatient context available: {patient_context[:200]}..."
        
        if chat_history:
            recent_history = "\n".join(chat_history[-3:])
            context_info += f"\nRecent chat history: {recent_history}"
        
        evaluation_prompt = f"""
        Analyze this medical query to determine if current web search is needed:
        
        Query: "{user_query}"
        {context_info}
        
        Web search should be recommended if:
        - Query asks about recent drug approvals, new treatments, or current guidelines
        - Query needs specific dosing information not in patient context
        - Query asks about rare conditions or cutting-edge research
        - Query needs current safety alerts or contraindications
        - Query specifically requests web search for up-to-date information
        
        Web search is NOT needed if:
        - Query can be answered with patient context alone
        - Query is about general medical knowledge
        - Query is conversational or about basic symptoms
        
        Respond with only "YES" if web search is needed, "NO" if not needed.
        """
        
        try:
            response = await self.llm_client.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information assistant."),
                ChatMessage(role=ChatRole.USER, content=evaluation_prompt)
            ])
            
            return response.content.strip().upper() == "YES"
        except Exception as e:
            print(f"[WebSearch] Error evaluating search need: {e}")
            return False
    
    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        patient_context: Optional[str] = None,
        search_intent: Optional[str] = None
    ) -> WebSearchResponse:
        """Perform web search using Tavily API."""
        
        start_time = time.time()
        query_obj = WebSearchQuery(
            query_id=str(uuid.uuid4()),
            query_text=query,
            search_intent=search_intent or "medical_information"
        )
        
        try:
            # Enhance query for medical context
            enhanced_query = await self._enhance_medical_query(query, patient_context)
            
            # Make Tavily API call
            payload = {
                "api_key": self.api_key,
                "query": enhanced_query,
                "search_depth": "advanced",
                "include_domains": [
                    "pubmed.ncbi.nlm.nih.gov",
                    "uptodate.com", 
                    "medscape.com",
                    "drugs.com",
                    "mayoclinic.org",
                    "who.int",
                    "cdc.gov",
                    "fda.gov"
                ],
                "max_results": max_results
            }
            
            response = await self.client.post(f"{self.base_url}/search", json=payload)
            response.raise_for_status()
            data = response.json()
            
            # Parse results
            results = []
            sources_used = []
            
            for item in data.get("results", []):
                result = WebSearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    relevance_score=item.get("score", 0.0),
                    source_type=self._classify_source(item.get("url", ""))
                )
                results.append(result)
                sources_used.append(item.get("url", ""))
            
            # Generate summary using LLM
            summary = await self._generate_summary(query, results, patient_context)
            
            search_time = int((time.time() - start_time) * 1000)
            
            return WebSearchResponse(
                query=query_obj,
                results=results,
                total_results=len(results),
                search_time_ms=search_time,
                sources_used=sources_used,
                summary=summary
            )
            
        except Exception as e:
            print(f"[WebSearch] Error performing search: {e}")
            return WebSearchResponse(
                query=query_obj,
                results=[],
                total_results=0,
                search_time_ms=int((time.time() - start_time) * 1000),
                summary=f"Web search failed: {str(e)}"
            )
    
    async def _enhance_medical_query(self, query: str, patient_context: Optional[str]) -> str:
        """Enhance query with medical context for better search results."""
        if not patient_context:
            return f"medical {query}"
        
        # Add patient demographics for better context
        return f"medical {query} clinical guidelines treatment"
    
    def _classify_source(self, url: str) -> str:
        """Classify the source type based on URL."""
        if "pubmed" in url:
            return "medical_journal"
        elif "uptodate" in url or "medscape" in url:
            return "clinical_reference"
        elif "drugs.com" in url or "fda.gov" in url:
            return "drug_database"
        elif "cdc.gov" in url or "who.int" in url:
            return "health_authority"
        else:
            return "general"
    
    async def _generate_summary(
        self, 
        query: str, 
        results: List[WebSearchResult], 
        patient_context: Optional[str]
    ) -> str:
        """Generate AI summary of search results."""
        
        if not results:
            return "No relevant search results found."
        
        # Combine top results for summary
        combined_content = "\n".join([
            f"Source: {r.title}\n{r.snippet}\n"
            for r in results[:5]  # Top 5 results
        ])
        
        context_note = ""
        if patient_context:
            context_note = f"\nPatient context: {patient_context[:200]}..."
        
        summary_prompt = f"""
        Summarize these web search results for the medical query: "{query}"
        {context_note}
        
        Search Results:
        {combined_content}
        
        Provide a concise medical summary that:
        1. Directly answers the query
        2. Highlights key clinical information
        3. Notes any important safety considerations
        4. Is appropriate for healthcare professionals
        
        Keep the summary under 200 words and focus on actionable medical information.
        """
        
        try:
            response = await self.llm_client.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information assistant providing clinical summaries."),
                ChatMessage(role=ChatRole.USER, content=summary_prompt)
            ])
            
            return response.content
        except Exception as e:
            print(f"[WebSearch] Error generating summary: {e}")
            return "Summary generation failed, but search results are available above."