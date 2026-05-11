const api = {
    latest: "/api/latest",
    history: "/api/history",
    stats: "/api/stats",
    db: "/api/db-status",
    patient: "/api/patient",
    exportExcel: "/api/export-excel",
};

let currentLang = localStorage.getItem("ecgDashboardLang") || "en";
let latestCache = null;
let historyCache = [];
let statsCache = {};
let dbCache = null;
let patientCache = null;

const i18n = {
    en: {
        brand_title: "ECG Dashboard",
        brand_subtitle: "Arrhythmia Detection",
        nav_dashboard: "Dashboard",
        nav_team: "Project Team",
        nav_patient: "Patient Biodata",
        nav_live: "Live ECG",
        nav_prediction: "Prediction",
        nav_history: "History",
        nav_database: "Database",
        system_status: "System Status",
        main_title: "Portable Real-Time ECG-Based Arrhythmia Detection Dashboard",
        live_status: "Live",
        current_classification: "Current ECG Classification",
        last_update: "Last Update",
        device: "Device",
        detection_summary: "Detection Summary",
        normal_abnormal: "Normal / Abnormal",
        normal: "Normal",
        abnormal: "Abnormal",
        pre_rr_desc: "Preceding RR interval",
        post_rr_desc: "Following RR interval",
        rpeak_desc: "R peak raw amplitude",
        qrs_desc: "QRS duration",
        feature_trend: "ECG Feature Trend",
        auto_refresh: "Auto refresh",
        time_trend: "RR/QRS time trend",
        rpeak_trend: "R-peak trend",
        recent_prediction_history: "Recent Prediction History",
        view_all: "View All",
        project_team: "Project Team",
        team_heading: "Supervisor & Student Roles",
        team_intro: "These roles can be shown during project presentation, poster, or dashboard demonstration.",
        supervisor: "Supervisor",
        supervisor_role: "Project supervision, guidance, evaluation direction, and academic monitoring.",
        team_member_1: "Team Member 1",
        team_member_2: "Team Member 2",
        safiah_role: "Hardware Development & Dashboard System",
        guga_role: "Report Documentation & Hardware Development",
        project_overview: "Project Overview",
        overview_badge: "ECG + ML + PostgreSQL",
        overview_text: "This project develops a portable ECG-based arrhythmia monitoring system using AD8232, ESP32, machine learning classification, and PostgreSQL database storage.",
        overview_point_1: "AD8232 captures ECG signal.",
        overview_point_2: "ESP32 sends ECG features to the Python bridge.",
        overview_point_3: "Machine learning classifies NORMAL or ABNORMAL.",
        overview_point_4: "PostgreSQL stores patient biodata and prediction history.",
        patient_biodata: "Patient Biodata",
        update_biodata: "Update",
        patient_heading: "Patient Information",
        patient_intro: "Enter the name and age of the person using this ECG monitoring system.",
        patient_form_title: "Register / Update Patient Biodata",
        patient_name: "Patient Name",
        patient_age: "Age",
        save_patient: "Save Patient Biodata",
        current_patient: "Current Patient",
        registered_at: "Registered At",
        patient_note: "This biodata identifies the person currently using the prototype during testing or demonstration.",
        patient_saved: "Patient biodata saved successfully.",
        patient_save_failed: "Unable to save patient biodata.",
        no_patient: "No patient biodata yet",
        export_excel: "Export Excel",
        live_ecg: "Live ECG",
        live_heading: "Real-Time ECG Signal / Feature Monitoring",
        live_intro: "This page is used to view incoming ECG trend from AD8232 + ESP32. If raw ECG is not stored, this chart displays real-time extracted feature trend from PostgreSQL.",
        ecg_trend: "ECG Trend",
        unit_guide: "Feature Unit Guide",
        unit_pre_post: "<b>0_pre-RR</b> and <b>0_post-RR</b> are RR interval timing features. They are displayed in <b>milliseconds (ms)</b>.",
        unit_qrs: "<b>0_qrs_interval</b> is QRS duration. It is displayed in <b>milliseconds (ms)</b>.",
        unit_rpeak: "<b>0_rPeak</b> is the detected ECG peak amplitude from hardware. It is displayed as <b>ADC/raw amplitude</b>, not ms.",
        prediction: "Prediction",
        prediction_heading: "Latest ML Classification Result",
        prediction_intro: "The dashboard displays the result already predicted by the trained machine learning model.",
        latest_prediction: "Latest Prediction",
        confidence: "Confidence",
        features_used: "Features Used by Model",
        history: "History",
        history_heading: "Stored Prediction Records",
        history_intro: "Prediction history is read from PostgreSQL. Normal and Abnormal results are kept for monitoring records.",
        recent_records: "Recent Records",
        time: "Time",
        no_data_yet: "No data yet",
        database: "Database",
        database_heading: "PostgreSQL Connection & System Flow",
        database_intro: "This page confirms that ECG prediction data is stored and retrieved from PostgreSQL.",
        status: "Status",
        database_name: "Database name",
        system_flow: "System Flow",
        flow_1: "AD8232 ECG sensor collects ECG signal.",
        flow_2: "ESP32 sends ECG features to Python bridge.",
        flow_3: "ML model predicts Normal or Abnormal.",
        flow_4: "PostgreSQL stores prediction data.",
        flow_5: "Dashboard displays result and history.",
        waiting: "WAITING",
        waiting_note: "Waiting for latest ML prediction.",
        normal_note: "No arrhythmia detected from latest ML prediction.",
        abnormal_note: "Abnormal ECG pattern detected from latest ML prediction.",
        checking: "Checking...",
        connected: "Connected",
        disconnected: "Disconnected",
        records: "records",
        waiting_ecg_data: "Waiting for ECG data",
        waiting_postgresql: "Waiting for PostgreSQL records",
    },
    ms: {
        brand_title: "Papan Pemuka ECG",
        brand_subtitle: "Pengesanan Aritmia",
        nav_dashboard: "Papan Pemuka",
        nav_team: "Pasukan Projek",
        nav_patient: "Biodata Pesakit",
        nav_live: "ECG Langsung",
        nav_prediction: "Ramalan",
        nav_history: "Sejarah",
        nav_database: "Pangkalan Data",
        system_status: "Status Sistem",
        main_title: "Papan Pemuka Pengesanan Aritmia Berasaskan ECG Masa Nyata Mudah Alih",
        live_status: "Langsung",
        current_classification: "Klasifikasi ECG Semasa",
        last_update: "Kemaskini Terakhir",
        device: "Peranti",
        detection_summary: "Ringkasan Pengesanan",
        normal_abnormal: "Normal / Tidak Normal",
        normal: "Normal",
        abnormal: "Tidak Normal",
        pre_rr_desc: "Selang RR sebelum denyutan semasa",
        post_rr_desc: "Selang RR selepas denyutan semasa",
        rpeak_desc: "Amplitud mentah puncak R",
        qrs_desc: "Tempoh QRS",
        feature_trend: "Trend Ciri ECG",
        auto_refresh: "Auto segar semula",
        time_trend: "Trend masa RR/QRS",
        rpeak_trend: "Trend R-peak",
        recent_prediction_history: "Sejarah Ramalan Terkini",
        view_all: "Lihat Semua",
        project_team: "Pasukan Projek",
        team_heading: "Penyelia & Peranan Pelajar",
        team_intro: "Peranan ini boleh dipaparkan semasa pembentangan projek, poster atau demonstrasi dashboard.",
        supervisor: "Penyelia",
        supervisor_role: "Penyeliaan projek, bimbingan, hala tuju penilaian dan pemantauan akademik.",
        team_member_1: "Ahli Pasukan 1",
        team_member_2: "Ahli Pasukan 2",
        safiah_role: "Pembangunan Perkakasan & Sistem Dashboard",
        guga_role: "Dokumentasi Laporan & Pembangunan Perkakasan",
        project_overview: "Gambaran Keseluruhan Projek",
        overview_badge: "ECG + ML + PostgreSQL",
        overview_text: "Projek ini membangunkan sistem pemantauan aritmia berasaskan ECG mudah alih menggunakan AD8232, ESP32, klasifikasi machine learning dan penyimpanan data PostgreSQL.",
        overview_point_1: "AD8232 menangkap isyarat ECG.",
        overview_point_2: "ESP32 menghantar ciri ECG kepada Python bridge.",
        overview_point_3: "Machine learning mengklasifikasikan NORMAL atau TIDAK NORMAL.",
        overview_point_4: "PostgreSQL menyimpan biodata pesakit dan sejarah ramalan.",
        patient_biodata: "Biodata Pesakit",
        update_biodata: "Kemaskini",
        patient_heading: "Maklumat Pesakit",
        patient_intro: "Masukkan nama dan umur individu yang menggunakan sistem pemantauan ECG ini.",
        patient_form_title: "Daftar / Kemaskini Biodata Pesakit",
        patient_name: "Nama Pesakit",
        patient_age: "Umur",
        save_patient: "Simpan Biodata Pesakit",
        current_patient: "Pesakit Semasa",
        registered_at: "Masa Daftar",
        patient_note: "Biodata ini mengenal pasti individu yang sedang menggunakan prototaip semasa ujian atau demonstrasi.",
        patient_saved: "Biodata pesakit berjaya disimpan.",
        patient_save_failed: "Biodata pesakit tidak berjaya disimpan.",
        no_patient: "Biodata pesakit belum dimasukkan",
        export_excel: "Eksport Excel",
        live_ecg: "ECG Langsung",
        live_heading: "Pemantauan Isyarat / Ciri ECG Masa Nyata",
        live_intro: "Halaman ini digunakan untuk melihat trend ECG masuk daripada AD8232 + ESP32. Jika raw ECG tidak disimpan, graf ini memaparkan trend ciri yang diekstrak secara masa nyata daripada PostgreSQL.",
        ecg_trend: "Trend ECG",
        unit_guide: "Panduan Unit Ciri",
        unit_pre_post: "<b>0_pre-RR</b> dan <b>0_post-RR</b> ialah ciri masa selang RR. Ia dipaparkan dalam <b>milisaat (ms)</b>.",
        unit_qrs: "<b>0_qrs_interval</b> ialah tempoh QRS. Ia dipaparkan dalam <b>milisaat (ms)</b>.",
        unit_rpeak: "<b>0_rPeak</b> ialah amplitud puncak ECG yang dikesan daripada perkakasan. Ia dipaparkan sebagai <b>ADC/amplitud mentah</b>, bukan ms.",
        prediction: "Ramalan",
        prediction_heading: "Keputusan Klasifikasi ML Terkini",
        prediction_intro: "Dashboard memaparkan keputusan yang telah diramal oleh model machine learning yang dilatih.",
        latest_prediction: "Ramalan Terkini",
        confidence: "Keyakinan",
        features_used: "Ciri yang Digunakan oleh Model",
        history: "Sejarah",
        history_heading: "Rekod Ramalan yang Disimpan",
        history_intro: "Sejarah ramalan dibaca daripada PostgreSQL. Keputusan Normal dan Tidak Normal disimpan sebagai rekod pemantauan.",
        recent_records: "Rekod Terkini",
        time: "Masa",
        no_data_yet: "Tiada data lagi",
        database: "Pangkalan Data",
        database_heading: "Sambungan PostgreSQL & Aliran Sistem",
        database_intro: "Halaman ini mengesahkan bahawa data ramalan ECG disimpan dan dibaca daripada PostgreSQL.",
        status: "Status",
        database_name: "Nama pangkalan data",
        system_flow: "Aliran Sistem",
        flow_1: "Sensor ECG AD8232 mengumpul isyarat ECG.",
        flow_2: "ESP32 menghantar ciri ECG kepada Python bridge.",
        flow_3: "Model ML meramal Normal atau Tidak Normal.",
        flow_4: "PostgreSQL menyimpan data ramalan.",
        flow_5: "Dashboard memaparkan keputusan dan sejarah.",
        waiting: "MENUNGGU",
        waiting_note: "Menunggu ramalan ML terkini.",
        normal_note: "Tiada aritmia dikesan daripada ramalan ML terkini.",
        abnormal_note: "Corak ECG tidak normal dikesan daripada ramalan ML terkini.",
        checking: "Sedang semak...",
        connected: "Bersambung",
        disconnected: "Terputus",
        records: "rekod",
        waiting_ecg_data: "Menunggu data ECG",
        waiting_postgresql: "Menunggu rekod PostgreSQL",
    },
};

