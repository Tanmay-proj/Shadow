#!/usr/bin/env python3
"""
PROJECT SHADOW — Real-Time Wi-Fi CSI Motion Radar Graph
========================================================

Reads CSI (Channel State Information) data from an ESP32 receiver board
via serial port, computes a motion index, and displays a live scrolling
graph. Flat line = empty room. Spikes = movement detected.

Compatible with StevenMHernandez/ESP32-CSI-Tool output format.

Usage:
    python radar_graph.py --port COM5 --baud 115200
    python radar_graph.py --port COM5 --baud 115200 --window 20
    python radar_graph.py --test   (synthetic data mode, no hardware needed)
    python radar_graph.py --ai     (enable AI classification using trained model)
    python radar_graph.py --raw-log raw_csi_data.csv  (save raw CSI for training)

Author: PROJECT SHADOW
"""

import argparse
import sys
import time
import math
import random
import collections
import numpy as np
import threading
import queue
import os
import csv

# Optional AI/ML dependencies — only needed if --ai flag is used
try:
    import joblib
except ImportError:
    joblib = None

try:
    import torch
    import torch.nn as nn
except ImportError:
    torch = None

# ---------------------------------------------------------------------------
# Try importing optional dependencies — give clear errors if missing
# ---------------------------------------------------------------------------
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

try:
    import matplotlib
    matplotlib.use("TkAgg")  # Use TkAgg backend for live updating
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    from matplotlib.ticker import MaxNLocator
except ImportError:
    print("ERROR: matplotlib is required. Install with: pip install matplotlib")
    sys.exit(1)

try:
    import scipy.signal as sig_proc
    from sklearn.decomposition import PCA
    import pandas as pd
except ImportError:
    print("ERROR: Advanced math libraries missing. Install with: pip install scipy scikit-learn pandas")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_PORT = "COM5"
DEFAULT_BAUD = 115200
DEFAULT_WINDOW = 3         # Rolling average window (very short for instant response)
GRAPH_HISTORY = 150        # Number of data points visible on the graph
UPDATE_INTERVAL_MS = 150   # Graph refresh rate (ms) — higher = smoother rendering
TEMPORAL_WINDOW = 50       # Number of recent packets for PCA and Filtering
MOTION_CONSECUTIVE_HITS = 3  # Must exceed threshold this many times in a row to trigger
CSI_DATA_PREFIX = "CSI_DATA"  # Line prefix in ESP32-CSI-Tool output

# Adaptive threshold parameters
CALIBRATION_MIN_DURATION_S = 15.0    # Minimum calibration time (seconds)
CALIBRATION_MAX_DURATION_S = 60.0    # Max calibration time before forcing completion
CALIBRATION_STABILITY_WINDOW = 10    # Check last N values for stability
CALIBRATION_STABILITY_THRESHOLD = 0.15  # CoV (coefficient of variation) below this = stable
ADAPTIVE_DECAY = 0.995          # Exponential decay for adaptive baseline (slow drift)
ADAPTIVE_SENSITIVITY = 5.0     # Multiplier above calm noise for threshold
PCA_REFIT_INTERVAL_S = 300.0   # Refit PCA every 5 minutes during calm periods

# Guard-band fraction: skip this fraction of subcarriers on each edge
GUARD_BAND_FRACTION = 0.10     # Skip ~10% on each side

# Number of subcarriers to normalize to (for consistent neural network input)
NORMALIZED_SUBCARRIER_COUNT = 52

# Neural network parameters
NEURAL_CONFIDENCE_THRESHOLD = 0.75  # Below this confidence, fall back to classical DSP


# ═══════════════════════════════════════════════════════════════════════════
# CSI PARSER (ADAPTIVE)
# ═══════════════════════════════════════════════════════════════════════════

def parse_csi_line(line: str):
    """
    Parse a single CSI_DATA line from the ESP32-CSI-Tool.

    ADAPTIVE: Automatically detects the number of subcarriers from the data
    length rather than using hardcoded constants. Applies a guard-band
    fraction to skip noisy edge subcarriers.

    Returns:
        tuple of (amplitudes, phases, metadata_dict) or (None, None, None).
    """
    try:
        if CSI_DATA_PREFIX not in line:
            return None, None, None

        # Extract metadata fields before the brackets
        bracket_start = line.index("[")
        bracket_end = line.index("]")

        # Parse metadata (comma-separated fields before the bracket)
        meta_part = line[:bracket_start]
        meta_fields = [f.strip() for f in meta_part.split(",")]

        metadata = {}
        if len(meta_fields) >= 3:
            metadata['mac'] = meta_fields[1] if len(meta_fields) > 1 else ''
            try:
                metadata['rssi'] = int(meta_fields[2]) if len(meta_fields) > 2 else 0
            except (ValueError, TypeError):
                metadata['rssi'] = 0
            try:
                metadata['channel'] = int(meta_fields[14]) if len(meta_fields) > 14 else 0
            except (ValueError, TypeError):
                metadata['channel'] = 0

        # Parse the CSI data inside square brackets
        csi_string = line[bracket_start + 1: bracket_end]

        # Handle both space-separated and comma-separated formats
        if ',' in csi_string:
            csi_raw = [int(x.strip()) for x in csi_string.split(',') if x.strip()]
        else:
            csi_raw = [int(x.strip()) for x in csi_string.split() if x.strip()]

        if len(csi_raw) < 16:
            return None, None, None

        # ── Adaptive header detection ──────────────────────────────────
        # The ESP32-CSI-Tool typically prepends metadata bytes.
        # Common layouts:
        #   - 128 values total -> LLTF only (HT20), 12 header + 116 payload (58 subcarriers)
        #   - 256 values total -> LLTF+HT-LTF (HT40), header varies
        #   - Other lengths    -> try to detect by checking if early bytes look like scale/header
        #
        # Heuristic: Try header sizes [0, 4, 8, 12] and pick the one that gives
        # the cleanest subcarrier count (even number for I/Q pairs, reasonable range)

        best_header = 0
        best_sc_count = 0
        for h in [0, 4, 8, 12]:
            payload_len = len(csi_raw) - h
            if payload_len >= 8 and payload_len % 2 == 0:
                sc = payload_len // 2
                if 20 <= sc <= 128:  # Reasonable subcarrier count
                    if sc > best_sc_count:
                        best_sc_count = sc
                        best_header = h

        # Fallback: if nothing matched, try 12-byte header
        if best_sc_count == 0:
            best_header = 12
            payload_len = len(csi_raw) - best_header
            if payload_len < 4 or payload_len % 2 != 0:
                return None, None, None
            best_sc_count = payload_len // 2

        csi_payload = csi_raw[best_header:]
        num_subcarriers = best_sc_count

        # ── Compute amplitudes and phases ──────────────────────────────
        amplitudes = np.zeros(num_subcarriers)
        phases = np.zeros(num_subcarriers)

        for i in range(num_subcarriers):
            imag = csi_payload[2 * i]
            real = csi_payload[2 * i + 1]
            amplitudes[i] = math.sqrt(imag * imag + real * real)
            phases[i] = math.atan2(imag, real)

        # ── Adaptive guard-band trimming ───────────────────────────────
        guard = max(1, int(num_subcarriers * GUARD_BAND_FRACTION))
        start = guard
        end = num_subcarriers - guard

        if end <= start:
            return amplitudes, phases, metadata

        metadata['num_subcarriers_raw'] = num_subcarriers
        metadata['num_subcarriers_used'] = end - start
        metadata['header_bytes'] = best_header

        return amplitudes[start:end], phases[start:end], metadata

    except (ValueError, IndexError):
        return None, None, None


