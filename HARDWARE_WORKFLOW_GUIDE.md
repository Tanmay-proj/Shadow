# Project SHADOW — Real Hardware (ESP32) Workflow Guide

Yeh guide real ESP32 hardware ke saath kaam karne ke liye hai.

---

## 1. Hardware Connections

1. **ESP32 Transmitter (TX):**
   - Power bank ya phone charger se plug karo.
   - Yeh room ke ek kone mein rakh do.
   - Iska kaam sirf Wi-Fi packets broadcast karna hai.

2. **ESP32 Receiver (RX):**
   - USB cable se apne **Laptop** mein plug karo.
   - Yeh doosre kone mein ya room ke beech mein rakh do (TX aur RX ke beech line-of-sight ho).

---

## 2. Step-by-Step Commands

### Step 1: Detect Port
Pehle check karo ki laptop ne ESP32 ko kaunsa COM port diya hai:
```cmd
cd /d E:\WIFI_INTERFEROMETRIC_NEURAL_SENSING\SHADOW
python radar_graph.py --list-ports
```
*(Maan lo output mein `COM8` ya `COM5` aaya)*

---

### Step 2: Live Stream Test (Without AI)
Graph khol kar dekho ki real Wi-Fi CSI packets aa rahe hain ya nahi:
```cmd
python radar_graph.py --port COM8
```
- Pehle 15 sec **CALIBRATING** hoga.
- Uske baad room mein khade hokar dekho — jab hiloge toh line upar jaayegi (spikes banenge), shaant rahoge toh flat line hogi.
- Jab verify ho jaaye, window close kar do.

---

### Step 3: Record Real "EMPTY" Room Data
Ab model ko train karne ke liye real data collect karenge:
1. Room ko **khaali** chhod do (koi movement nahi).
2. Yeh command chalao aur **2 se 3 minute** chalne do:
```cmd
python radar_graph.py --port COM8 --raw-log real_empty.csv --record empty
```
3. 2-3 minute baad window close kar do. `real_empty.csv` ban jaayegi.

---

### Step 4: Record Real "WALKING" Motion Data
1. Yeh command chalao:
```cmd
python radar_graph.py --port COM8 --raw-log real_walking.csv --record walking
```
2. TX aur RX ke beech mein normal speed se **walk karo / chalo** for **2 se 3 minute**.
3. Window close kar do. `real_walking.csv` ban jaayegi.

---

### Step 5: Train AI Model on Real Data
Dono real CSVs se fresh model train karo:
```cmd
python train_model.py --data real_empty.csv real_walking.csv --differential --epochs 10 --batch-size 128
```
Yeh naya `shadow_neural_model.pt` save kar dega jo real room ke signals pe trained hoga.

---

### Step 6: Run Full Real-Time AI on Hardware
Ab real time mein AI motion detect karega:
```cmd
python radar_graph.py --port COM8 --ai
```
- Jab room khaali hoga -> **AI: EMPTY (95-100%)** (Green)
- Jab koi chalega -> **AI: WALKING (95-100%)** (Red)

---

## Summary of Folders
- `E:\WIFI_INTERFEROMETRIC_NEURAL_SENSING\SHADOW\simulation\` -> Saara fake/simulated demo backup (Safe for presentations).
- `E:\WIFI_INTERFEROMETRIC_NEURAL_SENSING\SHADOW\` -> Main workspace for real hardware.