function t(key) {
    return i18n[currentLang][key] || i18n.en[key] || key;
}

function applyLanguage(lang) {
    currentLang = lang;
    localStorage.setItem("ecgDashboardLang", lang);
    document.documentElement.lang = lang === "ms" ? "ms" : "en";

    document.querySelectorAll("[data-i18n]").forEach((element) => {
        const key = element.dataset.i18n;
        const value = t(key);
        if (value.includes("<")) {
            element.innerHTML = value;
        } else {
            element.textContent = value;
        }
    });

    document.querySelectorAll(".lang-btn").forEach((button) => {
        button.classList.toggle("active", button.dataset.lang === lang);
    });

    setClassification(latestCache && !latestCache.error ? latestCache : null);
    setStats(statsCache && !statsCache.error ? statsCache : {});
    renderRecent(Array.isArray(historyCache) ? historyCache : []);
    renderHistory(Array.isArray(historyCache) ? historyCache : []);
    setPatient(patientCache && !patientCache.error ? patientCache : null);
    refreshDbStatusLabels();
}

function setActivePage(targetId) {
    document.querySelectorAll(".page-section").forEach((section) => {
        section.classList.toggle("active", section.id === targetId);
    });

    document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.target === targetId);
    });

    window.location.hash = targetId.replace("-page", "");
}

