import sys
import logging
import structlog

def configure_logger(debug: bool = False):
    # Standard python logging configuration
    logging_level = logging.DEBUG if debug else logging.INFO
    
    # Configure processors for structlog
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if debug:
        # Dev formatting (colored/console)
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # Production JSON formatting
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging_level,
    )

def get_logger(name: str):
    return structlog.get_logger(name)
