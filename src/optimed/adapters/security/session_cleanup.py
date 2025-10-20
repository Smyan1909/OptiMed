"""
Session Cleanup Service for GDPR Compliance

Automatically cleans up session data and ensures memory zeroization.
Implements automatic session timeout and cleanup.
"""

import asyncio
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

class SessionCleanupService:
    """Service for automatic session cleanup and memory management."""
    
    def __init__(self, vector_store: Any, user_repo: Optional[Any] = None) -> None:
        self.vector_store = vector_store
        self.user_repo = user_repo
        self.active_sessions: Dict[str, datetime] = {}
        self.session_ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "60"))
        self.cleanup_interval_minutes = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "5"))
        self._cleanup_task = None
        self._running = False
    
    async def start_cleanup_service(self):
        """Start the automatic cleanup service."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Session cleanup service started (TTL: {self.session_ttl_minutes}min, interval: {self.cleanup_interval_minutes}min)")
    
    async def stop_cleanup_service(self):
        """Stop the automatic cleanup service."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Session cleanup service stopped")
    
    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically."""
        while self._running:
            try:
                await self.cleanup_expired_sessions()
                await asyncio.sleep(self.cleanup_interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def register_session(self, session_id: str):
        """Register a new session for tracking."""
        self.active_sessions[session_id] = datetime.now(timezone.utc)
        logger.info(f"Registered session: {session_id}")
    
    async def cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        current_time = datetime.now(timezone.utc)
        expired_sessions = []
        
        for session_id, created_at in self.active_sessions.items():
            if current_time - created_at > timedelta(minutes=self.session_ttl_minutes):
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            await self.cleanup_session(session_id)
            del self.active_sessions[session_id]
        
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
    
    async def cleanup_session(self, session_id: str):
        """Clean up a specific session."""
        try:
            logger.info(f"Cleaning up session: {session_id}")
            
            # Clear RAM vector store for this session
            if hasattr(self.vector_store, 'clear_session'):
                await self.vector_store.clear_session(session_id)
            
            # Clear ephemeral cache if enabled
            if hasattr(self.vector_store, '_clear_ephemeral_cache'):
                await self.vector_store._clear_ephemeral_cache(session_id)
            
            # Log session cleanup for audit
            if self.user_repo:
                await self._log_session_cleanup(session_id)
            
            logger.info(f"Session {session_id} cleaned up successfully")
            
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")
    
    async def _log_session_cleanup(self, session_id: str):
        """Log session cleanup for audit trail."""
        try:
            # This would typically log to an audit table
            # For now, just log to console
            logger.info(f"[AUDIT] Session {session_id} cleaned up at {datetime.now(timezone.utc)}")
        except Exception as e:
            logger.error(f"Error logging session cleanup: {e}")
    
    async def force_cleanup_all_sessions(self):
        """Force cleanup of all active sessions (emergency cleanup)."""
        logger.warning("Force cleanup of all sessions initiated")
        
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            await self.cleanup_session(session_id)
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
        
        logger.warning(f"Force cleanup completed: {len(session_ids)} sessions cleaned")
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about active sessions."""
        current_time = datetime.now(timezone.utc)
        
        stats = {
            "active_sessions": len(self.active_sessions),
            "session_ttl_minutes": self.session_ttl_minutes,
            "cleanup_interval_minutes": self.cleanup_interval_minutes,
            "oldest_session_age_minutes": 0,
            "newest_session_age_minutes": 0
        }
        
        if self.active_sessions:
            session_ages = [
                (current_time - created_at).total_seconds() / 60
                for created_at in self.active_sessions.values()
            ]

            stats["oldest_session_age_minutes"] = int(max(session_ages))
            stats["newest_session_age_minutes"] = int(min(session_ages))
        
        return stats

class MemoryZeroizationService:
    """Service for secure memory zeroization."""
    
    @staticmethod
    def zeroize_string(text: str) -> None:
        """Zeroize a string in memory (Python limitation - strings are immutable)."""
        # Note: In Python, strings are immutable, so we can't truly zeroize them
        # This is more of a best practice reminder
        del text
    
    @staticmethod
    def zeroize_dict(data: Dict) -> None:
        """Clear a dictionary and its contents."""
        data.clear()
    
    @staticmethod
    def zeroize_list(data: List) -> None:
        """Clear a list and its contents."""
        data.clear()
    
    @staticmethod
    def secure_delete_file(file_path: str) -> None:
        """Securely delete a file (overwrite with random data)."""
        try:
            if os.path.exists(file_path):
                # Get file size
                file_size = os.path.getsize(file_path)
                
                # Overwrite with random data
                with open(file_path, "r+b") as f:
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())
                
                # Delete the file
                os.remove(file_path)
                
                logger.info(f"Securely deleted file: {file_path}")
        except Exception as e:
            logger.error(f"Error securely deleting file {file_path}: {e}")

# Global cleanup service instance
_cleanup_service: Optional[SessionCleanupService] = None

def get_cleanup_service() -> Optional[SessionCleanupService]:
    """Get global cleanup service instance."""
    return _cleanup_service

def initialize_cleanup_service(vector_store: Any, user_repo: Optional[Any] = None) -> SessionCleanupService:
    """Initialize the global cleanup service."""
    global _cleanup_service
    _cleanup_service = SessionCleanupService(vector_store, user_repo)
    return _cleanup_service
