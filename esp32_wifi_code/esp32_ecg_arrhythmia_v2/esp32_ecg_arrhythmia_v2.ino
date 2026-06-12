#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// =====================================================
// EDIT THESE 4 VALUES BEFORE UPLOADING
// =====================================================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL    = "https://YOUR-RENDER-APP.onrender.com/api/esp32/features";
const char* API_KEY       = "YOUR_ESP32_API_KEY";   // Must match Render env ESP32_API_KEY. Leave both empty if not used.
const char* DEVICE_ID     = "ESP32_AD8232_01";

// =====================================================
// OLED SETTINGS
// =====================================================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDR 0x3C
Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// =====================================================
// PIN SETTINGS - CHANGE ONLY IF YOUR WIRING IS DIFFERENT
// =====================================================
#define ECG_PIN   34    // AD8232 OUTPUT -> ESP32 GPIO34
#define LO_PLUS   32    // AD8232 LO+    -> ESP32 GPIO32
#define LO_MINUS  33    // AD8232 LO-    -> ESP32 GPIO33
#define SDA_PIN   21    // OLED SDA
#define SCL_PIN   22    // OLED SCL

// =====================================================
// SAMPLING / TIMING
// =====================================================
const unsigned long SAMPLE_INTERVAL_MS = 4;       // 250 Hz sampling rate
const unsigned long DISPLAY_INTERVAL_MS = 150;
const unsigned long SEND_INTERVAL_MS = 2500;
const unsigned long WIFI_CHECK_INTERVAL_MS = 5000;
const unsigned long REFRACTORY_PERIOD_MS = 250;   // prevents double-counting one beat
const unsigned long NO_BEAT_TIMEOUT_MS = 6000;

unsigned long lastSampleTime = 0;
unsigned long lastDisplayTime = 0;
unsigned long lastSendTime = 0;
unsigned long lastWiFiCheckTime = 0;
unsigned long lastBeatTime = 0;

// =====================================================
// ECG VARIABLES
// =====================================================
int rawECG = 0;
int leadOffPlus = 0;
int leadOffMinus = 0;

float baseline = 2048.0;
float highPassECG = 0.0;
float filteredECG = 0.0;
float previousAbsECG = 0.0;
float absECG = 0.0;

float signalLevel = 40.0;
float noiseLevel = 10.0;
float adaptiveThreshold = 25.0;

float preRR = 0.0;
float postRR = 0.0;
float rrDiff = 0.0;
float lastValidRR = 0.0;
float rPeak = 0.0;
float qrsInterval = 0.08;  // Debug/display only. ML V2 does not use QRS.
int bpm = 0;

bool featureReady = false;
bool validECG = false;
String statusText = "WAITING";
String messageText = "Waiting ECG";
int lastHttpCode = 0;

// =====================================================
// DISPLAY HELPERS
// =====================================================
void showMessage(String line1, String line2, String line3 = "") {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 8);
  display.println(line1);
  display.setCursor(0, 26);
  display.println(line2);
  if (line3.length() > 0) {
    display.setCursor(0, 44);
    display.println(line3);
  }
  display.display();
}

void startupScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("ECG Arrhythmia V2");
  display.setCursor(0, 16);
  display.println("ESP32 + AD8232");
  display.setCursor(0, 32);
  display.println("MIT-BIH ML Model");
  display.setCursor(0, 50);
  display.println("BPM + Normal/Abnormal");
  display.display();
  delay(1800);
}

void updateOLED() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(8, 0);
  display.print("ECG ARRHYTHMIA V2");
  display.drawLine(0, 12, 128, 12, SH110X_WHITE);

  display.setTextSize(2);
  if (leadOffPlus == 1 || leadOffMinus == 1 || statusText == "LEADS_OFF") {
    display.setCursor(16, 22);
    display.print("LEADS");
    display.setCursor(36, 42);
    display.print("OFF");
  } else if (statusText == "NORMAL") {
    display.setCursor(20, 30);
    display.print("NORMAL");
  } else if (statusText == "ABNORMAL") {
    display.setCursor(0, 30);
    display.print("ABNORMAL");
  } else {
    display.setCursor(12, 30);
    display.print("WAITING");
  }

  display.setTextSize(1);
  display.setCursor(0, 56);
  display.print("HR:");
  if (bpm > 0) display.print(bpm);
  else display.print("--");
  display.print(" BPM");

  display.setCursor(86, 56);
  display.print("WiFi:");
  display.print(WiFi.status() == WL_CONNECTED ? "OK" : "OFF");

  display.display();
}

