#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

const char* WIFI_SSID = "Safiah’s Iphone";
const char* WIFI_PASSWORD = "safiah123";
const char* SERVER_URL = "https://ecg-dashboard-jf8e.onrender.com/api/esp32/features";
const char* API_KEY = "safiah_ecg_2026";
const char* DEVICE_ID = "ESP32_AD8232_01";

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDR 0x3C

Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

#define ECG_PIN 34
#define LO_PLUS 32
#define LO_MINUS 33
#define SDA_PIN 21
#define SCL_PIN 22

unsigned long lastSampleTime = 0;
unsigned long lastDisplayTime = 0;
unsigned long lastFeatureSendTime = 0;
unsigned long lastWiFiCheckTime = 0;
unsigned long lastRPeakTime = 0;

const unsigned long sampleInterval = 4;
const unsigned long displayInterval = 100;
const unsigned long featureSendInterval = 2000;
const unsigned long wifiCheckInterval = 5000;
const unsigned long refractoryPeriod = 500;

int rawECG = 0;
int leadOffPlus = 0;
int leadOffMinus = 0;

float filteredECG = 0;
float previousFilteredECG = 0;
float minECG = -300;
float maxECG = 300;
float threshold = 0;
bool firstSample = true;
bool validECGSignal = false;

const int RAW_ECG_MIN = 300;
const int RAW_ECG_MAX = 3800;
const float MIN_ECG_RANGE = 120.0;

float xBuffer[5] = {0, 0, 0, 0, 0};
float yBuffer[5] = {0, 0, 0, 0, 0};
float butterECG = 0;

float preRR = 0.0;
float postRR = 0.0;
float rPeak = 0.0;
float qrsInterval = 0.08;
float currentRR = 0.0;
float lastValidRR = 0.0;

int bpm = 0;
bool featureReady = false;
bool newFeatureAvailable = false;
unsigned long featureCreatedTime = 0;
const unsigned long featureValidDuration = 1500;

String mlStatus = "WAITING";
String serverMessage = "Waiting ECG";
int lastHttpCode = 0;

