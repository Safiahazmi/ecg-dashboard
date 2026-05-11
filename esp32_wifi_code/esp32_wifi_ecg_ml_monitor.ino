#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// =====================================================
// WIFI + RENDER SERVER SETTINGS
// =====================================================
// IMPORTANT:
// 1) ESP32 only supports 2.4 GHz WiFi.
// 2) For iPhone hotspot, turn ON "Maximize Compatibility".
// 3) Make sure SSID is exactly the same as shown on your phone.
const char* WIFI_SSID = "Safiah’s Iphone";
const char* WIFI_PASSWORD = "safiah123";

// Replace this with your real Render dashboard URL.
// Example: https://ecg-dashboard-xxxx.onrender.com/api/esp32/features
const char* SERVER_URL = "https://ecg-dashboard-jf8e.onrender.com/api/esp32/features";

// Optional security key. If you set ESP32_API_KEY in Render, use the same value here.
// If you do not set ESP32_API_KEY in Render, this can stay empty.
const char* API_KEY = "safiah_ecg_2026";

const char* DEVICE_ID = "ESP32_AD8232_01";

// =====================================================
// OLED SETTINGS
// =====================================================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDR 0x3C

Adafruit_SH1106G display = Adafruit_SH1106G(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// =====================================================
// ESP32 PIN SETTINGS
// =====================================================
#define ECG_PIN 34       // AD8232 OUTPUT
#define LO_PLUS 32       // AD8232 LO+
#define LO_MINUS 33      // AD8232 LO-

#define SDA_PIN 21       // OLED SDA
#define SCL_PIN 22       // OLED SCL

// =====================================================
// TIMING SETTINGS
// =====================================================
unsigned long lastSampleTime = 0;
unsigned long lastDisplayTime = 0;
unsigned long lastHeartBlink = 0;
unsigned long lastFeatureSendTime = 0;
unsigned long lastRPeakTime = 0;
unsigned long lastWiFiCheckTime = 0;

const unsigned long sampleInterval = 4;           // 4 ms = 250 Hz
const unsigned long displayInterval = 100;        // OLED update speed
const unsigned long heartBlinkInterval = 500;     // heart blink
const unsigned long featureSendInterval = 2000;   // send features every 2 sec to Render
const unsigned long refractoryPeriod = 500;       // avoid false/double R peak
const unsigned long wifiCheckInterval = 5000;     // WiFi reconnect check

// =====================================================
// ECG VARIABLES
// =====================================================
int rawECG = 0;

float filteredECG = 0;
float previousFilteredECG = 0;

float minECG = -300;
float maxECG = 300;
float threshold = 0;

bool firstSample = true;
bool heartState = false;

int leadOffPlus = 0;
int leadOffMinus = 0;

// =====================================================
// BUTTERWORTH BANDPASS FILTER VARIABLES
// Bandpass 0.5 Hz - 40 Hz, Fs = 250 Hz
// =====================================================
float xBuffer[5] = {0, 0, 0, 0, 0};
float yBuffer[5] = {0, 0, 0, 0, 0};

float butterECG = 0;
float previousButterECG = 0;

// =====================================================
// ML FEATURE VARIABLES
// These are the 4 features required by ML model
// =====================================================
float preRR = 0.0;          // 0_pre-RR in seconds
float postRR = 0.0;         // 0_post-RR in seconds
float rPeak = 0.0;          // 0_rPeak in ADC/raw amplitude
float qrsInterval = 0.08;   // 0_qrs_interval in seconds

float previousRR = 0.0;
float currentRR = 0.0;

int bpm = 0;
bool featureReady = false;

// =====================================================
// BUFFER VARIABLES
// Kept for internal R-peak/structure consistency.
// Nothing is displayed as waveform on OLED.
// =====================================================
int waveform[128];
int waveformIndex = 0;

int lastRIndex = -1;
String mlStatus = "WAITING";
String serverMessage = "Waiting ML";
int lastHttpCode = 0;

// =====================================================
// DRAW HEART ICON
// =====================================================
void drawHeart(int x, int y, int size, bool filled) {
  if (filled) {
    display.fillCircle(x - size / 2, y - size / 2, size / 2, SH110X_WHITE);
    display.fillCircle(x + size / 2, y - size / 2, size / 2, SH110X_WHITE);
    display.fillTriangle(x - size, y - size / 4, x + size, y - size / 4, x, y + size, SH110X_WHITE);
  } else {
    display.drawCircle(x - size / 2, y - size / 2, size / 2, SH110X_WHITE);
    display.drawCircle(x + size / 2, y - size / 2, size / 2, SH110X_WHITE);
    display.drawLine(x - size, y - size / 4, x, y + size, SH110X_WHITE);
    display.drawLine(x + size, y - size / 4, x, y + size, SH110X_WHITE);
  }
}

// =====================================================
// OLED SMALL MESSAGE
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

// =====================================================
// WIFI CONNECT
// =====================================================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  showMessage("Connecting WiFi", WIFI_SSID, "Please wait...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttempt = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 20000) {
    delay(500);
    display.print(".");
    display.display();
  }

  if (WiFi.status() == WL_CONNECTED) {
    showMessage("WiFi Connected", WiFi.localIP().toString(), "Render Ready");
    delay(1200);
  } else {
    showMessage("WiFi Failed", "Check SSID/pass", "or iPhone hotspot");
    delay(1800);
  }
}

