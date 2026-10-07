#!/usr/bin/env python3
"""
PROJECT SHADOW — Synthetic CSI Data Generator
===============================================

Generates realistic synthetic Wi-Fi CSI data for:
  1. Neural network training (without ESP32 hardware)
  2. Demo playback scenarios (for presentations)

The generated CSV files are in the EXACT same format as radar_graph.py's
--raw-log output, so train_model.py and evaluate.py work without changes.

Usage:
    # Generate training data (separate files per class):
    python generate_synthetic_data.py --mode training

    # Generate a demo scenario (single file with scripted events):
    python generate_synthetic_data.py --mode demo

    # Generate both:
    python generate_synthetic_data.py --mode all

Output:
    Training mode:
      - synthetic_empty.csv     (3 minutes of empty room)
      - synthetic_walking.csv   (3 minutes of walking)

    Demo mode:
      - demo_scenario.csv       (scripted: empty->walking->weapon->recovery)

Author: PROJECT SHADOW
"""

import argparse
import csv
import math
import os
import sys
import time

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION — Must match radar_graph.py exactly
# ═══════════════════════════════════════════════════════════════════════════

NORMALIZED_SUBCARRIER_COUNT = 52  # Same as radar_graph.py
PACKET_RATE = 50                  # Packets per second (typical ESP32 rate)

# ═══════════════════════════════════════════════════════════════════════════
# CSI PHYSICS SIMULATION
# ═══════════════════════════════════════════════════════════════════════════
#
# Real Wi-Fi CSI (Channel State Information) captures how the wireless
# channel distorts signals across different subcarrier frequencies.
#
# Each subcarrier has:
#   - Amplitude: Signal strength (affected by path loss, reflections)
#   - Phase: Signal timing (affected by distance, multipath)
#
# When a human walks through the room:
#   - Amplitudes show slow sinusoidal variation (~1-2 Hz, matching gait)
#   - Phases show drift proportional to path length changes
#   - Different subcarriers are affected differently (frequency-selective fading)
#
# When a weapon (RF jammer) attacks:
#   - Amplitudes spike with high-frequency noise
#   - Phase becomes chaotic (random jumps)
#   - The pattern does NOT match natural human movement
# ═══════════════════════════════════════════════════════════════════════════


