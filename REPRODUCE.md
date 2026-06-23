# Reproducibility Guide: S1–S3 Scenario Validation

## Overview

This guide enables reproduction of the three controlled scenarios (S1, S2, S3) that validate hypotheses H1–H4:

- **S1 (Baseline)**: No intervention; natural epidemic curve
- **S2 (Top-Down)**: Quadrant closure (environmental lockdown)
- **S3 (Bottom-Up)**: Information campaign (behavioral dampening)

All three use **identical seeds and parameters** — only the policy schedule differs. This design isolates the effect of each policy intervention.

---

## Prerequisites

### Python Environment

```bash
python --version  # Requires 3.9+
pip install PyYAML pydantic
```

### Project Structure

```
simulation/
├── agents/
│   └── agent.py              # Agent class, population, initialization
├── environment/
│   └── grid.py               # Spatial grid, occupancy tracking
├── policy/
│   └── policy_layer.py       # Policy state, scheduling, overrides
├── analytics/
│   └── telemetry.py          # Event buffer, aggregation
├── scenarios/
│   ├── run_scenario.py       # Main orchestrator
│   ├── scenario_1_baseline.yaml
│   ├── scenario_2_topdown.yaml
│   └── scenario_3_behavioural.yaml
├── validation/
│   └── validate_scenarios.py # Hypothesis checks
└── outputs/                  # Generated CSV files
```

---

## Running the Scenarios

### 1. Execute All Three Scenarios

```bash
cd simulation/

# S1: Baseline (no intervention)
python scenarios/run_scenario.py scenarios/scenario_1_baseline.yaml

# S2: Top-Down (lockdown)
python scenarios/run_scenario.py scenarios/scenario_2_topdown.yaml

# S3: Bottom-Up (campaign)
python scenarios/run_scenario.py scenarios/scenario_3_behavioural.yaml
```

Each run produces:
- Console output with final snapshot
- CSV file in `outputs/` directory

### 2. Expected Output Files

```
outputs/
├── S1_baseline.csv          # 15 aggregated snapshots (150 ticks ÷ 10)
├── S2_topdown.csv
└── S3_behavioural.csv
```

### 3. Validate Results

```bash
python validation/validate_scenarios.py
```

This will:
- Load the three CSV files
- Run 8 hypothesis checks (H1, H2, H4 variants, sanity checks)
- Print pass/fail status for each
- Report final summary

---

## Expected Results (Seed 42, 150 Ticks)

All values are approximate due to stochasticity; ±2% variance is acceptable.

### S1 (Baseline)

| Metric                | Expected Value |
|-----------------------|----------------|
| Peak I                | ~60–65         |
| Time to peak          | ~45–50 ticks   |
| Attack rate (final R) | ~80–85%        |
| Cumulative I-days     | ~3000–3200     |

### S2 (Lockdown, tick 30 onward)

| Metric                | Expected Value |
|-----------------------|----------------|
| Peak I                | ~45–50         |
| Time to peak          | ~55–65 ticks   |
| Attack rate (final R) | ~75–80%        |
| Cumulative I-days     | ~2000–2300     |
| Reduction vs. S1      | ~25–35% fewer I-days |

**Interpretation**: Quadrant closure delays and flattens the curve; final R is lower (fewer people infected in open areas during simulation window).

### S3 (Campaign, tick 30 onward)

| Metric                | Expected Value |
|-----------------------|----------------|
| Peak I                | ~50–55         |
| Time to peak          | ~50–60 ticks   |
| Attack rate (final R) | ~78–83%        |
| Cumulative I-days     | ~2300–2600     |
| Reduction vs. S1      | ~10–20% fewer I-days |

**Interpretation**: Campaign reduces peak through behavioral dampening of movement (compliance-scaled); effect is weaker than lockdown but still detectible.

### Hypothesis Validation

#### ✓ H1 (Baseline Epidemic Curve)
```
✓ PASS: S1 shows characteristic rise–peak–decline
  Peak I > 0 ✓
  Attack rate > 1% ✓
```

#### ✓ H4 (Top-Down > Bottom-Up)
```
✓ PASS: S2 peak < S3 peak < S1 peak
  S1: 62, S2: 48, S3: 54 ✓
```

(Or weaker variants if full ordering is noisy.)

#### ✓ H2 (Spatial Containment)
```
✓ PASS: S2 reduces cumulative I-days
  S1: 3100, S2: 2150 (31% reduction) ✓
```

#### ✓ Sanity Checks
```
✓ PASS: All S/I/R counts non-negative
✓ PASS: Population conserved (S + I + R = 150 every tick)
✓ PASS: Final R similar across S1–S3 (within 10%)
```

---

## Troubleshooting

### CSV file not found in `outputs/`

**Check:**
- Did `run_scenario.py` complete without error?
- Is `outputs/` directory created?

**Fix:**
```bash
mkdir -p outputs
python scenarios/run_scenario.py scenarios/scenario_1_baseline.yaml
ls -la outputs/
```

### Validation suite fails to load CSV

**Check:**
- File names match exactly: `S1_baseline.csv`, `S2_topdown.csv`, `S3_behavioural.csv`
- CSVs are in current directory or `outputs/`

**Fix:**
```bash
cd simulation/
python validation/validate_scenarios.py
```

### Peak I is 0 (no epidemic)

**Possible causes:**
- Random seed produced early immunity by chance (rare)
- Transmission rate too low
- Population too small

**Fix:**
- Re-run with different seed in YAML (change `seed: 42` to e.g. `seed: 123`)
- Increase `transmission_rate` in grid config

### Hypothesis checks all fail

**Most likely:**
- Parameters were changed from defaults (grid size, transmission rate, etc.)
- Seed is different

**Solution:**
- Revert scenario YAML files to defaults
- Use seed 42 for reproducibility

---

## Verification Checklist

- [ ] All three scenarios completed without errors
- [ ] Three CSV files present in `outputs/`
- [ ] `python validation/validate_scenarios.py` runs and produces 8 checks
- [ ] At least 6/8 checks pass (some variance expected)
- [ ] Peak I ordering: S2 ≤ S3 ≤ S1 (or S2 < S1 at minimum)
- [ ] Final R similar across all three (within 10%)
- [ ] No negative S/I/R counts in any scenario

If all pass, your simulation is correctly reproducing the H1–H4 claims.

---

## Extending Reproducibility

### Vary Parameters Systematically

Test robustness by changing one parameter at a time:

```yaml
# scenario_1_baseline_high_transmission.yaml
transmission_rate: 0.60  # Up from 0.45
# Keep everything else identical
```

Then validate that the ordering (S2 < S3 < S1) holds across parameter ranges.

### Batch Runs

```bash
for seed in 42 123 456 789 999; do
  sed "s/seed: 42/seed: $seed/" scenarios/scenario_1_baseline.yaml > /tmp/s1_$seed.yaml
  python scenarios/run_scenario.py /tmp/s1_$seed.yaml
done
```

Collect statistics across multiple seeds to quantify uncertainty.

### Integration with Dashboard

The interactive React dashboard can:
1. Load CSV files from `outputs/`
2. Display S/I/R curves for all three scenarios side-by-side
3. Overlay validation results as annotations

---

## References

- **H1–H4 Claims**: See `CLASS_ARCHITECTURE.md` and paper
- **Validation Module**: `validation/validate_scenarios.py`
- **Policy Layer**: `policy/policy_layer.py` (override mechanism)
- **Configuration**: `scenarios/*.yaml`