// =====================================================
// SIMPLE JSON STRING VALUE EXTRACTOR
// Extracts: "status":"NORMAL"
// =====================================================
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
// SEND FEATURES TO RENDER API USING WIFI
// =====================================================
void sendFeaturesToRender() {
  if (leadOffPlus == 1 || leadOffMinus == 1) {
    mlStatus = "LEADS_OFF";
    serverMessage = "Check electrodes";
    return;
  }

  if (!featureReady) {
    mlStatus = "WAITING";
    serverMessage = "Waiting features";
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    mlStatus = "WAITING";
    serverMessage = "WiFi not connected";
    connectWiFi();
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();  // Prototype use: skip certificate validation for Render HTTPS

  HTTPClient https;
  https.setTimeout(10000);

  if (!https.begin(client, SERVER_URL)) {
    mlStatus = "WAITING";
    serverMessage = "HTTP begin failed";
    return;
  }

  https.addHeader("Content-Type", "application/json");

  if (String(API_KEY).length() > 0) {
    https.addHeader("X-API-Key", API_KEY);
  }

  String payload = "{";
  payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"pre_rr\":" + String(preRR, 4) + ",";
  payload += "\"post_rr\":" + String(postRR, 4) + ",";
  payload += "\"r_peak\":" + String(rPeak, 2) + ",";
  payload += "\"qrs_interval\":" + String(qrsInterval, 4) + ",";
  payload += "\"lo_plus\":" + String(leadOffPlus) + ",";
  payload += "\"lo_minus\":" + String(leadOffMinus);
  payload += "}";

  lastHttpCode = https.POST(payload);
  String response = https.getString();
  https.end();

  Serial.print("HTTP Code: ");
  Serial.println(lastHttpCode);
  Serial.print("Response: ");
  Serial.println(response);

  if (lastHttpCode == 200 || lastHttpCode == 201) {
    String status = extractJsonString(response, "status");
    status.trim();
    status.toUpperCase();

    if (status == "NORMAL") {
      mlStatus = "NORMAL";
      serverMessage = "Saved to Render";
    } else if (status == "ABNORMAL") {
      mlStatus = "ABNORMAL";
      serverMessage = "Saved to Render";
    } else if (status == "WAITING") {
      mlStatus = "WAITING";
      serverMessage = "Signal validation";
    } else if (status == "LEADS_OFF") {
      mlStatus = "LEADS_OFF";
      serverMessage = "Check electrodes";
    } else {
      mlStatus = "WAITING";
      serverMessage = "Unknown response";
    }
  } else {
    mlStatus = "WAITING";
    serverMessage = "HTTP error " + String(lastHttpCode);
  }
}

// =====================================================
// BUTTERWORTH BANDPASS FILTER FUNCTION
// Bandpass 0.5 Hz - 40 Hz, Sampling Frequency = 250 Hz
// =====================================================
float butterworthFilter(float input) {
  xBuffer[4] = xBuffer[3];
  xBuffer[3] = xBuffer[2];
  xBuffer[2] = xBuffer[1];
  xBuffer[1] = xBuffer[0];
  xBuffer[0] = input;

  yBuffer[4] = yBuffer[3];
  yBuffer[3] = yBuffer[2];
  yBuffer[2] = yBuffer[1];
  yBuffer[1] = yBuffer[0];

  yBuffer[0] =
      0.14244425 * xBuffer[0]
    - 0.28488849 * xBuffer[2]
    + 0.14244425 * xBuffer[4]
    + 2.66783480 * yBuffer[1]
    - 2.60211113 * yBuffer[2]
    + 1.19029069 * yBuffer[3]
    - 0.25610644 * yBuffer[4];

  return yBuffer[0];
}

// =====================================================
// STARTUP SCREEN
// =====================================================
void startupScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Portable Real-Time");

  display.setCursor(0, 12);
  display.println("ECG-Based");

  display.setCursor(0, 24);
  display.println("Arrhythmia Detection");

  display.setCursor(0, 42);
  display.println("ESP32 + AD8232 + ML");

  display.display();
  delay(1500);

  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(12, 8);
  display.println("ECG");

  display.setCursor(12, 30);
  display.println("READY");

  display.setTextSize(1);
  display.setCursor(5, 54);
  display.println("WiFi + Render API");

  display.display();
  delay(1200);
}

