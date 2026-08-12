import os
import logging
import asyncio
import redis.asyncio as aioredis
from typing import Optional, List, Any, Dict

from src.config.models import AppConfig

logger = logging.getLogger("arl.storage")

class RedisClient:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.client: Optional[aioredis.Redis] = None
        self.pool: Optional[aioredis.ConnectionPool] = None
        
        # Load scripts cache
        self.scripts: Dict[str, Any] = {}
        self.sha_cache: Dict[str, str] = {}
        
        # Register for config updates
        self.config_manager.register_callback(self.on_config_change)

    def on_config_change(self, config: AppConfig):
        # If connection params changed, we could recreate the pool
        # For simplicity, we just initialize on startup or if config tells us
        pass

    async def initialize(self):
        config = self.config_manager.get_config()
        redis_cfg = config.redis
        
        logger.info(f"Initializing Redis client connecting to {redis_cfg.host}:{redis_cfg.port}/{redis_cfg.db}")
        
        self.pool = aioredis.ConnectionPool(
            host=redis_cfg.host,
            port=redis_cfg.port,
            db=redis_cfg.db,
            max_connections=redis_cfg.pool_size,
            decode_responses=True # We want decoded string responses for scripts
        )
        self.client = aioredis.Redis(connection_pool=self.pool)
        
        # Test connection
        try:
            await self.client.ping()
            logger.info("Successfully connected to Redis.")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis on initialization: {e}. Running in degraded mode.")
            
        await self._load_lua_scripts()

    async def _load_lua_scripts(self):
        script_dir = os.path.join(os.path.dirname(__file__), "lua_scripts")
        if not os.path.exists(script_dir):
            logger.warning(f"Lua scripts directory not found at {script_dir}")
            return
            
        for file in os.listdir(script_dir):
            if file.endswith(".lua"):
                name = file[:-4]
                path = os.path.join(script_dir, file)
                try:
                    with open(path, "r") as f:
                        script_content = f.read()
                    
                    self.scripts[name] = script_content
                    # If connected, register script
                    if self.client:
                        try:
                            sha = await self.client.script_load(script_content)
                            self.sha_cache[name] = sha
                            logger.info(f"Loaded Lua script '{name}' into Redis with SHA {sha}")
                        except Exception as e:
                            logger.warning(f"Could not load Lua script '{name}' SHA into Redis: {e}")
                except Exception as e:
                    logger.exception(f"Failed to read/load Lua script '{name}': {e}")

    async def run_script(self, name: str, keys: List[str], args: List[Any]) -> Optional[Any]:
        if not self.client:
            logger.error("Redis client is not initialized.")
            return None
            
        sha = self.sha_cache.get(name)
        try:
            if sha:
                # Fast path: run using SHA
                try:
                    return await self.client.evalsha(sha, len(keys), *keys, *args)
                except aioredis.exceptions.NoScriptError:
                    # Script was evicted, reload and run
                    script_content = self.scripts.get(name)
                    if script_content:
                        sha = await self.client.script_load(script_content)
                        self.sha_cache[name] = sha
                        return await self.client.evalsha(sha, len(keys), *keys, *args)
            
            # Slow path or fallback
            script_content = self.scripts.get(name)
            if not script_content:
                logger.error(f"Lua script '{name}' is not loaded in memory.")
                return None
                
            return await self.client.eval(script_content, len(keys), *keys, *args)
        except Exception as e:
            logger.error(f"Redis Lua script execution error ({name}): {e}")
            raise

    async def close(self):
        if self.client:
            await self.client.close()
        if self.pool:
            await self.pool.disconnect()
        logger.info("Closed Redis connection pool.")
