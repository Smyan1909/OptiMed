import asyncpg
from typing import Optional
import asyncio
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)

class DatabasePoolManager:
    """Singleton connection pool manager for the entire application."""
    
    _instance: Optional['DatabasePoolManager'] = None
    _pool: Optional[asyncpg.Pool] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_pool(self, dsn: str, min_connections: int = 10, max_connections: int = 50) -> asyncpg.Pool:
        """Get or create the shared connection pool."""
        async with self._lock:
            if self._pool is None or self._pool._closed:
                try:
                    self._pool = await asyncpg.create_pool(
                        dsn,
                        min_size=min_connections,
                        max_size=max_connections,
                        command_timeout=30,
                        server_settings={
                            'application_name': 'optimed_app',
                            'jit': 'off'
                        }
                    )
                    logger.info(f"Created shared database connection pool with {min_connections}-{max_connections} connections")
                except Exception as e:
                    log_error(logger, "create_shared_connection_pool", e)
                    raise
            
            return self._pool
    
    async def close(self):
        """Close the shared connection pool."""
        async with self._lock:
            if self._pool and not self._pool._closed:
                await self._pool.close()
                logger.info("Shared database connection pool closed")
                self._pool = None

# Global instance
_pool_manager = DatabasePoolManager()

async def get_shared_pool(dsn: str) -> asyncpg.Pool:
    """Get the shared database pool."""
    return await _pool_manager.get_pool(dsn)

async def close_shared_pool():
    """Close the shared database pool."""
    await _pool_manager.close()