// =====================================================
// WIFI / JSON HELPERS
// =====================================================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  showMessage("Connecting WiFi", WIFI_SSID, "Use 2.4 GHz only");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    showMessage("WiFi Connected", WiFi.localIP().toString(), "Render ready");
    delay(1000);
  } else {
    showMessage("WiFi Failed", "Check hotspot", "2.4 GHz only");
    delay(1500);
  }
}

String extractJsonString(String json, String key) {
  String searchKey = "\"" + key + "\"";
  int keyIndex = json.indexOf(searchKey);
  if (keyIndex < 0) return "";
  int colonIndex = json.indexOf(":", keyIndex);
  if (colonIndex < 0) return "";
  int firstQuote = json.indexOf("\"", colonIndex + 1);
  if (firstQuote < 0) return "";
  int secondQuote = json.indexOf("\"", firstQuote + 1);
  if (secondQuote < 0) return "";
  return json.substring(firstQuote + 1, secondQuote);
}

// =====================================================
// ECG SIGNAL PROCESSING
// =====================================================
void resetFeatures(String msg) {
  featureReady = false;
  validECG = false;
  bpm = 0;
  preRR = 0.0;
  postRR = 0.0;
  rrDiff = 0.0;
  lastValidRR = 0.0;
  rPeak = 0.0;
  qrsInterval = 0.08;
  statusText = "WAITING";
  messageText = msg;
}

void processECGSample(unsigned long nowMs) {
  leadOffPlus = digitalRead(LO_PLUS);
  leadOffMinus = digitalRead(LO_MINUS);
  rawECG = analogRead(ECG_PIN);

  if (leadOffPlus == 1 || leadOffMinus == 1) {
    statusText = "LEADS_OFF";
    messageText = "Check electrodes";
    featureReady = false;
    validECG = false;
    return;
  }

  // Raw ECG from AD8232 should normally sit around mid-scale and move up/down.
  if (rawECG < 100 || rawECG > 4000) {
    resetFeatures("Raw ECG out of range");
    return;
  }

  // Simple baseline removal + smoothing. This is intentionally lightweight for ESP32.
  baseline = 0.995 * baseline + 0.005 * rawECG;
  highPassECG = rawECG - baseline;
  filteredECG = 0.85 * filteredECG + 0.15 * highPassECG;
  absECG = fabs(filteredECG);

  adaptiveThreshold = noiseLevel + 0.45 * (signalLevel - noiseLevel);
  if (adaptiveThreshold < 18.0) adaptiveThreshold = 18.0;

  bool aboveThreshold = absECG > adaptiveThreshold;
  bool rising = absECG > previousAbsECG;
  bool refractoryOK = (nowMs - lastBeatTime) > REFRACTORY_PERIOD_MS;

  if (aboveThreshold && rising && refractoryOK) {
    rPeak = rawECG;
    signalLevel = 0.125 * absECG + 0.875 * signalLevel;

    if (lastBeatTime > 0) {
      float currentRR = (nowMs - lastBeatTime) / 1000.0;

      if (currentRR >= 0.30 && currentRR <= 2.00) {
        if (lastValidRR >= 0.30 && lastValidRR <= 2.00) {
          preRR = lastValidRR;
          postRR = currentRR;
          rrDiff = fabs(preRR - postRR);
          bpm = (int)(60.0 / postRR + 0.5);

          featureReady = true;
          validECG = true;
          messageText = "Feature ready";

          Serial.println("===== ECG FEATURE READY =====");
          Serial.print("pre_rr_s: "); Serial.println(preRR, 4);
          Serial.print("post_rr_s: "); Serial.println(postRR, 4);
          Serial.print("rr_diff_s: "); Serial.println(rrDiff, 4);
          Serial.print("BPM: "); Serial.println(bpm);
          Serial.print("raw_r_peak: "); Serial.println(rPeak, 1);
          Serial.print("threshold: "); Serial.println(adaptiveThreshold, 2);
        }
        lastValidRR = currentRR;
      }
    }
    lastBeatTime = nowMs;
  } else {
    // Update noise level slowly when there is no detected QRS peak.
    noiseLevel = 0.125 * absECG + 0.875 * noiseLevel;
  }

  if (lastBeatTime > 0 && (nowMs - lastBeatTime) > NO_BEAT_TIMEOUT_MS) {
    resetFeatures("No R-peak detected");
  }

  previousAbsECG = absECG;
}