function initNavigation() {
    document.querySelectorAll(".nav-item, .text-button").forEach((button) => {
        button.addEventListener("click", () => setActivePage(button.dataset.target));
    });

    document.querySelectorAll(".lang-btn").forEach((button) => {
        button.addEventListener("click", () => applyLanguage(button.dataset.lang));
    });

    initPatientForm();
    initExportButton();

    const hash = window.location.hash.replace("#", "");
    const target = hash ? `${hash}-page` : "dashboard-page";
    if (document.getElementById(target)) {
        setActivePage(target);
    } else {
        setActivePage("dashboard-page");
    }

    applyLanguage(currentLang);
}

function cleanLabel(label) {
    if (!label) return t("waiting");
    const value = String(label).trim().toUpperCase();
    if (value === "ABNORMAL") return currentLang === "ms" ? "TIDAK NORMAL" : "ABNORMAL";
    if (value === "NORMAL") return "NORMAL";
    return value || t("waiting");
}

function rawLabel(label) {
    return String(label || "").trim().toUpperCase();
}

function formatTimeMs(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    const raw = Number(value);
    const ms = Math.abs(raw) < 10 ? raw * 1000 : raw;
    return `${ms.toFixed(1)} ms`;
}

function formatRPeak(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    return `${Number(value).toFixed(2)} ADC`;
}

