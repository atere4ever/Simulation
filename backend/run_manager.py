"""
backend/run_manager.py

Manages the lifecycle of simulation runs:
  - Spawn new runs (track state, IDs)
  - Persist telemetry to disk
  - Pause/resume/cancel
  - Expose current state for dashboard polling
"""

import uuid
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scenarios.run_scenario import run as run_scenario_sync
from models import RunStatus, RunMetadata, TickSnapshot, RunConfig


@dataclass
class RunState:
    """In-memory state for an active run."""
    run_id: str
    config: RunConfig
    status: RunStatus
    current_tick: int = 0
    history: List[Dict] = None  # Aggregated snapshots
    overrides_injected: List[Dict] = None
    error: Optional[str] = None
    thread: Optional[threading.Thread] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []
        if self.overrides_injected is None:
            self.overrides_injected = []


class RunManager:
    """
    Centralized lifecycle management for simulation runs.
    Thread-safe storage of active/completed runs.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory registry: run_id -> RunState
        self._runs: Dict[str, RunState] = {}
        self._lock = threading.Lock()
        
        # Load historical runs from disk
        self._load_run_history()

    def _load_run_history(self) -> None:
        """Scan storage_dir for completed runs and index metadata."""
        for metadata_file in self.storage_dir.glob("*/metadata.json"):
            try:
                with open(metadata_file, "r") as f:
                    data = json.load(f)
                    run_id = data.get("run_id")
                    if run_id:
                        # Metadata only; full data loaded on demand
                        pass
            except Exception as e:
                print(f"Warning: could not load metadata from {metadata_file}: {e}")

    def create_run(self, config: RunConfig) -> str:
        """
        Create a new run record. Return run_id (UUID).
        Run starts in PENDING state; call start_run() to begin execution.
        """
        run_id = str(uuid.uuid4())
        
        state = RunState(
            run_id=run_id,
            config=config,
            status=RunStatus.PENDING,
            current_tick=0,
            history=[],
            overrides_injected=[],
        )
        
        with self._lock:
            self._runs[run_id] = state
        
        # Persist initial metadata
        self._save_metadata(run_id)
        
        return run_id

    def start_run(self, run_id: str) -> None:
        """
        Transition run from PENDING -> RUNNING and spawn background thread.
        Raises ValueError if run not found or not in PENDING state.
        """
        with self._lock:
            if run_id not in self._runs:
                raise ValueError(f"Run {run_id} not found")
            
            state = self._runs[run_id]
            if state.status != RunStatus.PENDING:
                raise ValueError(f"Run {run_id} is {state.status}, cannot start")
            
            state.status = RunStatus.RUNNING
            state.thread = threading.Thread(
                target=self._run_worker,
                args=(run_id,),
                daemon=False,
            )
            state.thread.start()

    def _run_worker(self, run_id: str) -> None:
        """
        Background worker thread: execute simulation and capture history.
        Updates state in-memory; persists on completion.
        """
        try:
            state = self._runs[run_id]
            
            # Convert RunConfig to scenario config dict
            scenario_config = {
                "scenario_name": state.config.scenario_name,
                "description": state.config.description,
                "grid": {
                    "width": state.config.grid.width,
                    "height": state.config.grid.height,
                    "transmission_rate": state.config.grid.transmission_rate,
                    "recovery_rate": state.config.grid.recovery_rate,
                    "quadrant_size": state.config.grid.quadrant_size,
                },
                "population": {
                    "n_agents": state.config.population.n_agents,
                    "n_seed_infected": state.config.population.n_seed_infected,
                    "seed": state.config.population.seed,
                },
                "run": {
                    "n_ticks": state.config.n_ticks,
                    "aggregate_interval": state.config.aggregate_interval,
                },
                "policy_schedule": {
                    str(tick): {
                        "closed_quadrants": entry.closed_quadrants,
                        "campaign_intensity": entry.campaign_intensity,
                        "resource_multiplier": entry.resource_multiplier,
                    }
                    for tick, entry in state.config.policy_schedule.items()
                },
            }
            
            # Run scenario (blocking call)
            history, scenario_name = run_scenario_sync(scenario_config)
            
            state.history = history
            state.current_tick = state.config.n_ticks - 1
            state.status = RunStatus.COMPLETED
            
        except Exception as e:
            state.status = RunStatus.FAILED
            state.error = str(e)
            print(f"Run {run_id} failed: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Persist final state
            self._save_metadata(run_id)
            self._save_history(run_id)

    def get_run(self, run_id: str) -> Optional[RunState]:
        """Retrieve run state by ID."""
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> List[RunMetadata]:
        """Return metadata for all runs (in-memory + historical)."""
        results = []
        
        with self._lock:
            for run_id, state in self._runs.items():
                results.append(self._state_to_metadata(state))
        
        # Also scan disk for historical runs not in memory
        for metadata_file in self.storage_dir.glob("*/metadata.json"):
            try:
                with open(metadata_file, "r") as f:
                    data = json.load(f)
                    # Avoid duplicates
                    if not any(r.run_id == data.get("run_id") for r in results):
                        results.append(RunMetadata(**data))
            except Exception:
                pass
        
        return sorted(results, key=lambda r: r.created_at, reverse=True)

    def inject_override(self, run_id: str, override: Dict) -> None:
        """
        Record a policy override for a running simulation.
        (In a real implementation, this would communicate with the running worker thread.)
        """
        with self._lock:
            if run_id not in self._runs:
                raise ValueError(f"Run {run_id} not found")
            
            state = self._runs[run_id]
            state.overrides_injected.append({
                "tick": state.current_tick,
                "override": override,
            })

    def get_history(self, run_id: str) -> List[TickSnapshot]:
        """Load full S/I/R history for a run."""
        state = self.get_run(run_id)
        if state and state.history:
            return [TickSnapshot(**h) for h in state.history]
        
        # Try loading from disk
        history_file = self.storage_dir / run_id / "history.json"
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    data = json.load(f)
                    return [TickSnapshot(**h) for h in data]
            except Exception as e:
                print(f"Error loading history for {run_id}: {e}")
        
        return []

    def _state_to_metadata(self, state: RunState) -> RunMetadata:
        """Convert RunState to API-safe RunMetadata."""
        now = datetime.utcnow().isoformat() + "Z"
        
        return RunMetadata(
            run_id=state.run_id,
            scenario_name=state.config.scenario_name,
            status=state.status,
            created_at=now,
            started_at=now if state.status != RunStatus.PENDING else None,
            completed_at=now if state.status == RunStatus.COMPLETED else None,
            current_tick=state.current_tick,
            total_ticks=state.config.n_ticks,
            config=state.config,
            error=state.error,
        )

    def _save_metadata(self, run_id: str) -> None:
        """Persist run metadata to disk."""
        state = self.get_run(run_id)
        if not state:
            return
        
        run_dir = self.storage_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        metadata = self._state_to_metadata(state)
        metadata_file = run_dir / "metadata.json"
        
        with open(metadata_file, "w") as f:
            json.dump(metadata.dict(), f, indent=2)

    def _save_history(self, run_id: str) -> None:
        """Persist full S/I/R history to disk."""
        state = self.get_run(run_id)
        if not state or not state.history:
            return
        
        run_dir = self.storage_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        history_file = run_dir / "history.json"
        
        with open(history_file, "w") as f:
            json.dump(state.history, f, indent=2)
