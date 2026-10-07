# PROJECT SHADOW — Complete Beginner's Step-by-Step Guide

> This guide assumes you have ZERO coding experience. Every click, every command, every screen is explained.

---

## 🛒 STEP 0: Gather Your Hardware

Before touching any software, make sure you have these on your desk:

| Item | Qty | What to look for |
|---|---|---|
| ESP32 DevKit boards | 3 | Look for "ESP32-WROOM-32" or "ESP32-WROVER" printed on the metal shield |
| USB cables | 3 | **MUST be data cables** — cheap charging-only cables won't work. If you bought the ESP32 online, the cable that came with it is usually fine |
| Your Windows laptop | 1 | The one you're reading this on |
| Portable power bank | 1 | Any phone charger battery bank with a USB-A port |

> [!TIP]
> **How to tell if a USB cable is data-capable**: Plug an ESP32 into your laptop with the cable. Open **Device Manager** (press `Win + X`, click "Device Manager"). Look under **Ports (COM & LPT)**. If a new entry appears (like "Silicon Labs CP210x" or "USB-SERIAL CH340"), the cable works. If nothing appears, try a different cable.

**Label your boards now!** Put a small piece of tape on each:
- Board 1 → write **"TX"** (Transmitter)
- Board 2 → write **"RX"** (Receiver)  
- Board 3 → write **"WEAPON"**

---

# PHASE 1: BUILD THE RADAR

---

## 📥 STEP 1: Install ESP-IDF (the Radar Firmware Toolkit)

This is the software that lets you program the radar boards.

### 1.1 — Download the installer

1. Open your browser
2. Go to: **https://dl.espressif.com/dl/esp-idf/**
3. Look for **"ESP-IDF v4.3.x Offline Installer"** (or the closest to v4.3)
4. Click **Download**
5. Save it anywhere (your Downloads folder is fine)

> [!WARNING]
> **You MUST get version 4.3** — not 4.4, not 5.0, not "latest". The radar software only works with v4.3.

### 1.2 — Run the installer