// =====================================================
// SEND TO RENDER
// =====================================================
void sendFeaturesToRender() {
  if (leadOffPlus == 1 || leadOffMinus == 1) {
    statusText = "LEADS_OFF";
    messageText = "Check electrodes";
    return;
  }

  if (!featureReady || bpm <= 0) {
    statusText = "WAITING";
    messageText = "Waiting R-peaks";
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    statusText = "WAITING";
    messageText = "WiFi disconnected";
    connectWiFi();
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  https.setTimeout(12000);

  if (!https.begin(client, SERVER_URL)) {
    statusText = "WAITING";
    messageText = "HTTP begin failed";
    return;
  }

  https.addHeader("Content-Type", "application/json");
  if (String(API_KEY).length() > 0) {
    https.addHeader("X-API-Key", API_KEY);
  }

  String payload = "{";
  payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"pre_rr_s\":" + String(preRR, 4) + ",";
  payload += "\"post_rr_s\":" + String(postRR, 4) + ",";
  payload += "\"rr_diff_s\":" + String(rrDiff, 4) + ",";
  payload += "\"bpm\":" + String(bpm) + ",";
  payload += "\"heart_rate\":" + String(bpm) + ",";
  payload += "\"r_peak\":" + String(rPeak, 2) + ",";
  payload += "\"qrs_interval\":" + String(qrsInterval, 4) + ",";
  payload += "\"lo_plus\":" + String(leadOffPlus) + ",";
  payload += "\"lo_minus\":" + String(leadOffMinus);
  payload += "}";

  lastHttpCode = https.POST(payload);
  String response = https.getString();
  https.end();

  Serial.println("===== SEND TO RENDER =====");
  Serial.print("Payload: "); Serial.println(payload);
  Serial.print("HTTP Code: "); Serial.println(lastHttpCode);
  Serial.print("Response: "); Serial.println(response);

  if (lastHttpCode == 200 || lastHttpCode == 201) {
    String serverStatus = extractJsonString(response, "status");
    serverStatus.trim();
    serverStatus.toUpperCase();

    if (serverStatus == "NORMAL" || serverStatus == "ABNORMAL" || serverStatus == "LEADS_OFF") {
      statusText = serverStatus;
      messageText = "Saved to database";
    } else {
      statusText = "WAITING";
      messageText = "Server validation";
    }
  } else {
    statusText = "WAITING";
    messageText = "HTTP error " + String(lastHttpCode);
  }
}

// =====================================================
// SETUP / LOOP
// =====================================================
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(5);

  pinMode(LO_PLUS, INPUT);
  pinMode(LO_MINUS, INPUT);

  analogReadResolution(12);
  analogSetPinAttenuation(ECG_PIN, ADC_11db);

  Wire.begin(SDA_PIN, SCL_PIN);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("OLED not detected. Check SDA/SCL and OLED address.");
    while (true) delay(1000);
  }

  startupScreen();
  connectWiFi();
}

void loop() {
  unsigned long nowMs = millis();

  if (nowMs - lastWiFiCheckTime >= WIFI_CHECK_INTERVAL_MS) {
    lastWiFiCheckTime = nowMs;
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
  }

  if (nowMs - lastSampleTime >= SAMPLE_INTERVAL_MS) {
    lastSampleTime = nowMs;
    processECGSample(nowMs);
  }

  if (nowMs - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = nowMs;
    sendFeaturesToRender();
  }

  if (nowMs - lastDisplayTime >= DISPLAY_INTERVAL_MS) {
    lastDisplayTime = nowMs;
    updateOLED();
  }
}
