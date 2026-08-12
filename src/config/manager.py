import os
import yaml
import logging
import asyncio
from typing import Callable, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.config.models import AppConfig

logger = logging.getLogger("arl.config")

class ConfigHandler(FileSystemEventHandler):
    def __init__(self, config_path: str, reload_callback: Callable[[], None]):
        self.config_path = os.path.abspath(config_path)
        self.reload_callback = reload_callback
        super().__init__()

    def on_modified(self, event):
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) == self.config_path:
            logger.info("Configuration file modification detected, triggering reload.")
            self.reload_callback()

class ConfigManager:
    def __init__(self, config_path: str = "config/default_config.yaml"):
        self.config_path = config_path
        self._config: Optional[AppConfig] = None
        self._callbacks: List[Callable[[AppConfig], None]] = []
        self._observer: Optional[Observer] = None
        self._lock = asyncio.Lock()
        
        # Load initially
        self.reload_config()

    def get_config(self) -> AppConfig:
        if self._config is None:
            raise ValueError("Configuration has not been loaded yet.")
        return self._config

    def reload_config(self) -> bool:
        try:
            if not os.path.exists(self.config_path):
                logger.error(f"Configuration file not found at {self.config_path}")
                return False
                
            with open(self.config_path, 'r') as f:
                raw_data = yaml.safe_load(f)
                
            new_config = AppConfig(**raw_data)
            self._config = new_config
            logger.info("Configuration successfully loaded and validated.")
            
            # Fire callbacks
            for callback in self._callbacks:
                try:
                    callback(new_config)
                except Exception as e:
                    logger.exception(f"Error in config change callback: {e}")
            return True
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")
            return False

    def register_callback(self, callback: Callable[[AppConfig], None]):
        self._callbacks.append(callback)
        if self._config is not None:
            try:
                callback(self._config)
            except Exception as e:
                logger.exception(f"Error in initial config callback: {e}")

    def start_watcher(self):
        if self._observer is not None:
            return
            
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        if not config_dir:
            config_dir = "."
            
        event_handler = ConfigHandler(
            config_path=self.config_path,
            reload_callback=self.reload_config
        )
        
        self._observer = Observer()
        self._observer.schedule(event_handler, path=config_dir, recursive=False)
        self._observer.start()
        logger.info(f"Started watching configuration directory {config_dir} for changes.")

    def stop_watcher(self):
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped configuration file watcher.")
