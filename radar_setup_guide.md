# Radar Setup Guide — ESP-IDF & CSI-Tool Flashing

> Step-by-step instructions for building the Wi-Fi CSI motion detector (Phase 1).

---

## Prerequisites

- Windows 10/11 laptop
- 2x ESP32 DevKit boards (WROOM-32 or WROVER)
- 2x USB data cables (not charge-only)
- Internet connection (for downloads)

---

## Step 1: Install ESP-IDF v4.3

> [!IMPORTANT]
> The ESP32-CSI-Tool requires **ESP-IDF v4.3 specifically**. Newer versions (v4.4, v5.x) will cause build failures.

### Option A: ESP-IDF Tools Installer (Recommended for Windows)

1. Download the **ESP-IDF Tools Installer** from:
   https://dl.espressif.com/dl/esp-idf/

2. During installation, select **ESP-IDF v4.3** (not latest).

3. The installer sets up Python, Git, CMake, Ninja, and the Xtensa GCC toolchain automatically.

4. After installation, open the **"ESP-IDF 4.3 Command Prompt"** from the Start Menu.

5. Verify the installation:
   ```
   idf.py --version
   ```
   Expected output: `ESP-IDF v4.3` or similar.

### Option B: Manual Installation

```bash
# Clone ESP-IDF
mkdir C:\esp
cd /d C:\esp
git clone -b v4.3 --recursive https://github.com/espressif/esp-idf.git esp-idf-v4.3

# Run the install script
cd esp-idf-v4.3
install.bat

# Set up environment (run this every time you open a new terminal)
export.bat
```

---

## Step 2: Clone the CSI-Tool

Open the **ESP-IDF Command Prompt** and run:

```bash
cd /d C:\esp
git clone https://github.com/StevenMHernandez/ESP32-CSI-Tool.git
cd ESP32-CSI-Tool
```

The repo contains two key project folders:
- `active_ap/` — Firmware for the **Transmitter (TX)** board (runs as Access Point)
- `active_sta/` — Firmware for the **Receiver (RX)** board (runs as Station)

---

## Step 3: Flash ESP32 #1 — Transmitter (AP)

### 3.1 Connect the Board

1. Plug ESP32 #1 into your laptop via USB.
2. Open **Device Manager** → **Ports (COM & LPT)** → Note the COM port number (e.g., `COM3`).

> [!TIP]
> If no COM port appears, you may need to install the **CP2102** or **CH340** USB-to-serial driver depending on your ESP32 board variant.

### 3.2 Configure the Firmware

```bash
cd /d C:\esp\ESP32-CSI-Tool\active_ap
idf.py set-target esp32
idf.py menuconfig
```

In the menuconfig menu, navigate to:
- **Component config → CSI-Tool Config:**
  - Set **Wi-Fi Channel** = `6` (or your chosen channel — must match RX)
  - Set **SSID** = `SHADOW_RADAR` (or any name you'll remember)
  - Set **Password** = `shadowpass` (or leave open)

Press `S` to save, then `Q` to quit.

### 3.3 Build and Flash

```bash
idf.py build
idf.py -p COM3 flash
```

Replace `COM3` with your actual port. The TX board is now running as an Access Point.

---

## Step 4: Flash ESP32 #2 — Receiver (STA)

### 4.1 Connect the Board

1. **Unplug ESP32 #1** (or note its COM port to avoid confusion).
2. Plug ESP32 #2 into your laptop via USB.
3. Note the new COM port number (e.g., `COM5`).

### 4.2 Configure the Firmware

```bash
cd /d C:\esp\ESP32-CSI-Tool\active_sta
idf.py set-target esp32
idf.py menuconfig
```

In menuconfig:
- **Component config → CSI-Tool Config:**
  - Set **Wi-Fi Channel** = `6` (must match TX!)
  - Set **SSID** = `SHADOW_RADAR` (must match TX!)
  - Set **Password** = `shadowpass` (must match TX!)

Press `S` to save, then `Q` to quit.

### 4.3 Build, Flash, and Monitor

```bash
idf.py build
idf.py -p COM5 flash monitor
```

The `monitor` flag opens a live serial console after flashing.

---

## Step 5: Verify CSI Data Stream

### What You Should See

After flashing the RX board with `monitor`, you should see lines like:

```
CSI_DATA,<mac>,<rssi>,<rate>,<sig_mode>,<mcs>,<bandwidth>,<smoothing>,<not_sounding>,<aggregation>,<stbc>,<fec>,<sgi>,<noise_floor>,<ampdu>,<channel>,<secondary_channel>,<local_timestamp>,<ant>,<sig_len>,<rx_state>,<len>,[<csi_data>]
```

The `[<csi_data>]` portion contains comma-separated integers — these are the amplitude/phase values for each OFDM subcarrier.

### Troubleshooting

| Problem | Solution |
|---|---|
| No output at all | Check COM port, try pressing the RST button on the board |
| Garbled text | Verify baud rate is 115200 in your terminal |
| "WiFi not connected" | Ensure SSID and password match between AP and STA configs |
| Build errors | Verify you're using ESP-IDF v4.3 exactly: `idf.py --version` |
| COM port not found | Install CP2102/CH340 driver, try a different USB cable |

---

## Step 6: Physical Setup

```
    ┌──────────┐                              ┌──────────┐
    │ ESP32 #1 │      2-3 meters apart        │ ESP32 #2 │
    │   (TX)   │  ◄─────── clear LOS ───────► │   (RX)   │
    │   AP     │                              │   STA    │
    └──────────┘                              └────┬─────┘
                                                   │ USB
                                              ┌────▼─────┐
                                              │  Laptop   │
                                              └──────────┘
```

1. Place TX and RX **2-3 meters apart** on stable surfaces (desks, tables).
2. Ensure **clear line of sight** — no obstacles between them.
3. The RX board stays connected to the laptop via USB (for serial data).
4. The TX board can be powered via USB wall adapter (no laptop connection needed after flashing).
5. Keep the boards at roughly the **same height** (table-top level).

---

## Step 7: Launch the Radar Graph

```bash
cd C:\path\to\your\SHADOW
pip install -r requirements.txt
python radar_graph.py --port COM5 --baud 115200
```

See `radar_graph.py` for full usage and options.

---

## Step 8: Validation Tests

### Test 1 — Empty Room Baseline
- Clear the area between the boards.
- Sit still or leave the room entirely.
- **Expected**: The motion index graph shows a flat, stable line near zero.

### Test 2 — Hand Wave
- Wave your hand between the two boards.
- **Expected**: Sharp spikes appear on the graph, returning to flat when you stop.

### Test 3 — Walk-Through
- Walk through the corridor between the boards at normal pace.
- **Expected**: Sustained rhythmic spikes matching your walking cadence.

> [!TIP]
> If the graph is noisy during the "empty room" test, increase the averaging window. In `radar_graph.py`, adjust `--window 20` (default is 15 packets).

---

## Notes on the CSI Data Format

The CSI-Tool outputs data in this format per line:
```
CSI_DATA,<metadata_fields>,<len>,[imaginary,real,imaginary,real,...]
```

- Each subcarrier has an **imaginary** and **real** component.
- **Amplitude** = sqrt(imaginary² + real²)
- There are typically **52-64 subcarriers** depending on bandwidth (HT20/HT40).
- The radar_graph.py script handles all this parsing automatically.
