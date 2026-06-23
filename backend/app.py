"""
backend/app.py

Flask REST API server. Routes for:
  - POST /api/runs — create & start new scenario
  - GET /api/runs/<run_id> — poll current telemetry
  - POST /api/runs/<run_id>/override — inject policy change mid-run
  - GET /api/runs/<run_id>/history — fetch full S/I/R history
  - GET /api/runs — list all historical runs
  - POST /api/validate — run validation suite post-scenario

Connects dashboard UI to simulation backend.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import get_config
from backend.models import (
    RunConfig, PolicyOverride, RunStatus, TelemetryResponse,
    RunListResponse, HistoryExportResponse, ValidationReport
)
from backend.run_manager import RunManager


# ---- Initialization ----

def create_app(config_env: str = None):
    """Factory: create and configure Flask app."""
    app = Flask(__name__)
    config = get_config(config_env)
    app.config.from_object(config)
    
    # CORS: allow dashboard to call API
    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)
    
    # Global run manager
    app.run_manager = RunManager(storage_dir=config.RUNS_DIR)
    
    # Register routes
    register_routes(app)
    
    return app


def register_routes(app: Flask) -> None:
    """Register all API endpoints."""
    
    # ---- Health ----
    @app.route("/api/health", methods=["GET"])
    def health():
        """Liveness probe."""
        return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()}), 200
    
    # ---- Runs: Create ----
    @app.route("/api/runs", methods=["POST"])
    def create_run():
        """
        POST /api/runs
        
        Create a new scenario run.
        
        Body: RunConfig JSON
        Returns: {"run_id": "...", "status": "pending"}
        """
        try:
            payload = request.get_json()
            config = RunConfig(**payload)
            
            run_id = app.run_manager.create_run(config)
            
            # Auto-start (remove this line to require explicit start call)
            app.run_manager.start_run(run_id)
            
            return jsonify({
                "run_id": run_id,
                "status": RunStatus.RUNNING.value,
                "message": f"Scenario '{config.scenario_name}' started",
            }), 201
        
        except ValidationError as e:
            return jsonify({"error": e.errors()}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # ---- Runs: Telemetry Polling ----
    @app.route("/api/runs/<run_id>", methods=["GET"])
    def get_telemetry(run_id: str):
        """
        GET /api/runs/<run_id>
        
        Poll current run status and SIR counts.
        
        Returns: TelemetryResponse
        """
        state = app.run_manager.get_run(run_id)
        if not state:
            return jsonify({"error": f"Run {run_id} not found"}), 404
        
        # Latest snapshot
        latest = state.history[-1] if state.history else {"S": 0, "I": 0, "R": 0, "tick": 0}
        
        response = TelemetryResponse(
            run_id=run_id,
            current_tick=state.current_tick,
            status=state.status,
            kpis={"S": latest.get("S", 0), "I": latest.get("I", 0), "R": latest.get("R", 0)},
            timestamp=datetime.utcnow().isoformat() + "Z",
            overrides_injected=[o["override"] for o in state.overrides_injected],
        )
        
        return jsonify(response.dict()), 200
    
    # ---- Runs: Override Injection ----
    @app.route("/api/runs/<run_id>/override", methods=["POST"])
    def inject_override(run_id: str):
        """
        POST /api/runs/<run_id>/override
        
        Inject a policy override mid-run.
        
        Body: PolicyOverride JSON
        Returns: {"status": "injected", "tick": <current_tick>}
        """
        try:
            state = app.run_manager.get_run(run_id)
            if not state:
                return jsonify({"error": f"Run {run_id} not found"}), 404
            
            if state.status not in [RunStatus.RUNNING, RunStatus.PAUSED]:
                return jsonify({"error": f"Cannot inject override on {state.status} run"}), 409
            
            payload = request.get_json()
            override = PolicyOverride(**payload)
            
            app.run_manager.inject_override(run_id, override.dict(exclude_none=True))
            
            return jsonify({
                "status": "injected",
                "tick": state.current_tick,
                "override": override.dict(exclude_none=True),
            }), 200
        
        except ValidationError as e:
            return jsonify({"error": e.errors()}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # ---- Runs: History Export ----
    @app.route("/api/runs/<run_id>/history", methods=["GET"])
    def get_history(run_id: str):
        """
        GET /api/runs/<run_id>/history
        
        Fetch full S/I/R history for a completed run.
        
        Returns: HistoryExportResponse
        """
        state = app.run_manager.get_run(run_id)
        if not state:
            return jsonify({"error": f"Run {run_id} not found"}), 404
        
        if state.status != RunStatus.COMPLETED:
            return jsonify({"error": f"History only available for completed runs; this is {state.status}"}), 409
        
        history = app.run_manager.get_history(run_id)
        metadata = app.run_manager._state_to_metadata(state)
        
        response = HistoryExportResponse(
            run_id=run_id,
            scenario_name=state.config.scenario_name,
            history=history,
            metadata=metadata,
        )
        
        return jsonify(response.dict(by_alias=False)), 200
    
    # ---- Runs: List All ----
    @app.route("/api/runs", methods=["GET"])
    def list_runs():
        """
        GET /api/runs
        
        List all historical runs with metadata.
        
        Query params:
          - status: filter by RunStatus (e.g., ?status=completed)
          - limit: max results (default 50)
          - offset: pagination offset (default 0)
        
        Returns: RunListResponse
        """
        all_runs = app.run_manager.list_runs()
        
        # Filter by status if requested
        status_filter = request.args.get("status")
        if status_filter:
            all_runs = [r for r in all_runs if r.status.value == status_filter]
        
        # Pagination
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))
        
        paginated = all_runs[offset:offset + limit]
        
        response = RunListResponse(
            runs=paginated,
            total_count=len(all_runs),
        )
        
        return jsonify(response.dict()), 200
    
    # ---- Validation: Post-Run Suite ----
    @app.route("/api/validate", methods=["POST"])
    def validate_runs():
        """
        POST /api/validate
        
        Run validation suite on three completed scenarios (S1, S2, S3).
        
        Body: {"s1_run_id": "...", "s2_run_id": "...", "s3_run_id": "..."}
        Returns: ValidationReport
        """
        try:
            payload = request.get_json()
            s1_run_id = payload.get("s1_run_id")
            s2_run_id = payload.get("s2_run_id")
            s3_run_id = payload.get("s3_run_id")
            
            # Fetch histories
            s1_history = app.run_manager.get_history(s1_run_id)
            s2_history = app.run_manager.get_history(s2_run_id)
            s3_history = app.run_manager.get_history(s3_run_id)
            
            if not all([s1_history, s2_history, s3_history]):
                return jsonify({"error": "One or more runs not found or not completed"}), 404
            
            # Convert to dict for validation suite
            s1_data = [{"tick": h.tick, "S": h.S, "I": h.I, "R": h.R} for h in s1_history]
            s2_data = [{"tick": h.tick, "S": h.S, "I": h.I, "R": h.R} for h in s2_history]
            s3_data = [{"tick": h.tick, "S": h.S, "I": h.I, "R": h.R} for h in s3_history]
            
            # Import and run validation suite
            from validation.validate_scenarios import build_default_suite
            suite = build_default_suite()
            suite.run(s1_data, s2_data, s3_data)
            
            # Build response
            from backend.models import ValidationResult
            results = [
                ValidationResult(
                    check_name=name,
                    passed=passed,
                    message=msg,
                )
                for name, passed, msg in suite.results
            ]
            
            passed_count = sum(1 for r in results if r.passed)
            
            response = ValidationReport(
                run_id=f"{s1_run_id}+{s2_run_id}+{s3_run_id}",
                scenario_name="S1+S2+S3 Validation",
                total_checks=len(results),
                passed_checks=passed_count,
                results=results,
                timestamp=datetime.utcnow().isoformat() + "Z",
                summary=f"{passed_count}/{len(results)} checks passed",
            )
            
            return jsonify(response.dict()), 200
        
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # ---- Error Handlers ----
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404
    
    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app = create_app(config_env="development")
    app.run(host="0.0.0.0", port=5000, debug=True)
