"""
scenarios/run_scenario_interactive.py

Interactive scenario runner: human-in-the-loop policy experimentation.

Demonstrates PolicyLayer.inject_override() in action. Start with a baseline
scenario (S1), then inject policy changes mid-run via command-line prompts:

  - Adjust campaign_intensity at any tick
  - Toggle quadrant closures (on/off)
  - Save snapshots and compare against scheduled policy

This validates the architecture's claim (C1) that policy changes do NOT
require rewriting agent or environment code — only PolicyLayer.inject_override()
is called.

Usage:
    python scenarios/run_scenario_interactive.py scenarios/scenario_1_baseline.yaml
"""

import sys
import os
import csv
import yaml
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from policy.policy_layer import PolicyLayer
from agents.agent import AgentPopulation, build_initial_agents
from environment.grid import Grid
from analytics.telemetry import TelemetryBuffer, Aggregator


def load_config(config_path: str):
    """Load scenario YAML."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def interactive_override_prompt():
    """
    Blocking prompt for user override input.
    Returns dict with override parameters, or None if user quits.
    """
    print("\n" + "-" * 60)
    print("POLICY OVERRIDE MENU")
    print("-" * 60)
    print("1. Adjust campaign intensity")
    print("2. Toggle quadrant closures")
    print("3. Continue (no change)")
    print("4. Save & exit")
    print("-" * 60)

    choice = input("Enter choice (1-4): ").strip()

    overrides = {}

    if choice == "1":
        intensity = input("New campaign intensity (0.0-1.0): ").strip()
        try:
            overrides["campaign_intensity"] = float(intensity)
        except ValueError:
            print("Invalid input; ignoring.")
        return overrides

    elif choice == "2":
        quads = input("Enter quadrant tuples to close, comma-separated (e.g., '1,1 1,2'): ").strip()
        if quads:
            try:
                closed = [tuple(map(int, q.split(","))) for q in quads.split()]
                overrides["closed_quadrants"] = closed
            except ValueError:
                print("Invalid input; ignoring.")
        return overrides

    elif choice == "3":
        return None

    elif choice == "4":
        return {"_exit": True}

    else:
        print("Invalid choice.")
        return None


def run_interactive(config_path: str, check_override_every_n_ticks: int = 10):
    """
    Run scenario with periodic prompts for policy overrides.
    
    Args:
        config_path: Path to YAML scenario config
        check_override_every_n_ticks: How often to prompt user
    """
    cfg = load_config(config_path)

    grid_cfg = cfg["grid"]
    pop_cfg = cfg["population"]
    run_cfg = cfg["run"]

    print(f"\n{'=' * 60}")
    print(f"Interactive Scenario: {cfg['scenario_name']}")
    print(f"Description: {cfg['description']}")
    print(f"{'=' * 60}\n")

    policy = PolicyLayer(cfg)
    grid = Grid(
        width=grid_cfg["width"],
        height=grid_cfg["height"],
        transmission_rate=grid_cfg["transmission_rate"],
        recovery_rate=grid_cfg["recovery_rate"],
        quadrant_size=grid_cfg.get("quadrant_size", 5),
    )
    agents = build_initial_agents(
        n_agents=pop_cfg["n_agents"],
        grid_width=grid_cfg["width"],
        grid_height=grid_cfg["height"],
        n_seed_infected=pop_cfg.get("n_seed_infected", 3),
        seed=pop_cfg.get("seed"),
    )
    population = AgentPopulation(agents, seed=pop_cfg.get("seed"))

    buffer = TelemetryBuffer()
    aggregator = Aggregator(buffer, interval_ticks=run_cfg.get("aggregate_interval", 10))

    history = []
    n_ticks = run_cfg["n_ticks"]
    override_history = []  # Track when overrides were injected

    for tick in range(n_ticks):
        # Periodically check for overrides (non-blocking alternative: use threads)
        if tick > 0 and tick % check_override_every_n_ticks == 0:
            print(f"\n>>> Tick {tick}: Current state: S={population.counts()['S']}, "
                  f"I={population.counts()['I']}, R={population.counts()['R']}")
            overrides = interactive_override_prompt()

            if overrides and "_exit" in overrides:
                print("\nSaving and exiting...")
                history.append({"tick": tick, **population.counts()})
                break

            if overrides:
                policy.inject_override(**overrides)
                override_history.append((tick, overrides))
                print(f"✓ Override injected at tick {tick}: {overrides}")

        # Main simulation step
        grid.refresh_occupancy(population.agents)
        state = policy.get_state(tick)
        events = population.step_all(state, grid)

        for e in events:
            buffer.push(e)
        aggregator.collect(buffer.drain())

        snapshot = aggregator.maybe_aggregate(tick)
        if snapshot:
            history.append(snapshot)

    # Always record the final tick
    history.append({"tick": n_ticks - 1, **population.counts()})

    return history, cfg["scenario_name"], override_history


def write_results(history, scenario_name, override_history, out_dir="outputs"):
    """Write scenario results and override log to files."""
    os.makedirs(out_dir, exist_ok=True)

    # Main results CSV
    out_path = os.path.join(out_dir, f"{scenario_name}_interactive.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["tick", "S", "I", "R"])
        writer.writeheader()
        for row in history:
            writer.writerow(row)

    # Override log (for reference)
    override_log_path = os.path.join(out_dir, f"{scenario_name}_overrides.txt")
    with open(override_log_path, "w") as f:
        f.write(f"Scenario: {scenario_name}\n")
        f.write(f"Overrides injected: {len(override_history)}\n")
        f.write("-" * 60 + "\n")
        for tick, overrides in override_history:
            f.write(f"Tick {tick}: {overrides}\n")

    return out_path, override_log_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_scenario_interactive.py <config_path.yaml>")
        print("\nExample:")
        print("  python run_scenario_interactive.py scenarios/scenario_1_baseline.yaml")
        sys.exit(1)

    config_path = sys.argv[1]

    try:
        history, name, overrides = run_interactive(config_path, check_override_every_n_ticks=20)
        out_path, override_log = write_results(history, name, overrides)

        print(f"\n{'=' * 60}")
        print(f"Interactive scenario '{name}' complete")
        print(f"Aggregated snapshots: {len(history)}")
        print(f"Final tick counts: {history[-1]}")
        print(f"Overrides injected: {len(overrides)}")
        print(f"{'=' * 60}")
        print(f"\nResults written to:")
        print(f"  {out_path}")
        print(f"  {override_log}")

    except KeyboardInterrupt:
        print("\n\nSimulation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