function formatConfidence(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
    return `${Number(value).toFixed(1)}%`;
}

function setPredictionStyle(label) {
    const displayLabel = cleanLabel(label);
    const raw = rawLabel(label);
    const isAbnormal = raw === "ABNORMAL";
    const isNormal = raw === "NORMAL";

    const elements = [
        document.getElementById("dashboardPredictionLabel"),
        document.getElementById("predictionPageLabel"),
    ];
    const icons = [
        document.getElementById("classificationIcon"),
        document.getElementById("predictionIcon"),
    ];

    elements.forEach((el) => {
        if (!el) return;
        el.textContent = displayLabel;
        el.classList.remove("is-normal", "is-abnormal", "is-waiting");
        el.classList.add(isAbnormal ? "is-abnormal" : isNormal ? "is-normal" : "is-waiting");
    });

    icons.forEach((icon) => {
        if (!icon) return;
        icon.textContent = isAbnormal ? "!" : isNormal ? "✓" : "…";
        icon.classList.remove("icon-normal", "icon-abnormal", "icon-waiting");
        icon.classList.add(isAbnormal ? "icon-abnormal" : isNormal ? "icon-normal" : "icon-waiting");
    });
}

function setClassification(data) {
    const raw = rawLabel(data?.prediction_label);
    const label = raw || "WAITING";
    setPredictionStyle(label);

    const note = raw === "ABNORMAL" ? t("abnormal_note") : raw === "NORMAL" ? t("normal_note") : t("waiting_note");
    document.getElementById("dashboardPredictionNote").textContent = note;
    document.getElementById("predictionPageNote").textContent = note;
    document.getElementById("dashboardLastUpdate").textContent = data?.timestamp || "--";
    document.getElementById("predictionLastUpdate").textContent = data?.timestamp || "--";
    document.getElementById("dashboardDeviceId").textContent = data?.device_id || "--";
    document.getElementById("predictionConfidence").textContent = formatConfidence(data?.confidence);
}

