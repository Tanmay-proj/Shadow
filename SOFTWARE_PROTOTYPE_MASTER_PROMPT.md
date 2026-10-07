# Universal Master Prompt — Software Simulated Prototype Builder
*(Kisi bhi Hardware/IoT/AI Project ka Digital Twin / Simulator banane ka Reusable Blueprint)*

---

## 📋 How to Use This Prompt:
Jab bhi kisi naye hardware/sensor project (e.g., Radar, LiDAR, ECG, Vibration Sensor, Ultrasonic, Sound, etc.) ka bina hardware ke 100% working prototype banana ho, toh **bracket `[...]` wale parts ko apne naye project ke hisaab se replace karke** kisi bhi AI Agent ko seedha paste kar dena.

---

```markdown
# 🚀 SYSTEM TASK: Build a 100% Software-Simulated Digital Twin & Live Demo Prototype

You are an expert embedded systems engineer, signal processing specialist, and AI developer.
I want to build a fully functional, zero-hardware software prototype for a project called: **[PROJECT_NAME]**.

### 🎯 Project Context:
- **Core Concept:** [e.g., Wi-Fi CSI Motion Sensing / Vibration Fault Detection / ECG Arrhythmia Monitor]
- **Target Hardware (for future):** [e.g., ESP32 over USB Serial @ 115200 baud / Arduino / Raspberry Pi]
- **Target Classes / States:** [e.g., 1. Normal/Empty, 2. Active/Walking, 3. Anomaly/Attack]

---

### 🏗️ Architecture Requirements (4 Modular Components):

Please build a modular, end-to-end Python prototype with the following 4 components:

#### 1. Synthetic Data & Scenario Generator (`generate_synthetic_data.py`):
- Mathematically model the physics of [SENSOR_TYPE] (e.g., multipath fading, noise floor, frequency shifts, harmonic vibrations).
- Generate separate training datasets for each class: `synthetic_[class1].csv`, `synthetic_[class2].csv`, `synthetic_[class3].csv`.
- Generate a scripted 2-minute demonstration scenario (`demo_scenario.csv`) with clear event timeline (e.g., 0-30s Baseline -> 30-60s State A -> 60-90s State B -> 90-120s Recovery).
- Ensure output CSV headers match the exact raw format of the hardware sensor.

#### 2. Plug-and-Play Real-Time Playback Engine:
- Create a `PlaybackReader` class that replays the CSV timestamps at exact real-time clock speed (e.g., 50 packets/second).
- The reader must convert CSV rows back into raw hardware strings/packets so the downstream parser cannot distinguish between real serial hardware and fake playback.
- Support CLI flags: `--playback <file.csv>`, `--playback-speed <multiplier>`, `--playback-loop`.

#### 3. Deep Learning / ML Trainer (`train_model.py`):
- Train a lightweight neural network (e.g., 1D-CNN / LSTM / Random Forest) on sliding windows of raw sensor features.
- Support data augmentation (noise injection, scaling, time-shift) and differential features (temporal changes).
- Save the model artifact (`model.pt` or `model.pkl`) and export classification metrics JSON + non-blocking training curve plots.

#### 4. Real-Time Radar / Dashboard UI (`main_app.py`):
- High-performance live updating dark-mode UI (Matplotlib `TkAgg` / PyQt / Web).
- **Adaptive Calibration:** Automatically calculate dynamic noise floor / baseline during the first 5-15 seconds.
- **DSP Filter Pipeline:** Real-time signal sanitization (Butterworth filtering, PCA dimensionality reduction, moving variance).
- **AI Inference with Confidence Gating:** Display live predictions (e.g., `AI: WALKING (98%)`). If AI confidence < 75%, fall back to classical DSP threshold.
- **Hardware Agnostic:** Allow seamless switching between simulated data and real hardware using `--port COMx` vs `--playback file.csv`.

---

### 🛡️ Non-Negotiable Constraints:
1. **Windows Compatibility:** Strict ASCII-only console output (no unicode emojis/symbols like 🧠📊⚠⏳ that crash Windows `cp1252` encoding).
2. **Non-Blocking UI:** Do not call blocking `plt.show()` during automated training/evaluation scripts.
3. **Graceful Degradation:** The entire visualization and DSP pipeline must work even if PyTorch/ML models are not loaded.
4. **Clean Exit:** Proper multithreading / serial reader cleanup on window close or `Ctrl+C`.
```

---

## 🧠 Why This Architecture Is So Powerful:
1. **Zero Hardware Dependency:** Presentation ya college review mein stage pe hardware fail hone ka 0% risk.
2. **Plug & Play Hardware:** Jab asli hardware aayega, toh sirf `--playback file.csv` ki jagah `--port COMx` lagana padta hai — algorithm, DSP, aur AI code ka 1 line bhi change nahi karna padta.
3. **Digital Twin Strategy:** Tesla, NASA, aur defense robotics isi tareeqe se pehle digital twin banate hain, phir physical hardware integrate karte hain.
