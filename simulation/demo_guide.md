# PROJECT SHADOW — Live Demo Guide

> Step-by-step script for demonstrating Wi-Fi Interferometric Neural Sensing and its vulnerability to RF deception.

---

> [!CAUTION]
> **Before starting**: Ensure you are in a controlled environment. The SHADOW weapon broadcasts RF interference. Keep demo bursts SHORT (< 60 seconds each).

---

## Pre-Demo Checklist

- [ ] **Radar TX** (ESP32 #1) — flashed with `active_ap`, powered ON, placed on left side
- [ ] **Radar RX** (ESP32 #2) — flashed with `active_sta`, USB-connected to laptop, placed on right side
- [ ] **Boards positioned** — 2-3 meters apart, clear line of sight, same height
- [ ] **Neural model trained** — `shadow_neural_model.pt` exists (run `train_model.py` beforehand)
- [ ] **radar_graph.py running with `--ai`** — flat baseline + "🧠 AI: EMPTY" confirmed on screen
- [ ] **SHADOW Weapon** (ESP32 #3) — flashed with `shadow_weapon.ino`, **NOT connected to power**
- [ ] **Battery bank** — charged, ready in pocket with the weapon
- [ ] **Channel match confirmed** — Weapon's `RADAR_CHANNEL` matches radar's channel (default: 6)
- [ ] **MAC address confirmed** — Weapon's `TARGET_TX_MAC` matches the TX board's actual MAC address
- [ ] **Screen recording software** — ready to capture the demo

---

## Demo Script

### ACT 1: Introduce the Neural Sensing System (2 minutes)

**Setup**: Radar running with `--ai` flag, graph visible on projector/screen. Room is empty between boards.

**Command running on laptop:**
```
python radar_graph.py --port COM8 --ai
```

**Say:**
> "What you're seeing is a real-time Wi-Fi Neural Sensing system. These two ESP32 boards
> create an invisible motion detection field using Wi-Fi Channel State Information — the radio
> waves between them are constantly being analysed by a 1D Convolutional Neural Network we
> trained. Watch the blue line — it's flat. The AI says 'EMPTY' because nobody is between
> the boards."

**Action**: Point at the flat line and the "🧠 AI: EMPTY" indicator. Let it run 15–20 seconds.

---

### ACT 2: Prove the Neural Classifier Works (2 minutes)

**Say:**
> "Now let me prove the AI actually works."

**Action**: Walk through the corridor between the two boards.

**Say:**
> "See the red spikes? And notice the AI now says 'WALKING'. It doesn't just look at a
> threshold — it analyses the pattern of Wi-Fi subcarrier changes using a trained neural network
> to distinguish real human motion from random noise."

**Action**: Stop walking. Show the graph settle back to flat and "EMPTY".

**Say:**
> "When I stop, the AI immediately classifies the room as empty again. No false positives."

---

### ACT 3: The Vulnerability — Digital Ghost (2 minutes)

**Setup**: Make sure nobody is between the boards. Graph is flat, AI says "EMPTY".

**Say:**
> "Now I'm going to demonstrate a critical vulnerability in Wi-Fi sensing systems. Watch the screen."

**Action**:
1. Casually reach into your pocket
2. **Plug the battery bank into the SHADOW weapon** (do NOT announce what you're doing)
3. Wait 2-3 seconds for it to boot (you'll feel the LED start blinking through your pocket)
4. Watch the graph

**The flat line should erupt into rhythmic spikes.**

**Pause for dramatic effect. Let the audience see the spikes for 5-10 seconds.**

**Say:**
> "The radar believes someone is walking through this room. But look around —
> nobody is here. Nobody moved. I just activated a device called SHADOW."

**Action**: Pull the device out of your pocket and hold it up.

**Say:**
> "This is a single ESP32 board running on a battery bank. It spoofs the transmitter's
> MAC address and injects raw radio packets at a rhythm that mimics human walking cadence.
> This creates a 'digital ghost' — multipath interference that the radar interprets as motion."

---

### ACT 4: The Kill Switch (1 minute)

**Say:**
> "And when I turn it off..."

**Action**: Unplug the battery from the weapon.

**Expected**: The graph returns to flat within 1-2 seconds. AI says "EMPTY" again.

**Say:**
> "The ghost disappears instantly. The sensing system goes back to normal."

---

### ACT 5: Repeatability (2 minutes)

**Say:**
> "Let me prove this is consistent and repeatable."

**Action**: Cycle the weapon ON/OFF three times:
1. **ON** — wait 5 seconds — show spikes
2. **OFF** — wait 5 seconds — show flat line
3. **ON** — wait 5 seconds — show spikes
4. **OFF** — wait 5 seconds — show flat line
5. **ON** — wait 5 seconds — show spikes
6. **OFF** — final flat line

**Say:**
> "Three for three. Every single time, the radar reports a moving target that doesn't exist."

---

## Post-Demo Talking Points

### "How does the Neural Sensing work?"
> "Wi-Fi CSI captures how radio signals bounce around a room across 52 OFDM subcarriers.
> When a person moves, the amplitude and phase of these subcarriers change. Our system uses
> a Butterworth filter for denoising, PCA for dimensionality reduction, and a 1D-CNN called
> CSINet for classification. The neural network was trained on labelled recordings of empty
> rooms and walking activity."

### "What is the model architecture?"
> "CSINet is a 3-layer 1D Convolutional Neural Network — Conv1d(32)→Conv1d(64)→Conv1d(128)
> with batch normalization, followed by a fully connected classifier. It takes a sliding window
> of 20 CSI packets (amplitude + phase, 52 subcarriers each = 2080 features) and outputs a
> class label with confidence."

### "How does the attack work?"
> "SHADOW spoofs the transmitter's MAC address and injects 802.11 beacon frames at a rate
> that oscillates sinusoidally to mimic human gait cadence (~0.8-1.2s cycle). This floods
> the same Wi-Fi channel with energy that corrupts the legitimate CSI measurements."

### "Can the AI detect the attack?"
> "Yes — that's actually a research direction we explored. If you train the model with a
> 3rd class ('weapon'), the neural network can learn to distinguish real walking from the
> weapon's interference pattern. The weapon's signal has different statistical properties
> from real human motion."

### "Is this legal?"
> "This is a controlled lab demonstration. Intentional RF interference violates regulations
> in most countries. The point is to demonstrate the vulnerability of Wi-Fi sensing systems
> and explore countermeasures, not to create a weapon."

### "What are the defensive countermeasures?"
> "Adversarial training (3-class model: empty / real motion / attack), multi-antenna
> cross-correlation, anomaly detection on the RF environment, and cryptographic frame
> authentication would all help mitigate this type of attack."

---

## Troubleshooting During Demo

| Problem | Quick Fix |
|---|---|
| AI doesn't show, just threshold | Make sure you're using `--ai` flag AND `shadow_neural_model.pt` exists |
| No spikes when weapon is ON | Check channel match! Weapon must be on EXACT same channel as radar |
| Graph is always noisy (even baseline) | Move to a quieter Wi-Fi environment, increase `--window` |
| Weapon doesn't power on | Check battery bank has charge, try different USB cable |
| Spikes look different from real motion | This is expected — the pattern won't be identical, just similar enough |
| Graph freezes | Check USB connection to RX board, restart `radar_graph.py` |
| Weapon LED not blinking | Re-flash the firmware, check LED_PIN matches your board (usually GPIO 2) |

---

## Recording Checklist

- [ ] Screen recording showing: "AI: EMPTY" → walk → "AI: WALKING" → stop → "AI: EMPTY"
- [ ] Screen recording showing: "AI: EMPTY" → weapon ON → spikes → weapon OFF → "AI: EMPTY"
- [ ] Camera recording of the empty room during weapon activation
- [ ] Close-up of the SHADOW device being plugged in
- [ ] Side-by-side comparison: real human spikes vs SHADOW spikes
- [ ] Three consecutive ON/OFF cycles for repeatability evidence
- [ ] Screenshot of `evaluate.py` results showing accuracy/F1/ROC curves