function setFeatureValues(data) {
    const preRR = formatTimeMs(data?.pre_rr);
    const postRR = formatTimeMs(data?.post_rr);
    const rPeak = formatRPeak(data?.r_peak);
    const qrs = formatTimeMs(data?.qrs_interval);

    ["dashPreRR", "predPreRR"].forEach((id) => document.getElementById(id).textContent = preRR);
    ["dashPostRR", "predPostRR"].forEach((id) => document.getElementById(id).textContent = postRR);
    ["dashRPeak", "predRPeak"].forEach((id) => document.getElementById(id).textContent = rPeak);
    ["dashQRS", "predQRS"].forEach((id) => document.getElementById(id).textContent = qrs);
}

function setPatient(patient) {
    const name = patient?.patient_name || "--";
    const age = patient?.age !== undefined && patient?.age !== null ? String(patient.age) : "--";
    const createdAt = patient?.created_at || "--";

    const dashboardName = document.getElementById("dashboardPatientName");
    const dashboardAge = document.getElementById("dashboardPatientAge");
    const currentName = document.getElementById("currentPatientName");
    const currentAge = document.getElementById("currentPatientAge");
    const currentCreatedAt = document.getElementById("currentPatientCreatedAt");
    const patientNameInput = document.getElementById("patientName");
    const patientAgeInput = document.getElementById("patientAge");

    if (dashboardName) dashboardName.textContent = name;
    if (dashboardAge) dashboardAge.textContent = age === "--" ? "--" : `${age} ${currentLang === "ms" ? "tahun" : "years"}`;
    if (currentName) currentName.textContent = name;
    if (currentAge) currentAge.textContent = age === "--" ? "--" : `${age} ${currentLang === "ms" ? "tahun" : "years"}`;
    if (currentCreatedAt) currentCreatedAt.textContent = createdAt;

    if (patient && !patient.error) {
        if (patientNameInput) patientNameInput.value = patient.patient_name || "";
        if (patientAgeInput) patientAgeInput.value = patient.age ?? "";
    }
}

async function refreshPatient() {
    try {
        const res = await fetch(api.patient);
        patientCache = res.ok ? await res.json() : null;
    } catch (err) {
        patientCache = null;
    }
    setPatient(patientCache && !patientCache.error ? patientCache : null);
}

function initPatientForm() {
    const form = document.getElementById("patientForm");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = document.getElementById("patientFormMessage");
        const patientName = document.getElementById("patientName").value.trim();
        const age = document.getElementById("patientAge").value;

        if (message) {
            message.textContent = t("checking");
            message.className = "form-message";
        }

        try {
            const res = await fetch(api.patient, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ patient_name: patientName, age }),
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || t("patient_save_failed"));

            patientCache = data;
            setPatient(data);
            if (message) {
                message.textContent = t("patient_saved");
                message.classList.add("success");
            }
        } catch (err) {
            if (message) {
                message.textContent = err.message || t("patient_save_failed");
                message.classList.add("error");
            }
        }
    });
}

function initExportButton() {
    const button = document.getElementById("exportExcelButton");
    if (!button) return;
    button.addEventListener("click", () => {
        window.location.href = api.exportExcel;
    });
}


function setStats(stats) {
    const total = Number(stats?.total_predictions || 0);
    const normal = Number(stats?.normal_count || 0);
    const abnormal = Number(stats?.abnormal_count || 0);
    const normalPct = total ? (normal / total) * 100 : 0;
    const abnormalPct = total ? (abnormal / total) * 100 : 0;

    document.getElementById("normalCountMain").textContent = normal;
    document.getElementById("abnormalCountMain").textContent = abnormal;
    document.getElementById("normalPercent").textContent = `${normalPct.toFixed(1)}%`;
    document.getElementById("abnormalPercent").textContent = `${abnormalPct.toFixed(1)}%`;
    document.getElementById("normalBar").style.width = `${normalPct || 0}%`;
    document.getElementById("abnormalBar").style.width = `${abnormalPct || 0}%`;
    document.getElementById("totalRecordText").textContent = `${total} ${t("records")}`;
}

