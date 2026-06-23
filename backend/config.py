"""
backend/config.py

Configuration for Flask backend. Centralized settings for:
  - Simulation parameters (grid size, population, transmission rate)
  - API behavior (CORS, auth, request limits)
  - Storage (run history, telemetry persistence)
  - Logging
"""

import os
from pathlib import Path

# ---- Paths ----
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RUNS_DIR = PROJECT_ROOT / "backend" / "runs"  # Per-run session storage

# Create directories if needed
OUTPUTS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)

# ---- Flask Configuration ----
class Config:
    """Base configuration."""
    DEBUG = False
    TESTING = False
    JSON_SORT_KEYS = False
    
    # CORS: Allow dashboard to call API from localhost
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
    ]
    
    # Rate limiting
    MAX_CONCURRENT_RUNS = 5
    REQUEST_TIMEOUT_SECONDS = 300
    
    # Simulation defaults
    DEFAULT_N_TICKS = 150
    DEFAULT_N_AGENTS = 150
    DEFAULT_GRID_SIZE = 20
    DEFAULT_TRANSMISSION_RATE = 0.45
    DEFAULT_RECOVERY_RATE = 0.04
    DEFAULT_AGGREGATE_INTERVAL = 10


class DevelopmentConfig(Config):
    """Development environment."""
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing environment."""
    DEBUG = True
    TESTING = True
    MAX_CONCURRENT_RUNS = 1


class ProductionConfig(Config):
    """Production environment."""
    DEBUG = False
    TESTING = False
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []


def get_config(env: str = None) -> Config:
    """Factory: return config object based on environment."""
    if env is None:
        env = os.getenv("FLASK_ENV", "development")
    
    configs = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }
    
    return configs.get(env, DevelopmentConfig)()