1. Double-click the downloaded `.exe` file
2. If Windows asks "Do you want to allow this app to make changes?" → Click **Yes**
3. Click **Next** through the installer screens
4. When it asks **where to install** → leave the default path (usually `C:\esp\esp-idf` or your user folder)
5. When it asks about **components** → leave everything checked
6. Click **Install** and wait (this takes 10-20 minutes — it's downloading compilers, Python, Git, etc.)
7. When finished, click **Finish**

### 1.3 — Verify it works

1. Press the **Windows key** on your keyboard
2. Type: **ESP-IDF**
3. You should see **"ESP-IDF 4.3 CMD"** or **"ESP-IDF Command Prompt"** in the Start Menu
4. Click it to open. A black command window appears.
5. Type this and press Enter:
   ```
   idf.py --version
   ```
6. You should see something like: `ESP-IDF v4.3` or `ESP-IDF v4.3.5`

> [!IMPORTANT]
> **If you don't see "ESP-IDF" in the Start Menu**: The installer may have failed. Try running it again. If it still fails, restart your laptop and try once more.

✅ **Checkpoint**: You have a working ESP-IDF command prompt that shows version 4.3.

---

## 📥 STEP 2: Download the CSI-Tool (Radar Software)

### 2.1 — Clone the repository

1. In the **ESP-IDF Command Prompt** (the black window from Step 1.3), type these commands one at a time, pressing Enter after each:

   ```
   cd /d C:\esp
   ```
   ```
   git clone https://github.com/StevenMHernandez/ESP32-CSI-Tool.git
   ```

2. Wait for it to download (about 30 seconds)
3. You should see messages about "Cloning into 'ESP32-CSI-Tool'..." and then it finishes

> [!TIP]
> If you get an error about "git not found", close the command prompt and reopen "ESP-IDF 4.3 CMD" from the Start Menu. ESP-IDF installs its own Git.

✅ **Checkpoint**: The folder `C:\esp\ESP32-CSI-Tool` now exists.

---

## 🔌 STEP 3: Flash Board #1 — The Transmitter (TX)

### 3.1 — Plug in the TX board

1. Take the board labeled **"TX"**
2. Plug it into your laptop with a USB cable
3. Open **Device Manager**: Press `Win + X` → click **Device Manager**
4. Expand **Ports (COM & LPT)**
5. Note the port number, e.g., **COM3** or **COM4**
   - Write this number down! You'll need it in a moment.

> [!WARNING]
> **If no COM port appears:**
> - Try a different USB cable (yours might be charge-only)
> - Try a different USB port on your laptop
> - You may need to install a driver:
>   - If your board says "CP2102" → Download driver from https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
>   - If your board says "CH340" → Download driver from http://www.wch-ic.com/downloads/CH341SER_EXE.html

### 3.2 — Configure the TX firmware

In the **ESP-IDF Command Prompt**, type these commands one at a time:

```
cd /d C:\esp\ESP32-CSI-Tool\active_ap
```

```
idf.py set-target esp32
```

```
idf.py menuconfig
```

A blue/gray menu screen will appear! This is the configuration menu.

**Navigate using your keyboard:**
- **Arrow keys** (↑↓) to move up/down
- **Enter** to select/enter a submenu
- **Esc** to go back

**What to change:**
1. Use arrow keys to find **"Component config"** → press Enter
2. Find **"CSI-Tool Config"** → press Enter
3. Find **"WiFi Channel"** → press Enter → type **6** → press Enter
4. Find **"SSID"** → press Enter → clear the field → type **SHADOW_RADAR** → press Enter
5. Find **"Password"** → press Enter → type **shadowpass** → press Enter
6. Press **S** to save (a popup confirms — press Enter)
7. Press **Q** to quit

### 3.3 — Build and flash

Still in the ESP-IDF Command Prompt, type:

```
idf.py build
```

Wait for it to compile (2-5 minutes). You'll see lots of text scrolling by. Wait until you see **"Project build complete."**

Then type (replace `COM3` with YOUR actual port number from Step 3.1):

```
idf.py -p COM3 flash
```

Wait for it to finish. You'll see a progress bar and then **"Hard resetting via RTS pin..."**

✅ **Checkpoint**: TX board is flashed! You can unplug it now.

---

## 🔌 STEP 4: Flash Board #2 — The Receiver (RX)

### 4.1 — Plug in the RX board

1. **Unplug the TX board** from USB
2. Take the board labeled **"RX"**
3. Plug it into your laptop
4. Check **Device Manager** again → note the COM port number (e.g., **COM5**)
   - Write this down — you'll need it for the radar graph later!

### 4.2 — Configure the RX firmware

In the **ESP-IDF Command Prompt**, type:

```
cd /d C:\esp\ESP32-CSI-Tool\active_sta
```

```
idf.py set-target esp32
```

```
idf.py menuconfig
```

Same blue menu appears. Set these values **exactly matching the TX board:**
1. **Component config** → **CSI-Tool Config**
2. **WiFi Channel** = **6** (same as TX!)
3. **SSID** = **SHADOW_RADAR** (same as TX!)
4. **Password** = **shadowpass** (must exactly match TX!)
5. Press **S** to save, **Q** to quit

### 4.3 — Build and flash

```
idf.py build
```

Wait for compilation. Then (replace `COM5` with your actual port):

```
idf.py -p COM5 flash monitor
```

> [!IMPORTANT]
> Notice we added **`monitor`** at the end this time! This keeps the serial console open so you can see the CSI data streaming live.

### 4.4 — Check for CSI data

After flashing, the screen will start showing text. Look for lines that start with **`CSI_DATA`** and contain lots of numbers in square brackets, like:

```
CSI_DATA,aa:bb:cc:dd:ee:ff,-45,11,0,0,0,...,[12,-5,8,3,-2,15,...]
```

**If you see these lines → THE RADAR IS WORKING! 🎉**

Press **Ctrl + ]** (Control key + right square bracket) to exit the monitor.

> [!WARNING]
> **If you DON'T see CSI_DATA lines:**
> - Make sure the TX board is powered! Plug it into a USB charger or your laptop's other USB port.
> - Both boards must be on the SAME channel (6) and SAME SSID (SHADOW_RADAR).
> - Press the RST (reset) button on the RX board and wait 10 seconds.

✅ **Checkpoint**: Both radar boards are flashed. The RX board shows CSI_DATA in the monitor.

---

## 🖥️ STEP 5: Set Up the Physical Radar

### 5.1 — Position the boards

```
   Your desk / table / shelf

   ┌──────┐                              ┌──────┐
   │  TX  │         2-3 meters           │  RX  │
   │board │ ◄──── empty space ──────►    │board │
   └──┬───┘                              └──┬───┘
      │                                     │
   USB to                              USB to
   wall charger                         LAPTOP
   (or laptop)
```

1. Place **TX** on the LEFT side of a desk/table
2. Place **RX** on the RIGHT side, **2-3 meters away**
3. Make sure there's **nothing between them** (clear line of sight)
4. Both boards should be at the **same height** (both on the table)
5. **TX** → plug into a USB wall charger (just needs power, no laptop needed)
6. **RX** → plug into your **laptop** via USB (this is where data comes from)

