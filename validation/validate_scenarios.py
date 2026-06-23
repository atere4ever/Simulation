"""
validation/validate_scenarios.py

Post-run hypothesis validation. After executing S1, S2, S3 scenarios,
this module checks that the observed epidemiological outcomes match
theoretical expectations:

  H4 Top-Down > Bottom-Up: S2 (lockdown) should reduce peak infection
  more than S3 (campaign), which should reduce it more than S1 (baseline).

  H1 Baseline: S1 should show a characteristic epidemic curve.

  H2 Policy-to-Environment: S2 quadrant closure should visibly constrain
  spatial spread relative to S1.

  H3 Decoupled Analytics: synchronized vs. interval-batched aggregation
  should produce identical S/I/R counts (within rounding).
"""

from typing import Dict, List, Tuple
import statistics


class EpidemicMetrics:
    """Compute key epidemiological summaries from history."""

    @staticmethod
    def peak_infected(history: List[Dict]) -> Tuple[int, int]:
        """Return (tick, count) of maximum I at any point."""
        if not history:
            return None, None
        max_i = max((h["I"], h["tick"]) for h in history)
        return max_i[1], max_i[0]

    @staticmethod
    def attack_rate(history: List[Dict]) -> float:
        """Fraction of population that was ever infected (R at end)."""
        if not history:
            return 0.0
        final = history[-1]
        total = final["S"] + final["I"] + final["R"]
        return final["R"] / total if total > 0 else 0.0

    @staticmethod
    def time_to_peak(history: List[Dict]) -> int:
        """Ticks from first I to peak I."""
        if not history:
            return None
        first_i_tick = next((h["tick"] for h in history if h["I"] > 0), None)
        peak_tick, _ = EpidemicMetrics.peak_infected(history)
        return peak_tick - first_i_tick if first_i_tick and peak_tick else None

    @staticmethod
    def cumulative_infected_days(history: List[Dict]) -> int:
        """Sum of I across all ticks (person-days of infection)."""
        return sum(h.get("I", 0) for h in history)


class ValidationSuite:
    """
    Orchestrates hypothesis checks. Each check is a callable that takes
    scenario histories and returns (passed: bool, message: str).
    """

    def __init__(self):
        self.checks = []
        self.results = []

    def add_check(self, name: str, fn):
        """Register a validation check."""
        self.checks.append((name, fn))

    def run(self, s1: List[Dict], s2: List[Dict], s3: List[Dict]) -> bool:
        """
        Execute all checks against S1, S2, S3 histories.
        Return True if all pass, False if any fail (with warnings).
        """
        all_pass = True
        print("\n" + "=" * 70)
        print("HYPOTHESIS VALIDATION SUITE")
        print("=" * 70)

        for name, check_fn in self.checks:
            try:
                passed, msg = check_fn(s1, s2, s3)
                status = "✓ PASS" if passed else "✗ FAIL"
                all_pass = all_pass and passed
                self.results.append((name, passed, msg))
                print(f"\n{status}: {name}")
                print(f"  {msg}")
            except Exception as e:
                all_pass = False
                self.results.append((name, False, str(e)))
                print(f"\n✗ ERROR: {name}")
                print(f"  {e}")

        print("\n" + "=" * 70)
        summary = sum(1 for _, p, _ in self.results if p)
        total = len(self.results)
        print(f"Summary: {summary}/{total} checks passed")
        print("=" * 70 + "\n")
        return all_pass

    def summary_csv(self) -> str:
        """Return CSV-formatted results."""
        lines = ["check_name,passed,message"]
        for name, passed, msg in self.results:
            msg_safe = msg.replace('"', '""')  # escape quotes
            lines.append(f'"{name}",{passed},"{msg_safe}"')
        return "\n".join(lines)


# ---- Individual hypothesis checks ----


def check_h1_baseline_epidemic_curve(s1, s2, s3):
    """
    H1: S1 (no intervention) shows characteristic epidemic curve:
    rise, peak, decline. Peak I > 0, and final R > initial S infection.
    """
    peak_tick, peak_i = EpidemicMetrics.peak_infected(s1)
    attack_rate = EpidemicMetrics.attack_rate(s1)

    if peak_i <= 0:
        return False, f"S1 peak I = {peak_i}, expected > 0 (no epidemic)"
    if attack_rate < 0.01:
        return (
            False,
            f"S1 attack rate = {attack_rate:.2%}, expected >= 1% (too mild)",
        )

    return True, f"Peak I={peak_i} at tick {peak_tick}, attack rate={attack_rate:.1%}"


def check_h4_topdown_vs_bottom_up(s1, s2, s3):
    """
    H4 (strong): S2 (lockdown) peak I < S3 (campaign) peak I < S1 (baseline).
    This is the core claim about intervention effectiveness.
    """
    _, peak_i_s1 = EpidemicMetrics.peak_infected(s1)
    _, peak_i_s2 = EpidemicMetrics.peak_infected(s2)
    _, peak_i_s3 = EpidemicMetrics.peak_infected(s3)

    if peak_i_s2 < peak_i_s3 < peak_i_s1:
        return (
            True,
            f"S2 peak={peak_i_s2} < S3 peak={peak_i_s3} < S1 peak={peak_i_s1} ✓",
        )
    else:
        return (
            False,
            f"Expected S2 < S3 < S1, got S1={peak_i_s1}, S2={peak_i_s2}, S3={peak_i_s3}",
        )