// =====================================================
// MAP FILTERED ECG TO INTERNAL BUFFER
// Not displayed on OLED.
// =====================================================
int mapECGToY(float value) {
  float range = maxECG - minECG;

  if (range < 30) {
    return 45;
  }

  int y = map((int)value, (int)minECG, (int)maxECG, 61, 31);
  y = constrain(y, 31, 61);

  return y;
}

// =====================================================
// ESTIMATE QRS INTERVAL
// =====================================================
float estimateQRSInterval() {
  // Prototype-level QRS interval estimation.
  // Exact QRS onset/offset is difficult with AD8232 without advanced processing.
  // 0.08 sec is used as a reasonable estimated QRS interval.
  return 0.08;
}

// =====================================================
// R-PEAK DETECTION + FEATURE CALCULATION
// =====================================================
void detectRPeak(unsigned long currentTime) {
  float range = maxECG - minECG;

  if (range < 30) {
    return;
  }

  threshold = minECG + (range * 0.80);

  bool crossingThreshold = (filteredECG > threshold && previousFilteredECG <= threshold);
  bool enoughTimePassed = (currentTime - lastRPeakTime > refractoryPeriod);

  if (crossingThreshold && enoughTimePassed) {
    rPeak = rawECG;
    lastRIndex = waveformIndex;

    if (lastRPeakTime > 0) {
      previousRR = currentRR;
      currentRR = (currentTime - lastRPeakTime) / 1000.0;

      if (currentRR > 0.3 && currentRR < 2.0) {
        preRR = previousRR;
        postRR = currentRR;

        bpm = (int)(60.0 / currentRR);
        qrsInterval = estimateQRSInterval();

        if (preRR > 0.0 && postRR > 0.0) {
          featureReady = true;
        }
      }
    }

    lastRPeakTime = currentTime;
  }
}