✅ **Checkpoint**: Two boards facing each other, 2-3m apart, RX connected to laptop.

---

## 📊 STEP 6: Launch the Live Radar Graph

### 6.1 — Open a regular command prompt

1. Press `Win + R`
2. Type **cmd** and press Enter
3. A command window opens

### 6.2 — Navigate to the project folder

Type (replace with the actual path where you saved the SHADOW folder):
```
cd /d C:\path\to\your\SHADOW
```

### 6.3 — Run the radar graph

Replace `COM5` with the COM port of your **RX board** (the one you wrote down in Step 4.1):

```
python radar_graph.py --port COM5 --baud 115200
```

A window will pop up with a **dark-themed graph**! You should see:
- **Top panel**: A line graph labeled "SHADOW RADAR — Motion Index"
- **Bottom panel**: A bar-style graph showing subcarrier amplitudes
- **Status overlay**: Showing packet count and rate

### 6.4 — Test it!

**Test 1 — Empty Room:**
- Don't move. Sit still.
- The line should be **flat and near zero**.
- A green **"● CLEAR"** label should appear in the top-right.

**Test 2 — Hand Wave:**
- Wave your hand between the two boards.
- The line should **spike up sharply**.
- A red **"⚠ MOTION DETECTED"** label should appear.

**Test 3 — Walk Through:**
- Walk between the boards at normal speed.
- You should see **rhythmic spikes** matching your steps.

> [!TIP]
> **If the line is noisy when nobody is moving**, close the graph and restart with a bigger smoothing window:
> ```
> python radar_graph.py --port COM5 --baud 115200 --window 25
> ```

> [!TIP]
> **Want to test the graph without any hardware?** You can run:
> ```
> python radar_graph.py --test
> ```
> This uses fake data — the graph will show 10 seconds of calm, then 5 seconds of simulated motion, repeating.

✅ **Checkpoint**: The radar graph shows flat baseline when still, spikes when you move. PHASE 1 COMPLETE! 🎉

---

# PHASE 2: BUILD THE SHADOW WEAPON

---

## 📥 STEP 7: Install Arduino IDE

### 7.1 — Download Arduino IDE