def normalize_subcarriers(data: np.ndarray, target_length: int = NORMALIZED_SUBCARRIER_COUNT) -> np.ndarray:
    """
    Resample a subcarrier array to a fixed length via linear interpolation.
    This ensures consistent feature dimensions regardless of hardware config.
    """
    if len(data) == target_length:
        return data
    if len(data) == 0:
        return np.zeros(target_length)
    x_old = np.linspace(0, 1, len(data))
    x_new = np.linspace(0, 1, target_length)
    return np.interp(x_new, x_old, data)


def sanitize_phase(phases: np.ndarray) -> np.ndarray:
    """
    Remove Carrier Frequency Offset (CFO) and Sampling Frequency Offset (SFO)
    by subtracting the linear trend from the unwrapped phase.
    """
    try:
        unwrapped = np.unwrap(phases)
        x = np.arange(len(unwrapped))
        m, c = np.polyfit(x, unwrapped, 1)
        sanitized = unwrapped - (m * x + c)
        return sanitized
    except (np.linalg.LinAlgError, ValueError, FloatingPointError):
        # Fallback: return raw unwrapped phase if linear fit fails
        # (happens when all phase values are identical, e.g., during startup)
        return np.unwrap(phases)


# Pre-compute Butterworth Low-Pass Filter coefficients
# Cut-off at ~3Hz to capture human motion, remove static
BUTTER_B, BUTTER_A = sig_proc.butter(3, 0.4, btype='low')

def compute_advanced_motion_index(amp_history: collections.deque,
                                   phase_history: collections.deque,
                                   pca_model: PCA = None) -> float:
    """
    Advanced DSP Pipeline:
    1. Applies Butterworth Low-Pass Filter to smooth out electrical static.
    2. Applies PCA to fuse subcarriers (amplitude + phase) into 1 clean signal.
    """
    if len(amp_history) < 20:
        return 0.0

    amp_matrix = np.array(list(amp_history))
    phase_matrix = np.array(list(phase_history))

    # Normalize to consistent dimensions
    if amp_matrix.shape[1] != NORMALIZED_SUBCARRIER_COUNT:
        amp_matrix = np.array([normalize_subcarriers(row) for row in amp_matrix])
        phase_matrix = np.array([normalize_subcarriers(row) for row in phase_matrix])

    joint_matrix = np.hstack((amp_matrix, phase_matrix))

    try:
        filtered_joint = sig_proc.filtfilt(BUTTER_B, BUTTER_A, joint_matrix, axis=0)

        if pca_model is None:
            pca = PCA(n_components=1)
            principal_components = pca.fit_transform(filtered_joint)
        else:
            principal_components = pca_model.transform(filtered_joint)

        return float(np.var(principal_components))
    except Exception:
        return float(np.mean(np.var(joint_matrix, axis=0)))


# ═══════════════════════════════════════════════════════════════════════════
# NEURAL NETWORK MODEL DEFINITION (must match train_model.py)
# ═══════════════════════════════════════════════════════════════════════════

