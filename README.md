# PROJECT SHADOW — Wi-Fi Interferometric Neural Sensing

> **A dual-purpose Wi-Fi CSI research platform: a real-time motion radar using neural network classification, paired with an ESP32 "weapon" that demonstrates CSI spoofing vulnerabilities by injecting a digital ghost.**

![Status](https://img.shields.io/badge/status-experimental-red)
![Platform](https://img.shields.io/badge/platform-ESP32-blue)
![License](https://img.shields.io/badge/license-educational-yellow)
![ML](https://img.shields.io/badge/ML-PyTorch_1D--CNN-orange)

---

> [!CAUTION]
> **LEGAL WARNING**: This project intentionally generates RF interference on Wi-Fi channels. This violates FCC Part 15 (USA), ETSI EN 300 328 (EU), and equivalent regulations in most countries. **Use ONLY in a controlled laboratory environment for short demonstration bursts.** Never deploy in production, public, or shared Wi-Fi environments. The authors accept no liability for misuse.

---

## System Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                         RADAR SYSTEM                                  │
│                                                                       │
│  ESP32 #1 (TX/AP)  ~~~~~~~~ Wi-Fi Ch.6 ~~~~~~~~>  ESP32 #2 (RX/STA) │
│  [Beacon source]           2-3m LOS              [CSI extraction]    │
│                                                        │ USB         │
│                                                   ┌────▼──────────┐  │
│                                                   │    Laptop     │  │
│                                                   │               │  │
│                                                   │ radar_graph.py│  │
│                                                   │    ┌──────┐   │  │
│                                                   │    │ DSP  │   │  │
│                                                   │    │ +PCA │   │  │
│                                                   │    └──┬───┘   │  │
│                                                   │       │       │  │
│                                                   │    ┌──▼───┐   │  │
│                                                   │    │CSINet│   │  │
│                                                   │    │ 1D-  │   │  │
│                                                   │    │ CNN  │   │  │
│                                                   │    └──┬───┘   │  │
│                                                   │       │       │  │
│                                                   │   Detection   │  │
│                                                   └───────────────┘  │
└───────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│                      SHADOW WEAPON (ESP32 #3)                         │
│                                                                       │
│  MAC-spoofed 802.11 beacon injection at gait-modulated rates         │
│  Bypasses RX MAC filter → corrupts CSI → creates "digital ghost"     │
└───────────────────────────────────────────────────────────────────────┘
```

## Signal Processing & Neural Network Pipeline

```
Raw CSI I/Q Pairs (52 subcarriers × 2)
    │
    ├─── Amplitude: √(I² + Q²)
    ├─── Phase: atan2(I, Q) → unwrap → detrend (CFO/SFO removal)
    │
    ▼
Adaptive Subcarrier Normalization (→ 52 fixed dimensions)
    │
    ▼
Butterworth Low-Pass Filter (3rd order, fc ≈ 3 Hz)
    │
    ├───── Classical DSP Path ─────────┐
    │   PCA (104 features → 1)         │
    │   Variance → Motion Index        │
    │   Adaptive Threshold → Decision  │
    │                                  │
    ├───── Neural Network Path ────────┐
    │   Sliding Window (20 packets)    │
    │   1D-CNN (CSINet):               │
    │     Conv1d(1→32, k=7)            │
    │     Conv1d(32→64, k=5)           │
    │     Conv1d(64→128, k=3)          │
    │     AdaptiveAvgPool → FC(64)     │
    │     → Softmax → Class            │
    └──────────────────────────────────┘
```

## Hardware Required

| Component | Quantity | Notes |
|---|---|---|
| ESP32 DevKit (WROOM-32 or WROVER) | 3 | Any ESP32 with standard Wi-Fi |
| USB data cables | 3 | Must be data-capable, not charge-only |
| Laptop | 1 | Windows, Python 3.8+, Arduino IDE |
| Portable power bank | 1 | Any 5V USB output |

## Software Required

| Tool | Used For | Phase |
|---|---|---|
| ESP-IDF v4.3 | Radar firmware (CSI-Tool) | Phase 1 |
| Arduino IDE + ESP32 board package | Weapon firmware | Phase 2 |
| Python 3.8+ with PyTorch | Radar + Neural classification | Phase 1 & 3 |

## Project Structure

```
SHADOW/
├── README.md                     # This file
├── STEP_BY_STEP_GUIDE.md         # Complete beginner's guide (start here!)
├── requirements.txt              # Python dependencies (incl. PyTorch)
├── radar_setup_guide.md          # ESP-IDF & CSI-Tool flashing guide
├── demo_guide.md                 # Live demo script
├── radar_graph.py                # Real-time CSI radar (DSP + Neural)
├── train_model.py                # Neural network training script
├── evaluate.py                   # Quantitative evaluation & metrics
└── shadow_weapon/
    └── shadow_weapon.ino         # Deception engine firmware
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Radar (Phase 1)
```bash
# Flash TX & RX boards (see radar_setup_guide.md)

# Launch live graph (classical DSP mode)
python radar_graph.py --port COM8 --baud 115200

# Record raw CSI data for neural training
python radar_graph.py --port COM8 --record empty --raw-log raw_empty.csv
python radar_graph.py --port COM8 --record walking --raw-log raw_walking.csv
```

### 3. Train Neural Network (Phase 2)
```bash
python train_model.py --data raw_empty.csv raw_walking.csv
```

### 4. Run with Neural Classification
```bash
python radar_graph.py --port COM8 --ai
```

### 5. Weapon (Phase 3)
1. Open `shadow_weapon/shadow_weapon.ino` in Arduino IDE
2. Set `RADAR_CHANNEL` to match your radar's channel (default: 6)
3. Set `TARGET_TX_MAC` to the MAC address of your TX board
4. Flash to ESP32 #3
5. Unplug from laptop, plug into battery bank

### 6. Evaluate
```bash
python evaluate.py --motion-csvs csi_features_empty_*.csv csi_features_walking_*.csv \
                   --motion-labels empty walking \
                   --model shadow_neural_model.pt --raw-csvs raw_empty.csv raw_walking.csv
```

## How It Works

### The Radar (Sensing)
Uses **Wi-Fi Channel State Information (CSI)** — the fine-grained frequency response of the wireless channel between two ESP32 boards. When a person moves between the boards, their body perturbs the multipath propagation, causing measurable amplitude/phase shifts across OFDM subcarriers.

The system uses a **dual detection pipeline**:
1. **Classical DSP**: Butterworth filtering → PCA dimensionality reduction → variance-based motion index → adaptive threshold
2. **Neural Network (CSINet)**: A 1D Convolutional Neural Network trained on labeled CSI data that classifies motion states with higher accuracy and robustness

### The Weapon (Deception)
Exploits the fact that CSI is sensitive to **any** RF energy on the same channel. The weapon:
1. **Spoofs the TX board's MAC address** to bypass the RX board's hardware MAC filter
2. **Injects raw 802.11 beacon frames** via `esp_wifi_80211_tx()`
3. **Modulates packet rate sinusoidally** (~0.8-1.2s cycle) to mimic human gait cadence

This creates artificial multipath interference that the radar interprets as physical motion — a "digital ghost."

### Why `setTxPower()` Doesn't Work
TX power only controls the weapon's own signal strength — it doesn't modulate the channel between the radar's TX and RX boards. Raw packet injection with rate modulation creates actual environmental RF disturbance.

## References

- [ESP32-CSI-Tool (StevenMHernandez)](https://github.com/StevenMHernandez/ESP32-CSI-Tool)
- [Espressif Official ESP-CSI](https://github.com/espressif/esp-csi)
- [ESP-IDF v4.3 Documentation](https://docs.espressif.com/projects/esp-idf/en/v4.3/)
- [Wi-Fi Sensing Security Research (Rutgers)](https://www.winlab.rutgers.edu/)