// =====================================================
// UPDATE OLED DISPLAY
// Only title + Beat status.
// No waveform, no BPM, no ECG value.
// =====================================================
void updateOLED() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(18, 0);
  display.print("ECG ML Monitor");

  if (heartState) {
    drawHeart(118, 8, 5, true);
  } else {
    drawHeart(118, 8, 5, false);
  }

  display.setTextSize(1);
  display.setCursor(0, 16);
  display.print("WiFi:");
  if (WiFi.status() == WL_CONNECTED) {
    display.print(" OK");
  } else {
    display.print(" OFF");
  }

  display.setCursor(68, 16);
  display.print("HTTP:");
  display.print(lastHttpCode);

  display.setCursor(0, 28);
  display.print("Beat:");

  if (leadOffPlus == 1 || leadOffMinus == 1 || mlStatus == "LEADS_OFF") {
    display.setTextSize(1);
    display.setCursor(38, 28);
    display.print("LEADS OFF");

    display.setCursor(10, 44);
    display.print("Check electrodes");

    display.setCursor(36, 56);
    display.print("RA LA RL");

    display.display();
    return;
  }

  if (mlStatus == "NORMAL") {
    display.setTextSize(2);
    display.setCursor(22, 42);
    display.print("NORMAL");
  } else if (mlStatus == "ABNORMAL") {
    display.setTextSize(2);
    display.setCursor(5, 42);
    display.print("ABNORMAL");
  } else {
    display.setTextSize(1);
    display.setCursor(38, 40);
    display.print("WAITING ML");

    display.setCursor(0, 54);
    display.print(serverMessage.substring(0, 20));
  }

  display.display();
}

// =====================================================
// SETUP
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
    Serial.println("OLED not detected");
    while (true);
  }

  for (int i = 0; i < 128; i++) {
    waveform[i] = 45;
  }

  startupScreen();
  connectWiFi();
}

// =====================================================
// LOOP
// =====================================================
void loop() {
  unsigned long currentTime = millis();

  // Keep WiFi alive
  if (currentTime - lastWiFiCheckTime >= wifiCheckInterval) {
    lastWiFiCheckTime = currentTime;
    if (WiFi.status() != WL_CONNECTED) {
      connectWiFi();
    }
  }

  // ECG sampling
  if (currentTime - lastSampleTime >= sampleInterval) {
    lastSampleTime = currentTime;

    leadOffPlus = digitalRead(LO_PLUS);
    leadOffMinus = digitalRead(LO_MINUS);
    rawECG = analogRead(ECG_PIN);

    previousButterECG = butterECG;
    butterECG = butterworthFilter((float)rawECG);

    previousFilteredECG = filteredECG;
    filteredECG = butterECG;

    if (firstSample) {
      minECG = filteredECG - 100;
      maxECG = filteredECG + 100;
      firstSample = false;
    }

    if (filteredECG < minECG) {
      minECG = filteredECG;
    } else {
      minECG = minECG + 0.005 * (filteredECG - minECG);
    }

    if (filteredECG > maxECG) {
      maxECG = filteredECG;
    } else {
      maxECG = maxECG + 0.005 * (filteredECG - maxECG);
    }

    waveform[waveformIndex] = mapECGToY(filteredECG);

    if (leadOffPlus == 0 && leadOffMinus == 0) {
      detectRPeak(currentTime);
    } else {
      featureReady = false;
      bpm = 0;
      preRR = 0.0;
      postRR = 0.0;
      rPeak = 0.0;
      qrsInterval = 0.08;
      mlStatus = "LEADS_OFF";
      serverMessage = "Check electrodes";
    }

    waveformIndex = (waveformIndex + 1) % 128;
  }

  // Send features to Render API every 2 seconds
  if (currentTime - lastFeatureSendTime >= featureSendInterval) {
    lastFeatureSendTime = currentTime;
    sendFeaturesToRender();
  }

  // Heart blink animation
  if (currentTime - lastHeartBlink >= heartBlinkInterval) {
    lastHeartBlink = currentTime;
    heartState = !heartState;
  }

  // Update OLED
  if (currentTime - lastDisplayTime >= displayInterval) {
    lastDisplayTime = currentTime;
    updateOLED();
  }
}