class CSISimulator:
    """
    Generates realistic synthetic CSI data that matches real ESP32 output.
    
    The simulator models:
      - Static multipath channel profile (room-specific)
      - Thermal noise (always present)
      - Human motion (Doppler-like amplitude/phase modulation)
      - Weapon interference (high-energy random bursts)
    """

    def __init__(self, seed=42):
        """
        Args:
            seed: Random seed for reproducibility (same seed = same data)
        """
        self.rng = np.random.RandomState(seed)
        self.sc_count = NORMALIZED_SUBCARRIER_COUNT

        # ── Static channel profile (unique to this "room") ────────────
        # Each subcarrier has a baseline amplitude and phase that depends
        # on the room geometry, furniture placement, wall materials, etc.
        self.base_amplitude = 25.0 + 10.0 * np.sin(
            np.linspace(0, 2 * np.pi, self.sc_count)
        ) + self.rng.uniform(-3, 3, self.sc_count)

        self.base_phase = np.linspace(-np.pi, np.pi, self.sc_count) + \
                          self.rng.uniform(-0.5, 0.5, self.sc_count)

        # ── Subcarrier sensitivity profile ────────────────────────────
        # Not all subcarriers respond equally to motion. Middle ones are
        # typically more sensitive (better SNR).
        center = self.sc_count // 2
        self.sensitivity = np.exp(
            -0.5 * ((np.arange(self.sc_count) - center) / (self.sc_count * 0.3)) ** 2
        )

        # ── Slow environmental drift ─────────────────────────────────
        # Temperature changes, people in adjacent rooms, etc. cause very
        # slow baseline drift over minutes.
        self.drift_rate = self.rng.uniform(0.001, 0.005, self.sc_count)
        self.drift_phase = self.rng.uniform(0, 2 * np.pi, self.sc_count)

    def generate_packet(self, timestamp: float, state: str,
                        walking_params: dict = None) -> tuple:
        """
        Generate one CSI packet (amplitude + phase vectors).

        Args:
            timestamp: Current time in seconds
            state: One of 'empty', 'walking', 'weapon'
            walking_params: Optional dict with walking parameters
                           (speed, direction, position)

        Returns:
            (amplitudes, phases) — each a numpy array of shape (sc_count,)
        """
        # ── 1. Start with static channel + slow drift ─────────────────
        drift = 0.3 * np.sin(self.drift_rate * timestamp * 2 * np.pi + self.drift_phase)
        amplitudes = self.base_amplitude.copy() + drift

        phases = self.base_phase.copy() + \
                 0.02 * np.sin(0.01 * timestamp * 2 * np.pi + self.drift_phase)

        # ── 2. Add thermal noise (always present) ─────────────────────
        amp_noise = self.rng.normal(0, 0.8, self.sc_count)
        phase_noise = self.rng.normal(0, 0.05, self.sc_count)
        amplitudes += amp_noise
        phases += phase_noise

        # ── 3. Apply motion effects ───────────────────────────────────
        if state == 'walking':
            wp = walking_params or {}
            speed = wp.get('speed', 1.0)
            gait_freq = wp.get('gait_freq', 1.8)  # ~1.8 Hz human gait

            # Doppler-like amplitude modulation
            # Different subcarriers see different amounts of modulation
            for sc in range(self.sc_count):
                # Primary gait component
                gait_mod = self.sensitivity[sc] * 8.0 * speed * \
                           math.sin(2 * math.pi * gait_freq * timestamp +
                                    sc * 0.15)

                # Harmonics (human motion is not purely sinusoidal)
                harmonic = self.sensitivity[sc] * 3.0 * speed * \
                           math.sin(2 * math.pi * gait_freq * 2 * timestamp +
                                    sc * 0.3 + 1.2)

                # Arm swing component (different frequency from legs)
                arm_mod = self.sensitivity[sc] * 2.0 * speed * \
                          math.sin(2 * math.pi * gait_freq * 0.5 * timestamp +
                                   sc * 0.08 + 0.7)

                amplitudes[sc] += gait_mod + harmonic + arm_mod

                # Phase shift from path length change
                phases[sc] += self.sensitivity[sc] * 0.4 * speed * \
                              math.sin(2 * math.pi * gait_freq * timestamp +
                                       sc * 0.2 + 0.5)

            # Add slight randomness to simulate unpredictable human movement
            amplitudes += self.rng.normal(0, 1.5 * speed, self.sc_count)
            phases += self.rng.normal(0, 0.1 * speed, self.sc_count)

        elif state == 'weapon':
            # RF interference creates high-energy, non-natural patterns
            # Key difference from walking: NO gait frequency, much higher noise

            # Random amplitude spikes (beacon flood effect)
            spike_strength = self.rng.uniform(5, 25, self.sc_count)
            spike_pattern = np.sin(
                2 * np.pi * self.rng.uniform(10, 50) * timestamp +
                self.rng.uniform(0, 2 * np.pi, self.sc_count)
            )
            amplitudes += spike_strength * spike_pattern

            # Phase becomes chaotic (no coherent structure)
            phases += self.rng.uniform(-np.pi, np.pi, self.sc_count) * 0.3

            # Occasional large spikes (packet bursts)
            if self.rng.random() > 0.7:
                burst_sc = self.rng.randint(0, self.sc_count, 
                                           size=self.rng.randint(5, 20))
                amplitudes[burst_sc] += self.rng.uniform(10, 30, len(burst_sc))

        # ── 4. Clamp to realistic ranges ──────────────────────────────
        amplitudes = np.clip(amplitudes, 1.0, 80.0)
        phases = np.mod(phases + np.pi, 2 * np.pi) - np.pi  # Wrap to [-π, π]

        return amplitudes, phases