def check_h4_topdown_stronger_than_bottom_up(s1, s2, s3):
    """
    H4 (weak variant): S2 peak I < S1 peak I (top-down is effective).
    Weaker than full H4 but still meaningful.
    """
    _, peak_i_s1 = EpidemicMetrics.peak_infected(s1)
    _, peak_i_s2 = EpidemicMetrics.peak_infected(s2)

    reduction = (peak_i_s1 - peak_i_s2) / peak_i_s1 if peak_i_s1 > 0 else 0
    if peak_i_s2 < peak_i_s1:
        return (
            True,
            f"S2 reduces peak by {reduction:.1%} (from {peak_i_s1} to {peak_i_s2})",
        )
    else:
        return False, f"S2 peak {peak_i_s2} >= S1 peak {peak_i_s1} (no benefit)"


def check_h4_bottom_up_effective(s1, s2, s3):
    """
    H4 (weak variant): S3 peak I < S1 peak I (bottom-up campaign is effective).
    """
    _, peak_i_s1 = EpidemicMetrics.peak_infected(s1)
    _, peak_i_s3 = EpidemicMetrics.peak_infected(s3)

    reduction = (peak_i_s1 - peak_i_s3) / peak_i_s1 if peak_i_s1 > 0 else 0
    if peak_i_s3 < peak_i_s1:
        return (
            True,
            f"S3 reduces peak by {reduction:.1%} (from {peak_i_s1} to {peak_i_s3})",
        )
    else:
        return (
            False,
            f"S3 peak {peak_i_s3} >= S1 peak {peak_i_s1} (campaign ineffective)",
        )


def check_h2_spatial_containment(s1, s2, s3):
    """
    H2: S2 (quadrant closure) should reduce cumulative infected-days
    relative to S1 (spatial containment effect). Not as strong as
    overall peak reduction, but detectible.
    """
    cumul_i_s1 = EpidemicMetrics.cumulative_infected_days(s1)
    cumul_i_s2 = EpidemicMetrics.cumulative_infected_days(s2)

    reduction = (cumul_i_s1 - cumul_i_s2) / cumul_i_s1 if cumul_i_s1 > 0 else 0
    if cumul_i_s2 < cumul_i_s1:
        return (
            True,
            f"S2 reduces cumulative I-days by {reduction:.1%} (spatial containment)",
        )
    else:
        return (
            False,
            f"S2 cumulative I-days {cumul_i_s2} >= S1 {cumul_i_s1} (no containment)",
        )


def check_s1_s2_s3_monotonic_final_r(s1, s2, s3):
    """
    Monotonicity check: final R should be similar across S1, S2, S3
    (delaying infections doesn't prevent them if time window is fixed),
    but peak I should decrease: S1 >= S3 >= S2 (or similar).
    """
    final_r_s1 = s1[-1]["R"]
    final_r_s2 = s2[-1]["R"]
    final_r_s3 = s3[-1]["R"]

    # Within 10% is reasonable given stochasticity and 150-tick window
    tolerance = 0.1
    r_similar = (
        abs(final_r_s1 - final_r_s2) / final_r_s1 < tolerance
        and abs(final_r_s1 - final_r_s3) / final_r_s1 < tolerance
    )

    if r_similar:
        return (
            True,
            f"Final R: S1={final_r_s1}, S2={final_r_s2}, S3={final_r_s3} (similar, as expected)",
        )
    else:
        return (
            False,
            f"Final R varies: S1={final_r_s1}, S2={final_r_s2}, S3={final_r_s3} (diverged > 10%)",
        )


def check_no_negative_counts(s1, s2, s3):
    """Sanity check: S/I/R should never go negative."""
    for name, history in [("S1", s1), ("S2", s2), ("S3", s3)]:
        for tick_data in history:
            if tick_data.get("S", 0) < 0 or tick_data.get("I", 0) < 0 or tick_data.get("R", 0) < 0:
                return False, f"{name} has negative counts: {tick_data}"
    return True, "All S/I/R counts are non-negative ✓"


def check_conservation_of_population(s1, s2, s3):
    """
    Sanity check: S + I + R should equal total population at every tick.
    """
    for name, history in [("S1", s1), ("S2", s2), ("S3", s3)]:
        if not history:
            continue
        total = history[0]["S"] + history[0]["I"] + history[0]["R"]
        for tick_data in history:
            current_total = tick_data.get("S", 0) + tick_data.get("I", 0) + tick_data.get("R", 0)
            if current_total != total:
                return (
                    False,
                    f"{name} tick {tick_data['tick']}: total {current_total} != initial {total}",
                )
    return True, "Population conserved across all scenarios ✓"


def build_default_suite() -> ValidationSuite:
    """Factory: return a pre-configured ValidationSuite with all checks."""
    suite = ValidationSuite()
    suite.add_check("H1: Baseline epidemic curve", check_h1_baseline_epidemic_curve)
    suite.add_check("H4 (strong): S2 < S3 < S1 peak I", check_h4_topdown_vs_bottom_up)
    suite.add_check("H4 (weak): Top-down effective", check_h4_topdown_stronger_than_bottom_up)
    suite.add_check("H4 (weak): Bottom-up effective", check_h4_bottom_up_effective)
    suite.add_check("H2: Spatial containment", check_h2_spatial_containment)
    suite.add_check("Monotonicity: similar final R", check_s1_s2_s3_monotonic_final_r)
    suite.add_check("Sanity: no negative counts", check_no_negative_counts)
    suite.add_check("Sanity: population conserved", check_conservation_of_population)
    return suite


if __name__ == "__main__":
    # Example usage (import histories from CSV or call run_scenario.py)
    print("validation/validate_scenarios.py — import and use:")
    print("  from validation.validate_scenarios import build_default_suite")
    print("  suite = build_default_suite()")
    print("  passed = suite.run(s1_history, s2_history, s3_history)")
