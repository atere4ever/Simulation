"""
backend/models.py

Data models for API requests/responses. Pydantic schemas ensure type safety
and validation before passing to simulation layer.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from enum import Enum


class ScenarioType(str, Enum):
    """Scenario templates."""
    BASELINE = "baseline"
    TOPDOWN = "topdown"
    BEHAVIOURAL = "behavioural"
    CUSTOM = "custom"


class GridConfig(BaseModel):
    """Grid/environment parameters."""
    width: int = Field(default=20, ge=5, le=100)
    height: int = Field(default=20, ge=5, le=100)
    transmission_rate: float = Field(default=0.45, ge=0.0, le=1.0)
    recovery_rate: float = Field(default=0.04, ge=0.0, le=1.0)
    quadrant_size: int = Field(default=4, ge=1, le=20)


class PopulationConfig(BaseModel):
    """Agent population parameters."""
    n_agents: int = Field(default=150, ge=10, le=10000)
    n_seed_infected: int = Field(default=5, ge=1, le=100)
    seed: Optional[int] = None


class PolicyScheduleEntry(BaseModel):
    """Single policy intervention at a scheduled tick."""
    closed_quadrants: List[List[int]] = Field(default_factory=list)
    campaign_intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    resource_multiplier: float = Field(default=1.0, ge=0.5, le=2.0)


class RunConfig(BaseModel):
    """Full scenario configuration."""
    scenario_name: str
    description: str = ""
    scenario_type: ScenarioType = ScenarioType.CUSTOM
    grid: GridConfig = Field(default_factory=GridConfig)
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    n_ticks: int = Field(default=150, ge=10, le=1000)
    aggregate_interval: int = Field(default=10, ge=1, le=50)
    policy_schedule: Dict[str, PolicyScheduleEntry] = Field(default_factory=dict)

    @validator('policy_schedule', pre=True, always=True)
    def parse_policy_schedule(cls, v):
        """Convert policy schedule entries to PolicyScheduleEntry objects."""
        if not v:
            return {}
        parsed = {}
        for tick_str, entry in v.items():
            if isinstance(entry, PolicyScheduleEntry):
                parsed[tick_str] = entry
            else:
                parsed[tick_str] = PolicyScheduleEntry(**entry)
        return parsed


class PolicyOverride(BaseModel):
    """Runtime policy override injection."""
    campaign_intensity: Optional[float] = Field(None, ge=0.0, le=1.0)
    closed_quadrants: Optional[List[List[int]]] = None
    resource_multiplier: Optional[float] = Field(None, ge=0.5, le=2.0)


class TickSnapshot(BaseModel):
    """Single timestep SIR state."""
    tick: int
    S: int
    I: int
    R: int


class RunStatus(str, Enum):
    """Run lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class RunMetadata(BaseModel):
    """Run tracking: status, timing, config."""
    run_id: str
    scenario_name: str
    status: RunStatus = RunStatus.PENDING
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    current_tick: int = 0
    total_ticks: int
    config: RunConfig
    error: Optional[str] = None


class TelemetryResponse(BaseModel):
    """Current run telemetry snapshot."""
    run_id: str
    current_tick: int
    status: RunStatus
    kpis: Dict[str, int]  # {S, I, R}
    timestamp: str
    overrides_injected: List[Dict[str, Any]] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Single hypothesis check result."""
    check_name: str
    passed: bool
    message: str


class ValidationReport(BaseModel):
    """Full validation suite results (post-run)."""
    run_id: str
    scenario_name: str
    total_checks: int
    passed_checks: int
    results: List[ValidationResult]
    timestamp: str
    summary: str


class RunListResponse(BaseModel):
    """List of all historical runs with metadata."""
    runs: List[RunMetadata]
    total_count: int


class HistoryExportResponse(BaseModel):
    """Full S/I/R history for a completed run."""
    run_id: str
    scenario_name: str
    history: List[TickSnapshot]
    metadata: RunMetadata