# ═══════════════════════════════════════════════════════════════════════════
# DATA GENERATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def write_csv(filepath: str, packets: list):
    """
    Write packets to CSV in the exact same format as radar_graph.py --raw-log.
    
    Format: timestamp, label, motion_index, amp_0..amp_51, phase_0..phase_51
    """
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header — must match RawCSILogger in radar_graph.py exactly
        amp_cols = [f"amp_{i}" for i in range(NORMALIZED_SUBCARRIER_COUNT)]
        phase_cols = [f"phase_{i}" for i in range(NORMALIZED_SUBCARRIER_COUNT)]
        writer.writerow(["timestamp", "label", "motion_index"] + amp_cols + phase_cols)

        for pkt in packets:
            row = [f"{pkt['timestamp']:.4f}",
                   pkt['label'],
                   f"{pkt['motion_index']:.4f}"]
            row += [f"{v:.4f}" for v in pkt['amplitudes']]
            row += [f"{v:.4f}" for v in pkt['phases']]
            writer.writerow(row)

    print(f"  [+] Saved {len(packets)} packets to: {filepath}")


def compute_simple_motion_index(amplitudes: np.ndarray, 
                                 prev_amplitudes: np.ndarray) -> float:
    """Compute a simple motion index based on amplitude change."""
    if prev_amplitudes is None:
        return 0.0
    diff = np.abs(amplitudes - prev_amplitudes)
    return float(np.mean(diff))


def generate_training_data(output_dir: str = ".", duration_s: float = 180.0,
                           seed: int = 42):
    """
    Generate separate training files for 'empty' and 'walking' classes.
    
    Args:
        output_dir: Where to save the CSVs
        duration_s: Duration of each class in seconds (default: 180 = 3 min)
        seed: Random seed
    """
    print("\n" + "=" * 60)
    print("  Generating TRAINING data")
    print("=" * 60)

    sim = CSISimulator(seed=seed)
    dt = 1.0 / PACKET_RATE

    # ── Generate EMPTY data ──────────────────────────────────────────
    print(f"\n  Generating 'empty' data ({duration_s:.0f}s, ~{int(duration_s * PACKET_RATE)} packets)...")
    empty_packets = []
    prev_amp = None
    for i in range(int(duration_s * PACKET_RATE)):
        t = i * dt
        amp, phase = sim.generate_packet(t, 'empty')
        mi = compute_simple_motion_index(amp, prev_amp)
        empty_packets.append({
            'timestamp': t,
            'label': 'empty',
            'motion_index': mi,
            'amplitudes': amp,
            'phases': phase,
        })
        prev_amp = amp.copy()

    write_csv(os.path.join(output_dir, "synthetic_empty.csv"), empty_packets)

    # ── Generate WALKING data ────────────────────────────────────────
    print(f"\n  Generating 'walking' data ({duration_s:.0f}s, ~{int(duration_s * PACKET_RATE)} packets)...")
    sim_walk = CSISimulator(seed=seed + 1)
    walking_packets = []
    prev_amp = None

    for i in range(int(duration_s * PACKET_RATE)):
        t = i * dt
        # Vary walking speed slightly over time (realistic human behavior)
        speed = 0.7 + 0.6 * abs(math.sin(t * 0.1))
        gait_freq = 1.5 + 0.6 * abs(math.sin(t * 0.05))

        amp, phase = sim_walk.generate_packet(t, 'walking',
                                               walking_params={
                                                   'speed': speed,
                                                   'gait_freq': gait_freq
                                               })
        mi = compute_simple_motion_index(amp, prev_amp)
        walking_packets.append({
            'timestamp': t,
            'label': 'walking',
            'motion_index': mi,
            'amplitudes': amp,
            'phases': phase,
        })
        prev_amp = amp.copy()

    write_csv(os.path.join(output_dir, "synthetic_walking.csv"), walking_packets)

    print(f"\n  Training data ready! You can now train with:")
    print(f"    python train_model.py --data synthetic_empty.csv synthetic_walking.csv")
    print(f"    python train_model.py --data synthetic_empty.csv synthetic_walking.csv --differential")