1. Go to: **https://www.arduino.cc/en/software**
2. Click **"Windows Win 10 and newer, 64 bits"** (or the appropriate version)
3. Click **"JUST DOWNLOAD"** (you don't need to donate)
4. Run the downloaded installer
5. Click **Next → Next → Install → Finish**

### 7.2 — Add ESP32 board support

1. Open **Arduino IDE**
2. Go to **File** → **Preferences** (or press `Ctrl + ,`)
3. Find the field **"Additional boards manager URLs"**
4. Paste this URL into the field:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
5. Click **OK**
6. Go to **Tools** → **Board** → **Boards Manager** (or click the board icon on the left sidebar)
7. In the search box, type: **esp32**
8. Find **"esp32 by Espressif Systems"** → Click **Install**
9. Wait for installation (2-5 minutes)

✅ **Checkpoint**: Arduino IDE is installed with ESP32 support.

---

## 🔫 STEP 8: Flash the SHADOW Weapon

### 8.1 — Open the weapon sketch and set TX MAC Address

1. In Arduino IDE, go to **File** → **Open**
2. Navigate to where you saved the project: **.../SHADOW/shadow_weapon/**
3. Select **shadow_weapon.ino** → Click **Open**

The code will open in the editor.

> [!IMPORTANT]
> **Check the channel and set the MAC Address!** Near the top of the code, find these lines:
> ```cpp
> #define RADAR_CHANNEL        6
> uint8_t TARGET_TX_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
> ```
> 1. If your radar uses a different channel, change `6` to match. 
> 2. You **MUST** change `TARGET_TX_MAC` to the real MAC address of your TX board! To find it: plug the TX board into your laptop, open Arduino IDE Serial Monitor at 115200 baud, press the RST button, and look for a line like `wifi:mode : ap (BC:DD:C2:CC:49:F5)`. Convert each pair to hex: `{0xBC, 0xDD, 0xC2, 0xCC, 0x49, 0xF5}`.

### 8.2 — Plug in the Weapon board

1. Take the board labeled **"WEAPON"**
2. Plug it into your laptop via USB
3. Check Device Manager → note the COM port (e.g., **COM7**)

### 8.3 — Configure Arduino IDE

In the Arduino IDE menu bar:

1. **Tools** → **Board** → **ESP32 Arduino** → select **"ESP32 Dev Module"**
2. **Tools** → **Port** → select your COM port (e.g., **COM7**)

Leave all other settings at their defaults.

### 8.4 — Upload the firmware

1. Click the **Upload button** (the → arrow icon in the top-left, or press `Ctrl + U`)
2. Wait for compilation (1-2 minutes) — you'll see progress at the bottom
3. The upload starts — you'll see a progress bar
4. When done, it says **"Done uploading."**

> [!WARNING]
> **If upload fails with "Failed to connect":**
> - Hold down the **BOOT** button on the ESP32 board
> - Click Upload in Arduino IDE
> - Release the BOOT button when you see "Connecting..."

### 8.5 — Verify it's working

1. Go to **Tools** → **Serial Monitor** (or press `Ctrl + Shift + M`)
2. Set the baud rate dropdown (bottom-right of the Serial Monitor) to **115200**
3. You should see output like:

```
═══════════════════════════════════════════════════════════════
  PROJECT SHADOW — Dynamic EW Deception Engine
═══════════════════════════════════════════════════════════════

  Target Channel : 6
  Gait Cycle     : 800-1200 ms
  Burst Rate     : 20-200 pkt/s

[SHADOW] ████ WEAPON ARMED ████
[SHADOW] Deception engine running...

[SHADOW] Cycle: 1 | Packets: 342 | Rate: 150 pkt/s | Intensity: 0.73 | Period: 1050 ms
```

4. The **blue LED** on the board should be blinking!
5. Close the Serial Monitor

### 8.6 — Test standalone (battery) mode

1. **Unplug** the ESP32 from the laptop
2. Plug the ESP32 into your **portable battery bank** using a USB cable
3. Watch the board — the **blue LED should start blinking** within 2-3 seconds
4. That means the weapon is running autonomously!

✅ **Checkpoint**: Weapon is flashed, running on battery, LED blinking. PHASE 2 COMPLETE! 🎉

---

# PHASE 3: THE LIVE DEMO

---

## 🎭 STEP 9: Run the Deception Demo

### 9.1 — Set up the scene

1. **Radar ON**: TX board powered, RX board plugged into laptop
2. **Radar graph running**: `python radar_graph.py --port COM5 --baud 115200`
3. **Graph shows flat line**: Nobody between the boards
4. **Weapon OFF**: Weapon is NOT plugged into the battery bank yet. Keep both in your pocket.

### 9.2 — The demo sequence

#### 🟢 STEP A — Show the empty room (20 seconds)
- Point at the screen
- The line is flat, green "CLEAR" label is showing
- "This is a live Wi-Fi radar. The room is empty."

#### 🟢 STEP B — Prove motion works (30 seconds)
- Walk between the boards → spikes appear
- Stop → line goes flat again
- "See? It detects real movement."

#### 🔴 STEP C — Activate SHADOW
- Reach into your pocket
- **Plug the battery bank into the weapon** (don't say anything!)
- Wait 3 seconds for it to boot
- Watch the screen...

#### 💥 THE BIG MOMENT
- The flat line **erupts into wild rhythmic spikes**
- Let the audience stare for 5-10 seconds
- "The radar says someone is walking. But look around — nobody is here."
- Pull out the device: "I just activated SHADOW."

#### ⚫ STEP D — Kill switch
- **Unplug the battery** from the weapon
- Line goes flat **instantly**
- "Ghost disappears."

#### 🔁 STEP E — Repeat 3 times for proof
- ON → spikes → OFF → flat (×3)

---

## 🆘 Troubleshooting Quick Reference

| Problem | Solution |
|---|---|
| **No COM port appears** | Try different USB cable (must be data cable), install CP2102/CH340 driver |
| **ESP-IDF build fails** | Make sure you're using v4.3, not v4.4 or v5.x |
| **No CSI_DATA in monitor** | Make sure TX board is powered and on same channel/SSID as RX |
| **Radar graph won't open** | Run `pip install -r requirements.txt` first to install all packages |
| **Graph is noisy when still** | Add `--window 25` to the radar_graph command |
| **Weapon has no effect on radar** | Check that `RADAR_CHANNEL` in the .ino matches the radar's channel (6) |
| **Arduino upload fails** | Hold the BOOT button while uploading, release when "Connecting..." |
| **LED not blinking on weapon** | Try changing `LED_PIN` from 2 to 5 or 22 in the .ino code |

---

## 📋 Quick Command Reference

```bash
# Install Python dependencies (one time only)
pip install -r requirements.txt

# Run radar graph (live from hardware)
python radar_graph.py --port COM5 --baud 115200

# Run radar graph (test mode, no hardware needed)
python radar_graph.py --test

# Run with extra smoothing (if noisy)
python radar_graph.py --port COM5 --baud 115200 --window 25

# List available COM ports
python radar_graph.py --list-ports
```