function renderRecent(rows) {
    const container = document.getElementById("recentList");
    container.innerHTML = "";
    if (!rows || rows.length === 0) {
        container.innerHTML = `<div class="recent-row"><span class="pulse-dot"></span><div><strong>${t("no_data_yet")}</strong><small>${t("waiting_postgresql")}</small></div></div>`;
        return;
    }

    rows.slice(0, 5).forEach((row) => {
        const raw = rawLabel(row.prediction_label);
        const label = cleanLabel(row.prediction_label);
        const type = raw === "ABNORMAL" ? "abnormal" : "normal";
        const dotColor = raw === "ABNORMAL" ? "var(--red)" : "var(--green)";
        const div = document.createElement("div");
        div.className = "recent-row";
        div.innerHTML = `
            <span class="pulse-dot" style="background:${dotColor}; box-shadow:0 0 16px ${dotColor}"></span>
            <div><strong>${row.timestamp || "--"}</strong><small>${formatTimeMs(row.pre_rr)} · ${formatTimeMs(row.qrs_interval)}</small></div>
            <span class="pred-badge ${type}">${label}</span>
        `;
        container.appendChild(div);
    });
}

function renderHistory(rows) {
    const body = document.getElementById("historyBody");
    body.innerHTML = "";
    if (!rows || rows.length === 0) {
        body.innerHTML = `<tr><td colspan="7" class="empty-row">${t("no_data_yet")}</td></tr>`;
        return;
    }

    rows.forEach((row) => {
        const raw = rawLabel(row.prediction_label);
        const label = cleanLabel(row.prediction_label);
        const type = raw === "ABNORMAL" ? "abnormal" : "normal";
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.timestamp || "--"}</td>
            <td>${formatTimeMs(row.pre_rr)}</td>
            <td>${formatTimeMs(row.post_rr)}</td>
            <td>${formatRPeak(row.r_peak)}</td>
            <td>${formatTimeMs(row.qrs_interval)}</td>
            <td><span class="pred-badge ${type}">${label}</span></td>
            <td>${formatConfidence(row.confidence)}</td>
        `;
        body.appendChild(tr);
    });
}

function mapPoints(values, width, height, minValue, maxValue) {
    if (!values || values.length === 0) return "";
    const padTop = 26;
    const padBottom = 34;
    const usableHeight = height - padTop - padBottom;
    const range = maxValue - minValue || 1;
    const step = values.length > 1 ? width / (values.length - 1) : width;

    return values.map((value, index) => {
        const safe = Number.isFinite(Number(value)) ? Number(value) : minValue;
        const x = index * step;
        const y = padTop + (1 - (safe - minValue) / range) * usableHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
}

function drawGrid(svg, width, height) {
    if (!svg) return;
    svg.innerHTML = "";
    for (let i = 0; i <= 5; i++) {
        const y = 26 + i * ((height - 60) / 5);
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", "0");
        line.setAttribute("x2", String(width));
        line.setAttribute("y1", String(y));
        line.setAttribute("y2", String(y));
        line.setAttribute("class", "chart-grid-line");
        svg.appendChild(line);
    }
}

function addPolyline(svg, points, color, extraClass = "") {
    if (!svg || !points) return;
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", points);
    polyline.setAttribute("stroke", color);
    polyline.setAttribute("class", `chart-line ${extraClass}`);
    svg.appendChild(polyline);
}

function addWaitingText(svg) {
    if (!svg) return;
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", "50%");
    text.setAttribute("y", "50%");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("fill", "rgba(255,255,255,0.55)");
    text.setAttribute("font-size", "18");
    text.textContent = t("waiting_ecg_data");
    svg.appendChild(text);
}

function renderCharts(rows) {
    const dashboardSvg = document.getElementById("dashboardChart");
    const liveSvg = document.getElementById("liveChart");

    const widthDash = 850;
    const heightDash = 270;
    const widthLive = 980;
    const heightLive = 360;

    drawGrid(dashboardSvg, widthDash, heightDash);
    drawGrid(liveSvg, widthLive, heightLive);

    if (!rows || rows.length < 2) {
        addWaitingText(dashboardSvg);
        addWaitingText(liveSvg);
        return;
    }

    const ordered = [...rows].reverse().slice(-24);

    const timeTrend = ordered.map((row) => {
        const pre = Math.abs(Number(row.pre_rr || 0)) < 10 ? Number(row.pre_rr || 0) * 1000 : Number(row.pre_rr || 0);
        const post = Math.abs(Number(row.post_rr || 0)) < 10 ? Number(row.post_rr || 0) * 1000 : Number(row.post_rr || 0);
        const qrs = Math.abs(Number(row.qrs_interval || 0)) < 10 ? Number(row.qrs_interval || 0) * 1000 : Number(row.qrs_interval || 0);
        return (pre + post + qrs) / 3;
    });
    const rPeakTrend = ordered.map((row) => Number(row.r_peak || 0));

    const allTime = timeTrend.filter(Number.isFinite);
    const minTime = Math.min(...allTime);
    const maxTime = Math.max(...allTime);
    const allPeak = rPeakTrend.filter(Number.isFinite);
    const minPeak = Math.min(...allPeak);
    const maxPeak = Math.max(...allPeak);

    addPolyline(dashboardSvg, mapPoints(timeTrend, widthDash, heightDash, minTime, maxTime), "#8b5cf6");
    addPolyline(dashboardSvg, mapPoints(rPeakTrend, widthDash, heightDash, minPeak, maxPeak), "#45e07a", "chart-line-green");

    addPolyline(liveSvg, mapPoints(timeTrend, widthLive, heightLive, minTime, maxTime), "#8b5cf6");
    addPolyline(liveSvg, mapPoints(rPeakTrend, widthLive, heightLive, minPeak, maxPeak), "#45e07a", "chart-line-green");
}

function refreshDbStatusLabels() {
    const side = document.getElementById("sideConnection");
    const dbStatus = document.getElementById("dbStatus");
    const dbName = document.getElementById("dbName");

    if (!dbCache) {
        side.textContent = t("checking");
        dbStatus.textContent = t("checking");
        return;
    }

    dbName.textContent = dbCache.database || "ecg_db";
    if (dbCache.connected) {
        side.textContent = t("connected");
        dbStatus.textContent = t("connected");
        dbStatus.className = "connected";
    } else {
        side.textContent = t("disconnected");
        dbStatus.textContent = t("disconnected");
        dbStatus.className = "disconnected";
    }
}

async function refreshDbStatus() {
    try {
        const res = await fetch(api.db);
        dbCache = await res.json();
    } catch (err) {
        dbCache = { connected: false, database: "ecg_db" };
    }
    refreshDbStatusLabels();
}

async function refreshDashboard() {
    try {
        const [latestRes, historyRes, statsRes] = await Promise.all([
            fetch(api.latest),
            fetch(api.history),
            fetch(api.stats),
        ]);

        latestCache = latestRes.ok ? await latestRes.json() : null;
        historyCache = historyRes.ok ? await historyRes.json() : [];
        statsCache = statsRes.ok ? await statsRes.json() : {};

        const latest = latestCache && !latestCache.error ? latestCache : null;
        const history = Array.isArray(historyCache) ? historyCache : [];
        const stats = statsCache && !statsCache.error ? statsCache : {};

        setClassification(latest);
        setFeatureValues(latest);
        setStats(stats);
        renderRecent(history);
        renderHistory(history);
        renderCharts(history);
    } catch (err) {
        console.error("Dashboard refresh error:", err);
        latestCache = null;
        historyCache = [];
        statsCache = {};
        setClassification(null);
        setFeatureValues(null);
        renderRecent([]);
        renderHistory([]);
        renderCharts([]);
    }
}

initNavigation();
refreshDbStatus();
refreshPatient();
refreshDashboard();
setInterval(refreshDashboard, 3000);
setInterval(refreshPatient, 15000);
setInterval(refreshDbStatus, 8000);