def generate_demo_scenario(output_dir: str = ".", seed: int = 42):
    """
    Generate a scripted demo scenario file for presentation playback.

    Scenario timeline (total ~2 minutes):
      0:00 - 0:25   EMPTY    (Room is calm, AI shows green)
      0:25 - 0:55   WALKING  (Person walks in, AI detects motion)
      0:55 - 1:10   EMPTY    (Person leaves, calm again)
      1:10 - 1:30   WEAPON   (Shadow weapon activates -- RF attack!)
      1:30 - 1:50   EMPTY    (Weapon off, system recovers)
      1:50 - 2:00   WALKING  (Final walking demo -- AI still works)

    This creates a compelling narrative:
      "Detection -> Attack -> Defense -> Recovery"
    """
    print("\n" + "=" * 60)
    print("  Generating DEMO SCENARIO")
    print("=" * 60)

    # Define the scenario timeline
    scenario = [
        {'label': 'empty',   'duration': 25.0,  'desc': 'Room empty -- baseline'},
        {'label': 'walking', 'duration': 30.0,  'desc': 'Person walking -- AI detects'},
        {'label': 'empty',   'duration': 15.0,  'desc': 'Person leaves -- calm again'},
        {'label': 'weapon',  'duration': 20.0,  'desc': 'WEAPON ATTACK -- RF interference'},
        {'label': 'empty',   'duration': 20.0,  'desc': 'Weapon off -- system recovers'},
        {'label': 'walking', 'duration': 10.0,  'desc': 'Final walking -- AI still works'},
    ]

    total_duration = sum(s['duration'] for s in scenario)
    print(f"\n  Scenario duration: {total_duration:.0f}s ({total_duration/60:.1f} min)")
    print()

    for i, seg in enumerate(scenario):
        t_start = sum(s['duration'] for s in scenario[:i])
        t_end = t_start + seg['duration']
        print(f"  {t_start:5.0f}s - {t_end:5.0f}s  [{seg['label']:8s}]  {seg['desc']}")

    sim = CSISimulator(seed=seed)
    dt = 1.0 / PACKET_RATE
    packets = []
    prev_amp = None
    global_t = 0.0

    for segment in scenario:
        label = segment['label']
        duration = segment['duration']
        num_packets = int(duration * PACKET_RATE)

        for i in range(num_packets):
            t = global_t + i * dt

            if label == 'walking':
                speed = 0.8 + 0.4 * abs(math.sin(t * 0.15))
                gait_freq = 1.6 + 0.4 * math.sin(t * 0.08)
                amp, phase = sim.generate_packet(t, 'walking',
                                                  walking_params={
                                                      'speed': speed,
                                                      'gait_freq': gait_freq
                                                  })
            elif label == 'weapon':
                amp, phase = sim.generate_packet(t, 'weapon')
            else:
                amp, phase = sim.generate_packet(t, 'empty')

            mi = compute_simple_motion_index(amp, prev_amp)
            packets.append({
                'timestamp': t,
                'label': label,
                'motion_index': mi,
                'amplitudes': amp,
                'phases': phase,
            })
            prev_amp = amp.copy()

        global_t += duration

    write_csv(os.path.join(output_dir, "demo_scenario.csv"), packets)

    print(f"\n  Demo scenario ready! Playback with:")
    print(f"    python radar_graph.py --playback demo_scenario.csv --ai")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PROJECT SHADOW -- Synthetic CSI Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  training  -- Generate separate empty + walking CSVs for neural network training
  demo      -- Generate a scripted scenario file for presentation playback
  all       -- Generate both training data and demo scenario

Examples:
  python generate_synthetic_data.py --mode training
  python generate_synthetic_data.py --mode demo
  python generate_synthetic_data.py --mode all --duration 120
        """,
    )
    parser.add_argument("--mode", choices=["training", "demo", "all"],
                        default="all", help="What to generate (default: all)")
    parser.add_argument("--duration", type=float, default=180.0,
                        help="Training data duration per class in seconds (default: 180)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory to save generated files")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")

    args = parser.parse_args()

    print("=" * 60)
    print("  PROJECT SHADOW -- Synthetic CSI Data Generator")
    print("=" * 60)
    print(f"  Mode: {args.mode}")
    print(f"  Output directory: {os.path.abspath(args.output_dir)}")
    print(f"  Seed: {args.seed}")

    if args.mode in ("training", "all"):
        generate_training_data(args.output_dir, args.duration, args.seed)

    if args.mode in ("demo", "all"):
        generate_demo_scenario(args.output_dir, args.seed)

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