class CSINet(nn.Module):
    """
    1D Convolutional Neural Network for CSI-based motion classification.
    Input: (batch, 1, window_size * NORMALIZED_SUBCARRIER_COUNT * 2)
    Output: (batch, num_classes)
    """
    def __init__(self, input_size, num_classes=2):
        super(CSINet, self).__init__()
        self.features = nn.Sequential(
            nn.Conv1d(1, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(2),

            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(2),

            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(8),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128 * 8, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = self.classifier(x)
        return x

# Neural inference window size (must match training)
NEURAL_WINDOW = 20  # Number of recent packets for neural input


# ═══════════════════════════════════════════════════════════════════════════
# SERIAL READER (with reconnection)
# ═══════════════════════════════════════════════════════════════════════════

class SerialCSIReader:
    """Reads CSI data lines from the ESP32 serial port asynchronously."""

    def __init__(self, port: str, baud: int):
        if serial is None:
            print("ERROR: pyserial is required. Install with: pip install pyserial")
            sys.exit(1)

        self.port = port
        self.baud = baud
        self.ser = None
        self.data_queue = queue.Queue(maxsize=500)
        self.running = False
        self.thread = None
        self.stats = {'total_lines': 0, 'parse_errors': 0, 'reconnects': 0}

    def connect(self):
        """Open the serial connection and start background reader thread."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=0.5,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
            print(f"[RADAR] Connected to {self.port} at {self.baud} baud")
            self.ser.reset_input_buffer()

            self.running = True
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
            return True
        except serial.SerialException as e:
            print(f"[ERROR] Cannot open {self.port}: {e}")
            return False

    def _try_reconnect(self):
        """Attempt to reconnect to the serial port after a disconnect."""
        self.stats['reconnects'] += 1
        print(f"[RADAR] Serial disconnected. Reconnecting... (attempt #{self.stats['reconnects']})")
        try:
            if self.ser:
                self.ser.close()
            time.sleep(1.0)
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=0.5,
            )
            self.ser.reset_input_buffer()
            print(f"[RADAR] Reconnected to {self.port}")
            return True
        except Exception:
            return False

    def _reader_loop(self):
        """Background loop reading lines from serial with auto-reconnect."""
        while self.running:
            try:
                if self.ser is None or not self.ser.is_open:
                    if not self._try_reconnect():
                        time.sleep(2.0)
                        continue

                raw = self.ser.readline()
                if raw:
                    self.stats['total_lines'] += 1
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        if self.data_queue.full():
                            try:
                                self.data_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self.data_queue.put(line)
            except (serial.SerialException, OSError):
                if self.running:
                    if not self._try_reconnect():
                        time.sleep(2.0)
            except Exception:
                pass

    def read_line(self) -> str:
        """Non-blocking fetch of next available line."""
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return ""

    def close(self):
        """Close the serial connection and stop background thread."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[RADAR] Serial port closed.")


# ═══════════════════════════════════════════════════════════════════════════
# SYNTHETIC DATA GENERATOR (for testing without hardware)
# ═══════════════════════════════════════════════════════════════════════════

class SyntheticCSIReader:
    """
    Generates fake CSI data for testing the graph without ESP32 hardware.
    Simulates: 10s calm -> 5s motion -> 10s calm -> 5s motion (repeating).
    """

    def __init__(self):
        self.start_time = time.time()
        self.packet_counter = 0
        self.stats = {'total_lines': 0, 'parse_errors': 0, 'reconnects': 0}

    def connect(self):
        print("[RADAR] Synthetic data mode -- no hardware required")
        print("[RADAR] Pattern: 10s calm -> 5s motion -> repeat")
        return True

    def read_line(self) -> str:
        """Generate a synthetic CSI_DATA line."""
        time.sleep(0.02)  # ~50 packets/sec
        self.packet_counter += 1
        self.stats['total_lines'] += 1

        elapsed = time.time() - self.start_time
        cycle = elapsed % 15.0

        if cycle < 10.0:
            base, noise_level = 30.0, 2.0
        else:
            base, noise_level = 30.0, 15.0

        num_sc = 52
        header = [0] * 12
        amplitudes = []
        for i in range(num_sc):
            if cycle >= 10.0:
                phase = (i * 0.3) + (elapsed * 5.0) + random.gauss(0, noise_level / 10.0)
            else:
                phase = (i * 0.3) + random.gauss(0, noise_level / 10.0)

            amp = base + random.gauss(0, noise_level)
            imag = int(amp * math.sin(phase))
            real = int(amp * math.cos(phase))
            amplitudes.extend([imag, real])

        all_data = header + amplitudes
        csi_str = " ".join(str(x) for x in all_data)
        return f"CSI_DATA,STA,aa:bb:cc:dd:ee:ff,-50,11,0,0,0,0,0,0,0,0,0,-90,0,6,0,{self.packet_counter},0,0,0,0,0.0,{len(all_data)},[{csi_str} ]"

    def close(self):
        print("[RADAR] Synthetic data source closed.")


class InteractiveCSIReader:
    """
    Real-time interactive synthetic CSI generator controlled via hidden keyboard keys:
      '1' -> Empty room (calm baseline)
      '2' -> Human walking motion (gait Doppler + phase modulation)
      '3' -> Weapon / RF interference attack (chaotic noise + frequency spikes)
    """

    def __init__(self):
        self.start_time = time.time()
        self.packet_counter = 0
        self.stats = {'total_lines': 0, 'parse_errors': 0, 'reconnects': 0}
        self.current_state = 'empty'
        self.rng = np.random.RandomState(42)
        self.sc_count = NORMALIZED_SUBCARRIER_COUNT

        # Static baseline channel profile
        self.base_amplitude = self.rng.uniform(28.0, 38.0, self.sc_count)
        self.base_phase = self.rng.uniform(-np.pi, np.pi, self.sc_count)

        center = self.sc_count // 2
        self.sensitivity = np.exp(
            -0.5 * ((np.arange(self.sc_count) - center) / (self.sc_count * 0.3)) ** 2
        )
        self.drift_rate = self.rng.uniform(0.001, 0.005, self.sc_count)
        self.drift_phase = self.rng.uniform(0, 2 * np.pi, self.sc_count)

    def connect(self):
        print("[RADAR] Interactive mode active (Use keyboard: 1=Empty, 2=Walking, 3=Weapon)")
        return True

    def set_state(self, state: str):
        if state in ['empty', 'walking', 'weapon']:
            self.current_state = state

    def read_line(self) -> str:
        """Generate an interactive CSI packet at ~50 pkts/s."""
        time.sleep(0.02)
        self.packet_counter += 1
        self.stats['total_lines'] += 1
        now = time.time() - self.start_time

        drift = 0.3 * np.sin(self.drift_rate * now * 2 * np.pi + self.drift_phase)
        amplitudes = self.base_amplitude.copy() + drift
        phases = self.base_phase.copy() + 0.02 * np.sin(0.01 * now * 2 * np.pi + self.drift_phase)

        # Thermal noise
        amplitudes += self.rng.normal(0, 0.8, self.sc_count)
        phases += self.rng.normal(0, 0.05, self.sc_count)

        if self.current_state == 'walking':
            gait_freq = 1.8
            for sc in range(self.sc_count):
                gait_mod = self.sensitivity[sc] * 8.0 * math.sin(2 * math.pi * gait_freq * now + sc * 0.15)
                harmonic = self.sensitivity[sc] * 3.0 * math.sin(2 * math.pi * gait_freq * 2 * now + sc * 0.3 + 1.2)
                arm_mod = self.sensitivity[sc] * 2.0 * math.sin(2 * math.pi * gait_freq * 0.5 * now + sc * 0.08 + 0.7)
                amplitudes[sc] += gait_mod + harmonic + arm_mod
                phases[sc] += self.sensitivity[sc] * 0.4 * math.sin(2 * math.pi * gait_freq * now + sc * 0.2 + 0.5)
            amplitudes += self.rng.normal(0, 1.5, self.sc_count)
            phases += self.rng.normal(0, 0.1, self.sc_count)

        elif self.current_state == 'weapon':
            spike_strength = self.rng.uniform(6, 24, self.sc_count)
            spike_pattern = np.sin(2 * np.pi * self.rng.uniform(10, 50) * now + self.rng.uniform(0, 2 * np.pi, self.sc_count))
            amplitudes += spike_strength * spike_pattern
            phases += self.rng.uniform(-np.pi, np.pi, self.sc_count) * 0.3
            if self.rng.random() > 0.7:
                burst_sc = self.rng.randint(0, self.sc_count, size=self.rng.randint(5, 20))
                amplitudes[burst_sc] += self.rng.uniform(10, 30, len(burst_sc))

        amplitudes = np.clip(amplitudes, 1.0, 80.0)

        header = [0] * 12
        iq_data = []
        for i in range(self.sc_count):
            amp = amplitudes[i]
            phase = phases[i]
            imag = int(amp * math.sin(phase))
            real = int(amp * math.cos(phase))
            iq_data.extend([imag, real])

        all_data = header + iq_data
        csi_str = " ".join(str(x) for x in all_data)
        return (f"CSI_DATA,STA,aa:bb:cc:dd:ee:ff,-50,11,0,0,0,0,0,0,0,0,0,"
                f"-90,0,6,0,{self.packet_counter},0,0,0,0,0.0,"
                f"{len(all_data)},[{csi_str} ]")

    def close(self):
        print("[RADAR] Interactive data source closed.")


class PlaybackCSIReader:
    """
    Replays a pre-recorded CSV file (from --raw-log or generate_synthetic_data.py)
    as if it were live serial input. The rest of the pipeline (parser, DSP, PCA,
    neural network, UI) works identically — it can't tell the difference.

    This enables:
      1. Software-only demos (no ESP32 hardware needed)
      2. Fail-safe presentations (zero risk of hardware failure on stage)
      3. Later hardware integration (just swap --playback for --port COM8)
    """

    def __init__(self, csv_path: str, speed: float = 1.0, loop: bool = False):
        """
        Args:
            csv_path: Path to CSV file (from --raw-log or generate_synthetic_data.py)
            speed: Playback speed multiplier (1.0 = real-time, 2.0 = 2x fast)
            loop: If True, restart from beginning when file ends
        """
        self.csv_path = csv_path
        self.speed = max(0.1, speed)
        self.loop = loop
        self.rows = []
        self.current_idx = 0
        self.start_time = None
        self.first_timestamp = None
        self.stats = {'total_lines': 0, 'parse_errors': 0, 'reconnects': 0}
        self.finished = False

    def connect(self):
        """Load the CSV file into memory."""
        if not os.path.exists(self.csv_path):
            print(f"[ERROR] Playback file not found: {self.csv_path}")
            return False

        try:
            df = pd.read_csv(self.csv_path)
        except Exception as e:
            print(f"[ERROR] Cannot read playback file: {e}")
            return False

        # Validate required columns
        amp_cols = [c for c in df.columns if c.startswith("amp_")]
        phase_cols = [c for c in df.columns if c.startswith("phase_")]

        if 'timestamp' not in df.columns or not amp_cols or not phase_cols:
            print(f"[ERROR] Playback file missing required columns.")
            print(f"  Need: timestamp, amp_0..amp_N, phase_0..phase_N")
            print(f"  Got:  {list(df.columns[:5])}...")
            return False

        # Store rows for playback (vectorized for speed)
        timestamps = df['timestamp'].values.astype(float)
        amp_matrix = df[amp_cols].values.astype(float)
        phase_matrix = df[phase_cols].values.astype(float)
        labels_col = df['label'].values if 'label' in df.columns else ['unknown'] * len(df)

        self.rows = []
        for i in range(len(timestamps)):
            self.rows.append({
                'timestamp': timestamps[i],
                'amplitudes': amp_matrix[i].tolist(),
                'phases': phase_matrix[i].tolist(),
                'label': str(labels_col[i]),
            })

        self.first_timestamp = self.rows[0]['timestamp'] if self.rows else 0.0
        self.start_time = time.time()
        self.current_idx = 0

        label_str = ''
        if 'label' in df.columns:
            labels = df['label'].unique()
            label_str = f", labels: {list(labels)}"

        print(f"[RADAR] >> PLAYBACK MODE -- {self.csv_path}")
        print(f"[RADAR]   {len(self.rows)} packets{label_str}")
        duration = self.rows[-1]['timestamp'] - self.first_timestamp if len(self.rows) > 1 else 0
        print(f"[RADAR]   Duration: {duration:.1f}s, Speed: {self.speed}x")
        print(f"[RADAR]   Loop: {'ON' if self.loop else 'OFF'}")
        return True

    def _row_to_csi_line(self, row: dict) -> str:
        """
        Convert a CSV row back into a CSI_DATA format line that
        parse_csi_line() can understand. This is the key trick that
        makes the entire downstream pipeline work unchanged.
        """
        num_sc = len(row['amplitudes'])

        # Reconstruct I/Q pairs from amplitude and phase
        # CSI raw format: [header_bytes...] [imag_0, real_0, imag_1, real_1, ...]
        header = [0] * 12  # 12 header bytes (typical ESP32)
        iq_data = []
        for i in range(num_sc):
            amp = row['amplitudes'][i]
            phase = row['phases'][i]
            imag = int(amp * math.sin(phase))
            real = int(amp * math.cos(phase))
            iq_data.extend([imag, real])

        all_data = header + iq_data
        csi_str = " ".join(str(x) for x in all_data)

        # Build a fake but valid CSI_DATA line
        self.stats['total_lines'] += 1
        return (f"CSI_DATA,STA,aa:bb:cc:dd:ee:ff,-50,11,0,0,0,0,0,0,0,0,0,"
                f"-90,0,6,0,{self.stats['total_lines']},0,0,0,0,0.0,"
                f"{len(all_data)},[{csi_str} ]")

    def read_line(self) -> str:
        """Return the next CSI line at the correct playback timing."""
        if self.finished or not self.rows:
            time.sleep(0.1)  # Don't spin CPU when done
            return ""

        if self.current_idx >= len(self.rows):
            if self.loop:
                self.current_idx = 0
                self.start_time = time.time()
                print("[RADAR] >> Playback looping...")
            else:
                if not self.finished:
                    print("[RADAR] [DONE] Playback finished.")
                    self.finished = True
                return ""

        row = self.rows[self.current_idx]

        # Wait until the correct time to emit this packet
        row_time = (row['timestamp'] - self.first_timestamp) / self.speed
        elapsed = time.time() - self.start_time

        if elapsed < row_time:
            sleep_time = min(row_time - elapsed, 0.05)  # Don't sleep too long
            time.sleep(sleep_time)
            if time.time() - self.start_time < row_time:
                return ""  # Not ready yet, return empty

        self.current_idx += 1
        return self._row_to_csi_line(row)

    def close(self):
        print(f"[RADAR] Playback source closed. {self.stats['total_lines']} packets replayed.")


# ═══════════════════════════════════════════════════════════════════════════
# RAW CSI LOGGER
# ═══════════════════════════════════════════════════════════════════════════

class RawCSILogger:
    """
    Logs raw (normalized) amplitude and phase vectors to CSV for
    offline analysis and neural network training.

    Format: timestamp, label, amp_0, amp_1, ..., amp_51, phase_0, ..., phase_51
    """

    def __init__(self, filepath: str, label: str = "unlabeled"):
        self.label = label
        self.file = open(filepath, "w", newline="")
        self.writer = csv.writer(self.file)

        # Header row
        amp_cols = [f"amp_{i}" for i in range(NORMALIZED_SUBCARRIER_COUNT)]
        phase_cols = [f"phase_{i}" for i in range(NORMALIZED_SUBCARRIER_COUNT)]
        self.writer.writerow(["timestamp", "label", "motion_index"] + amp_cols + phase_cols)

        self.count = 0
        print(f"[RADAR] Raw CSI logging to: {filepath} (label: {label})")

    def log(self, timestamp: float, label: str, motion_index: float,
            amplitudes: np.ndarray, phases: np.ndarray):
        """Log one packet of normalized CSI data."""
        amp_norm = normalize_subcarriers(amplitudes)
        phase_norm = normalize_subcarriers(phases)

        row = [f"{timestamp:.4f}", label, f"{motion_index:.4f}"]
        row += [f"{v:.4f}" for v in amp_norm]
        row += [f"{v:.4f}" for v in phase_norm]

        self.writer.writerow(row)
        self.count += 1

        # Flush every 50 rows
        if self.count % 50 == 0:
            self.file.flush()

    def close(self):
        self.file.flush()
        self.file.close()
        print(f"[RADAR] Raw CSI log closed. {self.count} packets saved.")


# ═══════════════════════════════════════════════════════════════════════════
# LIVE GRAPH
# ═══════════════════════════════════════════════════════════════════════════

class RadarGraph:
    """
    Real-time scrolling matplotlib graph showing the motion index over time.
    """

    def __init__(self, reader, window_size=DEFAULT_WINDOW, record_label=None,
                 ai_enabled=False, raw_log_path=None):
        self.reader = reader
        self.record_file = None
        self.ai_enabled = ai_enabled
        self.neural_model = None
        self.raw_logger = None
        self.is_playback = isinstance(reader, PlaybackCSIReader)

        # ── Neural AI model loading ──────────────────────────────────
        if self.ai_enabled:
            self._load_neural_model()

        # ── Recording mode (processed motion index) ──────────────────
        if record_label:
            fname = f"csi_features_{record_label}_{int(time.time())}.csv"
            self.record_file = open(fname, "w")
            self.record_file.write("timestamp,motion_index\n")
            print(f"[RADAR] Recording mode ON. Saving features to {fname}")

        # ── Raw CSI logging ──────────────────────────────────────────
        if raw_log_path:
            label = record_label or "unlabeled"
            self.raw_logger = RawCSILogger(raw_log_path, label=label)

        # ── Data buffers ─────────────────────────────────────────────
        self.smoothed_history = collections.deque(maxlen=GRAPH_HISTORY)
        self.time_history = collections.deque(maxlen=GRAPH_HISTORY)
        self.rolling_buffer = collections.deque(maxlen=window_size)

        # Temporal variance & advanced DSP buffers
        self.amp_history = collections.deque(maxlen=TEMPORAL_WINDOW)
        self.phase_history = collections.deque(maxlen=TEMPORAL_WINDOW)
        self.pca_model = None

        # Neural network input buffer (last N normalized packets)
        self.neural_amp_buffer = collections.deque(maxlen=NEURAL_WINDOW)
        self.neural_phase_buffer = collections.deque(maxlen=NEURAL_WINDOW)
        self.ai_pred_history = collections.deque(maxlen=5)  # Temporal smoothing / majority vote filter

        self.start_time = time.time()
        self.packet_count = 0
        self.last_motion_index = 0.0
        self.consecutive_detections = 0

        # ── Threshold calibration ────────────────────────────────────
        self.calibration_values = []
        self.calibration_done = False
        self.threshold = 999.0

        # Adaptive baseline tracking (updates slowly after calibration)
        self.adaptive_baseline = 0.0
        self.adaptive_threshold = 999.0

        # PCA periodic refit tracking
        self.last_pca_refit_time = 0.0
        self.calm_buffer_for_refit = []

        # ── Track last amplitudes/phases for raw logging ─────────────
        self.last_amplitudes = None
        self.last_phases = None

        # ── Setup the matplotlib figure ──────────────────────────────
        plt.style.use("dark_background")
        self.fig, self.ax_main = plt.subplots(1, 1, figsize=(12, 6))
        self.fig.patch.set_facecolor("#0a0a0a")
        self.fig.canvas.manager.set_window_title("PROJECT SHADOW -- Wi-Fi CSI Radar")

        self.ax_main.set_facecolor("#0d1117")
        self.ax_main.set_title(
            "SHADOW RADAR — Motion Index",
            fontsize=16, fontweight="bold", color="#58a6ff", pad=15,
        )
        self.ax_main.set_ylabel("Motion Index", fontsize=12, color="#c9d1d9")
        self.ax_main.set_xlabel("Time (seconds)", fontsize=12, color="#c9d1d9")
        self.ax_main.tick_params(colors="#8b949e")
        self.ax_main.grid(True, alpha=0.15, color="#30363d")

        (self.line_smooth,) = self.ax_main.plot(
            [], [], color="#58a6ff", linewidth=2.0, label="Motion",
        )
        (self.line_threshold,) = self.ax_main.plot(
            [], [], color="#f85149", linewidth=1.5, linestyle="--",
            alpha=0.8, label="Threshold",
        )

        self.ax_main.legend(loc="upper right", fontsize=9, framealpha=0.3)

        self.status_text = self.ax_main.text(
            0.02, 0.95, "", transform=self.ax_main.transAxes,
            fontsize=10, color="#8b949e", verticalalignment="top",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#161b22", alpha=0.8),
        )

        self.detection_text = self.ax_main.text(
            0.98, 0.95, "", transform=self.ax_main.transAxes,
            fontsize=14, fontweight="bold", verticalalignment="top",
            horizontalalignment="right",
        )

        plt.tight_layout(pad=2.0)

        # Hidden keyboard listener for interactive state control
        if hasattr(self.reader, 'set_state'):
            def _on_key_press(event):
                if event.key == '1':
                    self.reader.set_state('empty')
                elif event.key == '2':
                    self.reader.set_state('walking')
                elif event.key == '3':
                    self.reader.set_state('weapon')
            self.fig.canvas.mpl_connect('key_press_event', _on_key_press)

    def _load_neural_model(self):
        """Load the trained neural network model for real-time classification."""
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow_neural_model.pt")

        if torch is None:
            print("[RADAR] WARNING: PyTorch not installed. Run: pip install torch")
            print("[RADAR] Continuing without neural classification.")
            self.ai_enabled = False
            return

        if not os.path.exists(model_path):
            print(f"[RADAR] WARNING: Neural model not found at {model_path}")
            print("[RADAR] Train a model first with: python train_model.py")
            print("[RADAR] Continuing without neural classification.")
            self.ai_enabled = False
            return

        try:
            checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
            input_size = checkpoint.get('input_size', NEURAL_WINDOW * NORMALIZED_SUBCARRIER_COUNT * 2)
            num_classes = checkpoint.get('num_classes', 2)
            class_names = checkpoint.get('class_names', ['empty', 'walking'])
            self.use_differential = checkpoint.get('use_differential', False)

            self.neural_model = CSINet(input_size=input_size, num_classes=num_classes)
            self.neural_model.load_state_dict(checkpoint['model_state_dict'])
            self.neural_model.eval()
            self.neural_class_names = class_names

            diff_str = " (with differential features)" if self.use_differential else ""
            print(f"[RADAR] Neural model loaded: {num_classes} classes {class_names}{diff_str}")
            print(f"[RADAR] Model accuracy: {checkpoint.get('test_accuracy', 'N/A')}")
            print(f"[RADAR] Confidence gate: {NEURAL_CONFIDENCE_THRESHOLD:.0%} (below -> fallback to DSP)")
        except Exception as e:
            print(f"[RADAR] ERROR loading neural model: {e}")
            self.ai_enabled = False

    def _neural_classify(self) -> tuple:
        """
        Run neural network inference on the recent CSI buffer.
        Returns (label_string, confidence, is_confident).
        is_confident indicates whether the prediction passes the confidence gate.
        """
        if (self.neural_model is None or torch is None or
                len(self.neural_amp_buffer) < NEURAL_WINDOW):
            return ("", 0.0, False)

        try:
            # Build feature vector: (NEURAL_WINDOW × NORMALIZED_SUBCARRIER_COUNT × 2)
            amp_matrix = np.array(list(self.neural_amp_buffer))
            phase_matrix = np.array(list(self.neural_phase_buffer))
            features = np.concatenate([amp_matrix, phase_matrix], axis=1).flatten()

            # Add differential features if model was trained with them
            if getattr(self, 'use_differential', False):
                # Temporal differences: amp[i] - amp[i-1], phase[i] - phase[i-1]
                amp_diff = np.diff(amp_matrix, axis=0)   # (WINDOW-1, subcarriers)
                phase_diff = np.diff(phase_matrix, axis=0)
                diff_features = np.concatenate([amp_diff, phase_diff], axis=1).flatten()
                features = np.concatenate([features, diff_features])

            # Convert to tensor: (1, 1, features)
            x = torch.FloatTensor(features).unsqueeze(0).unsqueeze(0)

            with torch.no_grad():
                logits = self.neural_model(x)
                probs = torch.softmax(logits, dim=1)
                pred_class = torch.argmax(probs, dim=1).item()
                confidence = probs[0, pred_class].item()

            # Add to temporal history for majority voting
            self.ai_pred_history.append((pred_class, confidence))

            # Majority vote over the last N predictions to prevent gait zero-crossing flicker
            recent_classes = [c for c, _ in self.ai_pred_history]
            voted_class = collections.Counter(recent_classes).most_common(1)[0][0]
            voted_confs = [conf for c, conf in self.ai_pred_history if c == voted_class]
            avg_confidence = float(np.mean(voted_confs))

            class_name = self.neural_class_names[voted_class] if voted_class < len(self.neural_class_names) else f"class_{voted_class}"
            is_confident = avg_confidence >= NEURAL_CONFIDENCE_THRESHOLD

            label = f"AI: {class_name.upper()} ({avg_confidence:.0%})"
            return (label, avg_confidence, is_confident)
        except Exception:
            return ("", 0.0, False)

    def _fit_pca(self):
        """Fit (or refit) the PCA model using the current amplitude/phase history."""
        try:
            amp_matrix = np.array(list(self.amp_history))
            phase_matrix = np.array(list(self.phase_history))
            if len(amp_matrix) < 20:
                return
            joint_matrix = np.hstack((amp_matrix, phase_matrix))
            filtered_joint = sig_proc.filtfilt(BUTTER_B, BUTTER_A, joint_matrix, axis=0)
            self.pca_model = PCA(n_components=1)
            self.pca_model.fit(filtered_joint)
        except Exception as e:
            print(f"[RADAR] PCA fit warning: {e}")

    def _update(self, frame):
        """Animation update function — called every UPDATE_INTERVAL_MS."""

        lines_read = 0
        max_lines_per_frame = 10  # Increased for better throughput under heavy packet rates

        while lines_read < max_lines_per_frame:
            line = self.reader.read_line()
            if not line:
                break

            amplitudes, phases, metadata = parse_csi_line(line)
            if amplitudes is None:
                continue

            # Advanced DSP: Phase sanitization
            sanitized_phases = sanitize_phase(phases)

            # Normalize to consistent dimensions
            amp_norm = normalize_subcarriers(amplitudes)
            phase_norm = normalize_subcarriers(sanitized_phases)

            # Add to temporal window for advanced DSP
            self.amp_history.append(amp_norm.copy())
            self.phase_history.append(phase_norm.copy())

            # Add to neural buffer
            self.neural_amp_buffer.append(amp_norm.copy())
            self.neural_phase_buffer.append(phase_norm.copy())

            # Store for raw logging
            self.last_amplitudes = amplitudes
            self.last_phases = sanitized_phases

            # Compute motion via advanced DSP pipeline
            motion = compute_advanced_motion_index(
                self.amp_history, self.phase_history, self.pca_model)

            # Light smoothing
            self.rolling_buffer.append(motion)
            smoothed = float(np.mean(self.rolling_buffer))

            # ── Smart calibration ──────────────────────────────────────
            # Instead of blindly trusting 30s, we detect when the
            # environment is actually calm by checking variance stability.
            now = time.time() - self.start_time
            if not self.calibration_done:
                self.calibration_values.append(smoothed)

                # Check if we can finish calibration
                can_finish = False
                cal_min = 5.0 if self.is_playback else CALIBRATION_MIN_DURATION_S
                if now >= cal_min and len(self.calibration_values) >= CALIBRATION_STABILITY_WINDOW:
                    # Check stability: is the recent data consistent?
                    recent = self.calibration_values[-CALIBRATION_STABILITY_WINDOW:]
                    recent_mean = np.mean(recent)
                    recent_std = np.std(recent)
                    cov = recent_std / max(recent_mean, 0.01)  # Coefficient of Variation

                    if cov < CALIBRATION_STABILITY_THRESHOLD:
                        can_finish = True  # Environment is stable
                    elif now >= CALIBRATION_MAX_DURATION_S:
                        can_finish = True  # Timeout — use whatever we have
                        print("[RADAR] WARNING: Calibration forced (environment may not be fully calm)")

                if can_finish:
                    calm_mean = np.mean(self.calibration_values)
                    calm_std = np.std(self.calibration_values)
                    self.threshold = max(calm_mean * 3.0,
                                         calm_mean + ADAPTIVE_SENSITIVITY * calm_std,
                                         5.0)
                    self.adaptive_baseline = calm_mean
                    self.adaptive_threshold = self.threshold

                    # Fit initial PCA model
                    self._fit_pca()
                    self.last_pca_refit_time = now

                    print(f"[RADAR] Calibration done at {now:.0f}s. "
                          f"Calm noise: {calm_mean:.2f}, Threshold: {self.threshold:.2f}")
                    self.calibration_done = True

            # ── Adaptive threshold + periodic PCA refit ───────────────
            elif self.calibration_done:
                # Slowly track the noise floor during calm periods
                if smoothed < self.adaptive_threshold:
                    self.adaptive_baseline = (ADAPTIVE_DECAY * self.adaptive_baseline +
                                              (1 - ADAPTIVE_DECAY) * smoothed)
                    self.adaptive_threshold = max(
                        self.adaptive_baseline * 3.0,
                        self.adaptive_baseline + ADAPTIVE_SENSITIVITY * max(np.std(list(self.rolling_buffer)), 1.0),
                        5.0
                    )
                    self.threshold = self.adaptive_threshold

                    # Collect calm data for periodic PCA refit
                    self.calm_buffer_for_refit.append(smoothed)

                # Periodic PCA refit during calm periods
                if (now - self.last_pca_refit_time > PCA_REFIT_INTERVAL_S
                        and len(self.calm_buffer_for_refit) > 30):
                    self._fit_pca()
                    self.last_pca_refit_time = now
                    self.calm_buffer_for_refit.clear()
                    print(f"[RADAR] PCA model refitted at {now:.0f}s")

            # ── Logging ───────────────────────────────────────────────
            if self.record_file and self.calibration_done:
                self.record_file.write(f"{now:.3f},{smoothed:.4f}\n")
                self.record_file.flush()

            if self.raw_logger and self.calibration_done:
                label = self.raw_logger.label
                self.raw_logger.log(now, label, smoothed,
                                    self.last_amplitudes, self.last_phases)

            self.smoothed_history.append(smoothed)
            self.time_history.append(now)
            self.packet_count += 1
            self.last_motion_index = smoothed
            lines_read += 1

        # ── Update the plot ───────────────────────────────────────────
        # Show playback complete indicator
        if self.is_playback and getattr(self.reader, 'finished', False) and len(self.time_history) > 2:
            self.detection_text.set_text("[PLAYBACK COMPLETE]")
            self.detection_text.set_color("#58a6ff")
            return (self.line_smooth, self.status_text, self.detection_text)

        if len(self.time_history) < 2:
            return (self.line_smooth, self.status_text, self.detection_text)

        times = list(self.time_history)
        smooth_vals = list(self.smoothed_history)

        # Detect motion state
        if self.calibration_done and self.last_motion_index > self.threshold:
            self.consecutive_detections += 1
        else:
            self.consecutive_detections = 0

        is_motion = (self.calibration_done and
                     self.consecutive_detections >= MOTION_CONSECUTIVE_HITS)

        # Neural classification with confidence gating
        ai_label = ''
        ai_confident = False
        if self.ai_enabled and self.neural_model is not None:
            ai_label, ai_confidence, ai_confident = self._neural_classify()

        # Main line — turns RED during motion detection
        # Use AI decision if confident, otherwise fall back to classical DSP
        if ai_confident:
            # AI is confident — trust the neural network
            ai_says_motion = any(word in ai_label.upper() for word in ['WALKING', 'MOTION', 'WEAPON'])
            line_color = "#f85149" if ai_says_motion else "#58a6ff"
        else:
            line_color = "#f85149" if is_motion else "#58a6ff"

        self.line_smooth.set_data(times, smooth_vals)
        self.line_smooth.set_color(line_color)

        # Threshold line
        if self.calibration_done and self.threshold > 0:
            self.line_threshold.set_data(
                [times[0], times[-1]], [self.threshold, self.threshold]
            )

        # Auto-scale axes
        self.ax_main.set_xlim(max(0, times[-1] - 30), times[-1] + 1)
        max_val = max(max(smooth_vals[-100:]) if len(smooth_vals) > 0 else 1, 0.5)
        self.ax_main.set_ylim(-0.5, max(max_val * 1.3, self.threshold * 2))

        # Status text
        elapsed = max(times[-1], 0.1)
        pps = self.packet_count / elapsed
        cal_status = "CALIBRATING..." if not self.calibration_done else f"Threshold: {self.threshold:.1f}"
        self.status_text.set_text(
            f"Packets: {self.packet_count:,}  |  "
            f"Rate: {pps:.0f} pkt/s  |  "
            f"{cal_status}  |  "
            f"Motion: {self.last_motion_index:.2f}"
        )

        # Detection indicator — confidence-gated
        if self.ai_enabled and ai_label and ai_confident:
            # AI is confident — show the AI decision
            self.detection_text.set_text(ai_label)
            ai_says_motion = any(word in ai_label.upper() for word in ['WALKING', 'MOTION', 'WEAPON'])
            self.detection_text.set_color("#f85149" if ai_says_motion else "#3fb950")
        elif self.ai_enabled and ai_label and not ai_confident:
            # AI not confident — show AI label but add "(DSP fallback)" indicator
            dsp_decision = "MOTION" if is_motion else "CLEAR"
            self.detection_text.set_text(f"DSP: {dsp_decision} | {ai_label}")
            self.detection_text.set_color("#e3b341")
        elif is_motion:
            self.detection_text.set_text("!! MOTION DETECTED")
            self.detection_text.set_color("#f85149")
        elif not self.calibration_done:
            self.detection_text.set_text("... CALIBRATING")
            self.detection_text.set_color("#e3b341")
        else:
            self.detection_text.set_text("[CLEAR]")
            self.detection_text.set_color("#3fb950")

        return (self.line_smooth, self.status_text, self.detection_text)

    def run(self):
        """Start the live graph animation loop."""
        if not self.reader.connect():
            print("[ERROR] Failed to connect to data source. Exiting.")
            sys.exit(1)

        print("[RADAR] Live graph starting...")
        print("[RADAR] Close the graph window to exit.")

        self.ani = animation.FuncAnimation(
            self.fig,
            self._update,
            interval=UPDATE_INTERVAL_MS,
            blit=False,
            cache_frame_data=False,
        )

        try:
            plt.show()
        except KeyboardInterrupt:
            pass
        finally:
            if self.record_file:
                self.record_file.close()
            if self.raw_logger:
                self.raw_logger.close()
            self.reader.close()
            print("[RADAR] Shutdown complete.")


# ═══════════════════════════════════════════════════════════════════════════
# COM PORT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def list_com_ports():
    """List all available COM ports on the system."""
    if serial is None:
        print("pyserial not installed -- cannot list ports.")
        return

    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No COM ports found. Is the ESP32 plugged in?")
        return

    print("\nAvailable COM ports:")
    print("-" * 60)
    for p in sorted(ports, key=lambda x: x.device):
        print(f"  {p.device:10s}  {p.description}")
    print("-" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PROJECT SHADOW -- Wi-Fi CSI Motion Radar Graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python radar_graph.py --port COM5                 # Live from ESP32
  python radar_graph.py --port COM5 --window 20     # Wider smoothing
  python radar_graph.py --test                      # Synthetic data demo
  python radar_graph.py --playback demo_scenario.csv --ai   # Software demo
  python radar_graph.py --playback demo.csv --playback-loop # Loop playback
  python radar_graph.py --list-ports                # Show available ports
  python radar_graph.py --port COM5 --record empty --raw-log raw_empty.csv
        """,
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help=f"Rolling average window (default: {DEFAULT_WINDOW})")
    parser.add_argument("--record", type=str, help="Save motion index to CSV (e.g. 'empty' or 'walking')")
    parser.add_argument("--raw-log", type=str, help="Save raw CSI amplitudes/phases to CSV for neural training")
    parser.add_argument("--ai", action="store_true", help="Enable neural network classification")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive live simulation controlled via keyboard (1=Empty, 2=Walking, 3=Weapon)")
    parser.add_argument("--test", action="store_true", help="Use synthetic data (no hardware needed)")
    parser.add_argument("--playback", type=str, metavar="CSV_FILE",
                        help="Replay a recorded/generated CSV file as live data (no hardware needed)")
    parser.add_argument("--playback-speed", type=float, default=1.0,
                        help="Playback speed multiplier (default: 1.0 = real-time)")
    parser.add_argument("--playback-loop", action="store_true",
                        help="Loop playback when file ends")
    parser.add_argument("--list-ports", action="store_true", help="List available COM ports and exit")

    args = parser.parse_args()

    if args.list_ports:
        list_com_ports()
        sys.exit(0)

    print("=" * 60)
    print("  PROJECT SHADOW -- Wi-Fi CSI Neural Motion Radar")
    print("=" * 60)

    if args.interactive or args.test:
        reader = InteractiveCSIReader()
    elif args.playback:
        reader = PlaybackCSIReader(args.playback, speed=args.playback_speed,
                                   loop=args.playback_loop)
    else:
        list_com_ports()
        reader = SerialCSIReader(args.port, args.baud)

    graph = RadarGraph(reader, window_size=args.window, record_label=args.record,
                       ai_enabled=args.ai, raw_log_path=args.raw_log)
    graph.run()


if __name__ == "__main__":
    main()