void resetECGFeature(String message) {
  featureReady = false;
  newFeatureAvailable = false;

  bpm = 0;
  preRR = 0.0;
  postRR = 0.0;
  rPeak = 0.0;
  qrsInterval = 0.08;
  currentRR = 0.0;
  lastValidRR = 0.0;

  lastRPeakTime = 0;

  mlStatus = "WAITING";
  serverMessage = message;
}

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

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  showMessage("Connecting WiFi", WIFI_SSID, "Please wait...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttempt = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 20000) {
    delay(500);
  }

  if (WiFi.status() == WL_CONNECTED) {
    showMessage("WiFi Connected", WiFi.localIP().toString(), "Render Ready");
    delay(1000);
  } else {
    showMessage("WiFi Failed", "Check hotspot", "2.4GHz only");
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

float estimateQRSInterval() {
  return 0.08;
}

void detectRPeak(unsigned long currentTime) {
  float range = maxECG - minECG;

  if (range < MIN_ECG_RANGE) return;

  threshold = minECG + (range * 0.80);

  bool crossingThreshold = (filteredECG > threshold && previousFilteredECG <= threshold);
  bool enoughTimePassed = (currentTime - lastRPeakTime > refractoryPeriod);

  if (crossingThreshold && enoughTimePassed) {
    rPeak = rawECG;

    if (lastRPeakTime > 0) {
      currentRR = (currentTime - lastRPeakTime) / 1000.0;

      if (currentRR > 0.3 && currentRR < 2.0) {
        if (lastValidRR > 0.3 && lastValidRR < 2.0) {
          preRR = lastValidRR;
          postRR = currentRR;
          bpm = (int)(60.0 / currentRR);
          qrsInterval = estimateQRSInterval();

          featureReady = true;
          newFeatureAvailable = true;
          featureCreatedTime = currentTime;

          Serial.println("New ECG feature ready");
          Serial.print("preRR: "); Serial.println(preRR, 4);
          Serial.print("postRR: "); Serial.println(postRR, 4);
          Serial.print("rPeak: "); Serial.println(rPeak, 2);
          Serial.print("qrs: "); Serial.println(qrsInterval, 4);
          Serial.print("BPM: "); Serial.println(bpm);
        }

        lastValidRR = currentRR;
      } else {
        resetECGFeature("Invalid RR");
      }
    }

    lastRPeakTime = currentTime;
  }
}

void sendFeaturesToRender() {
  if (leadOffPlus == 1 || leadOffMinus == 1) {
    mlStatus = "LEADS_OFF";
    serverMessage = "Check electrodes";
    return;
  }

  if (!validECGSignal) {
    resetECGFeature("No valid ECG");
    return;
  }

  if (!featureReady || !newFeatureAvailable || millis() - featureCreatedTime > featureValidDuration) {
    mlStatus = "WAITING";
    serverMessage = "Waiting new ECG";
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    mlStatus = "WAITING";
    serverMessage = "WiFi not connected";
    connectWiFi();
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  https.setTimeout(10000);

  if (!https.begin(client, SERVER_URL)) {
    mlStatus = "WAITING";
    serverMessage = "HTTP failed";
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
  payload += "\"heart_rate\":" + String(bpm) + ",";
  payload += "\"lo_plus\":" + String(leadOffPlus) + ",";
  payload += "\"lo_minus\":" + String(leadOffMinus);
  payload += "}";

  lastHttpCode = https.POST(payload);
  String response = https.getString();
  https.end();

  Serial.print("Payload: ");
  Serial.println(payload);
  Serial.print("HTTP Code: ");
  Serial.println(lastHttpCode);
  Serial.print("Response: ");
  Serial.println(response);

  if (lastHttpCode == 200 || lastHttpCode == 201) {
    newFeatureAvailable = false;
    featureReady = false;

    String status = extractJsonString(response, "status");
    status.trim();
    status.toUpperCase();

    if (status == "NORMAL") {
      mlStatus = "NORMAL";
      serverMessage = "Saved";
    } else if (status == "ABNORMAL") {
      mlStatus = "ABNORMAL";
      serverMessage = "Saved";
    } else if (status == "LEADS_OFF") {
      mlStatus = "LEADS_OFF";
      serverMessage = "Check electrodes";
    } else {
      mlStatus = "WAITING";
      serverMessage = "Signal validation";
    }
  } else {
    mlStatus = "WAITING";
    serverMessage = "HTTP error";
  }
}

void startupScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Portable Real-Time");
  display.setCursor(0, 14);
  display.println("ECG Arrhythmia");
  display.setCursor(0, 28);
  display.println("Detection System");
  display.setCursor(0, 46);
  display.println("ESP32 + AD8232 + ML");
  display.display();
  delay(1500);
}

void updateOLED() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  // =========================
  // TITLE
  // =========================
  display.setTextSize(1);
  display.setCursor(8, 0);
  display.print("ECG ARRHYTHMIA");

  display.setCursor(4, 10);
  display.print("DETECTION & CLASS");

  display.drawLine(0, 21, 128, 21, SH110X_WHITE);

  // =========================
  // BIG STATUS DISPLAY
  // =========================
  display.setTextSize(2);

  if (leadOffPlus == 1 || leadOffMinus == 1 || mlStatus == "LEADS_OFF") {
    display.setCursor(16, 27);
    display.print("LEADS");
    display.setCursor(36, 45);
    display.print("OFF");
  } 
  else if (mlStatus == "NORMAL") {
    display.setCursor(20, 34);
    display.print("NORMAL");
  } 
  else if (mlStatus == "ABNORMAL") {
    display.setCursor(0, 34);
    display.print("ABNORMAL");
  } 
  else {
    display.setCursor(12, 34);
    display.print("WAITING");
  }

  // =========================
  // FOOTER
  // =========================
  display.setTextSize(1);

  display.setCursor(0, 56);
  if (bpm > 0) {
    display.print("HR:");
    display.print(bpm);
    display.print(" BPM");
  } else {
    display.print("HR:-- BPM");
  }

  display.setCursor(86, 56);
  display.print("WiFi:");
  display.print(WiFi.status() == WL_CONNECTED ? "OK" : "OFF");

  display.display();
}

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

  startupScreen();
  connectWiFi();
}

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastWiFiCheckTime >= wifiCheckInterval) {
    lastWiFiCheckTime = currentTime;
    if (WiFi.status() != WL_CONNECTED) {
      connectWiFi();
    }
  }

  if (currentTime - lastSampleTime >= sampleInterval) {
    lastSampleTime = currentTime;

    leadOffPlus = digitalRead(LO_PLUS);
    leadOffMinus = digitalRead(LO_MINUS);
    rawECG = analogRead(ECG_PIN);

    if (leadOffPlus == 1 || leadOffMinus == 1) {
      validECGSignal = false;
      resetECGFeature("Check electrodes");
      mlStatus = "LEADS_OFF";
    } 
    else if (rawECG < RAW_ECG_MIN || rawECG > RAW_ECG_MAX) {
      validECGSignal = false;
      resetECGFeature("No valid ECG");
    } 
    else {
      previousFilteredECG = filteredECG;
      butterECG = butterworthFilter((float)rawECG);
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

      float ecgRange = maxECG - minECG;

      if (ecgRange < MIN_ECG_RANGE) {
        validECGSignal = false;
        resetECGFeature("No real ECG");
      } else {
        validECGSignal = true;
        detectRPeak(currentTime);
      }

      if (lastRPeakTime > 0 && currentTime - lastRPeakTime > 2500) {
        validECGSignal = false;
        resetECGFeature("Waiting valid ECG");
      }
    }
  }

  if (currentTime - lastFeatureSendTime >= featureSendInterval) {
    lastFeatureSendTime = currentTime;
    sendFeaturesToRender();
  }

  if (currentTime - lastDisplayTime >= displayInterval) {
    lastDisplayTime = currentTime;
    updateOLED();
  }
}
