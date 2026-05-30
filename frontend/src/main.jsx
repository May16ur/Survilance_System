import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, RefreshCw } from "lucide-react";
import { getJson } from "./lib/api.js";
import { DEFAULT_CAMERAS, TCP_OPTIONS, TABS } from "./lib/constants.js";
import { Metric } from "./components/Metric.jsx";
import { DashboardPanel } from "./features/DashboardPanel.jsx";
import { StreamsPanel } from "./features/StreamsPanel.jsx";
import { UploadPanel } from "./features/UploadPanel.jsx";
import { LogsPanel } from "./features/LogsPanel.jsx";
import { ReportsPanel } from "./features/ReportsPanel.jsx";
import { TcpPanel } from "./features/TcpPanel.jsx";
import { VehicleMasterPanel } from "./features/VehicleMasterPanel.jsx";
import { AlertsPanel } from "./features/AlertsPanel.jsx";
import { ReceiverTable } from "./features/ReceiverTable.jsx";
import { MapPanel } from "./features/MapPanel.jsx";
import leftLogo from "./assets/etcp-left-logo.png";
import rightLogo from "./assets/etcp-right-logo.png";
import "./styles.css";

// App keeps page state and API actions; tab screens live in src/features.
function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [status, setStatus] = useState("Connecting to backend...");
  const [cameras, setCameras] = useState(DEFAULT_CAMERAS);
  const [tcpOptions, setTcpOptions] = useState(TCP_OPTIONS.map((key) => ({ key, label: key.toUpperCase() })));
  const [backendUrl, setBackendUrl] = useState("http://192.168.2.146:7073");
  const [cameraStats, setCameraStats] = useState({});
  const [running, setRunning] = useState({});
  const [uploadLogs, setUploadLogs] = useState([]);
  const [cameraLogs, setCameraLogs] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState(1);
  const [notifications, setNotifications] = useState([]);
  const [blacklist, setBlacklist] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [plateSearch, setPlateSearch] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [uploadRunning, setUploadRunning] = useState(false);
  const [previewTick, setPreviewTick] = useState(0);
  const [dashboard, setDashboard] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [diagnostic, setDiagnostic] = useState(null);
  const [reportRows, setReportRows] = useState([]);
  const [reportFilters, setReportFilters] = useState({ vehicle_type: "all", camera_id: "", start_date: "", end_date: "" });
  const [tcpName, setTcpName] = useState("kiari");
  const [tcpReport, setTcpReport] = useState(null);
  const [remaining, setRemaining] = useState(null);
  const [vehicleMaster, setVehicleMaster] = useState([]);
  const uploadRef = useRef(null);

  useEffect(() => {
    loadAppConfig();
    refreshHealth();
    refreshCounters();
    refreshNotifications();
    refreshBlacklist();
    loadDashboard();
    loadVehicleMaster();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      refreshCounters();
      if (activeTab === "dashboard") loadDashboard(false);
      if (activeTab === "receiver") refreshNotifications();
      if (activeTab === "alerts") refreshBlacklist();
      if (activeTab === "logs") loadCameraLogs(selectedCamera);
      if (activeTab === "upload" && uploadRunning) loadUploadLogs();
    }, 5000);
    return () => clearInterval(timer);
  }, [activeTab, selectedCamera, uploadRunning, cameras]);

  useEffect(() => {
    if (activeTab !== "streams" && activeTab !== "logs") return undefined;
    const timer = setInterval(() => {
      setPreviewTick((value) => value + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [activeTab]);

  async function refreshHealth() {
    try {
      const data = await getJson("/api/health");
      setStatus(data.success ? "Backend online" : "Backend unavailable");
    } catch {
      setStatus(`Backend offline. Start Flask on ${backendUrl}.`);
    }
  }

  async function loadAppConfig() {
    try {
      const data = await getJson("/api/app_config");
      const config = data.config || {};
      const configuredCameras = (config.cameras || []).map((camera) => ({
        id: camera.id,
        name: camera.name,
        url: camera.rtsp_url || "",
        tcp: camera.tcp || "",
        direction: camera.direction || "",
      }));
      if (configuredCameras.length) {
        setCameras(configuredCameras);
        setSelectedCamera(configuredCameras[0].id);
      } else {
        loadCameras();
      }
      const pairs = (config.tcp_pairs || []).map((pair) => ({
        key: pair.key,
        label: pair.label || String(pair.key || "").toUpperCase(),
      }));
      if (pairs.length) {
        setTcpOptions(pairs);
        setTcpName(pairs[0].key);
        loadTcpReport(pairs[0].key);
      }
      if (config.server?.public_url) {
        setBackendUrl(config.server.public_url);
      }
    } catch {
      loadCameras();
      loadTcpReport("kiari");
    }
  }

  async function loadCameras() {
    try {
      const data = await getJson("/api/cameras");
      if (!data.success) return;
      const activeIds = new Set(DEFAULT_CAMERAS.map((camera) => camera.id));
      setCameras((current) =>
        data.cameras
          .filter((camera) => activeIds.has(camera.id))
          .map((camera) => ({
            ...camera,
            url: current.find((item) => item.id === camera.id)?.url || "",
          }))
      );
    } catch {
      setCameras(DEFAULT_CAMERAS);
    }
  }

  async function refreshCounters() {
    const next = {};
    await Promise.all(
      cameras.slice(0, 14).map(async (camera) => {
        try {
          next[camera.id] = await getJson(`/api/camera_today_stats/${camera.id}`);
        } catch {
          next[camera.id] = { today_total: 0, today_mil: 0, today_civil: 0 };
        }
      })
    );
    setCameraStats(next);
  }

  async function loadDashboard(showStatus = true) {
    try {
      const [full, cmp, diag] = await Promise.all([
        getJson("/dashboard_full"),
        getJson("/api/camera_comparison"),
        getJson("/api/count_diagnostic"),
      ]);
      setDashboard(full);
      setComparison(cmp);
      setDiagnostic(diag);
      if (showStatus) setStatus("Dashboard refreshed.");
    } catch (e) {
      if (showStatus) setStatus(`Dashboard refresh failed: ${e.message}`);
    }
  }

  function updateCameraUrl(cameraId, url) {
    setCameras((items) => items.map((item) => (item.id === cameraId ? { ...item, url } : item)));
  }

  async function startCamera(camera) {
    if (!camera.url.trim()) {
      setStatus(`Camera ${camera.id} RTSP URL is missing.`);
      return;
    }
    try {
      setStatus(`Starting ${camera.name}...`);
      const data = await getJson("/preview/start_camera", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: camera.id, url: camera.url.trim() }),
      });
      setRunning((value) => ({ ...value, [camera.id]: true }));
      setStatus(data.message || `${camera.name} preview started without YOLO.`);
    } catch (e) {
      setStatus(`Camera start failed: ${e.message}`);
    }
  }

  async function registerAllStreams() {
    try {
      const urls = cameras.map((camera) => camera.url.trim());
      const data = await getJson("/start_streams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls }),
      });
      setStatus(data.message || "Streams registered.");
    } catch (e) {
      setStatus(`Stream registration failed: ${e.message}`);
    }
  }

  async function stopCamera(cameraId) {
    setRunning((value) => ({ ...value, [cameraId]: false }));
    try {
      await getJson("/preview/stop_camera", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: cameraId }),
      });
    } catch {
      // The browser preview stops immediately even if the backend stop request fails.
    }
  }

  async function uploadVideo() {
    const file = uploadRef.current?.files?.[0];
    if (!file) {
      setStatus("Choose a video file first.");
      return;
    }
    try {
      const formData = new FormData();
      formData.append("video", file);
      setStatus("Uploading video...");
      const data = await getJson("/upload_video", { method: "POST", body: formData });
      setUploadRunning(Boolean(data.success));
      setStatus(data.message || "Video processing started.");
      loadUploadLogs();
    } catch (e) {
      setStatus(`Upload pipeline unavailable: ${e.message}`);
    }
  }

  async function loadUploadLogs() {
    const data = await getJson("/api/upload_logs");
    setUploadLogs(data.logs || []);
  }

  async function loadCameraLogs(cameraId = selectedCamera) {
    setSelectedCamera(cameraId);
    const data = await getJson(`/api/camera_logs/${cameraId}?limit=300`);
    setCameraLogs(data.logs || []);
  }

  async function saveLogs() {
    try {
      const data = await getJson("/save_logs", { method: "POST" });
      setStatus(data.message || "Logs saved.");
    } catch (e) {
      setStatus(`Save logs unavailable: ${e.message}`);
    }
  }

  async function refreshNotifications() {
    try {
      const data = await getJson("/api/notifications/recent?limit=100");
      setNotifications(data.events || []);
    } catch {
      setNotifications([]);
    }
  }

  async function refreshBlacklist() {
    try {
      const [list, alertData] = await Promise.all([
        getJson("/api/blacklist"),
        getJson("/api/blacklist_alerts"),
      ]);
      setBlacklist(list.rows || []);
      setAlerts(alertData.alerts || []);
    } catch {
      setBlacklist([]);
      setAlerts([]);
    }
  }

  async function addBlacklist(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const license_plate = String(form.get("license_plate") || "").trim();
    const remarks = String(form.get("remarks") || "").trim();
    if (!license_plate) return;
    await getJson("/api/blacklist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_plate, remarks }),
    });
    event.currentTarget.reset();
    refreshBlacklist();
  }

  async function deleteBlacklist(plate) {
    await getJson(`/api/blacklist/${encodeURIComponent(plate)}`, { method: "DELETE" });
    refreshBlacklist();
  }

  async function searchPlate(event) {
    event.preventDefault();
    if (!plateSearch.trim()) return;
    const data = await getJson(`/api/search_license?query=${encodeURIComponent(plateSearch.trim())}`);
    setSearchResults(Array.isArray(data) ? data : data.rows || []);
  }

  async function loadReport(event) {
    event?.preventDefault();
    const params = new URLSearchParams();
    Object.entries(reportFilters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    params.set("limit", "2000");
    const data = await getJson(`/api/last_7_days_report?${params}`);
    setReportRows(data.rows || []);
    setStatus(`Loaded ${data.total || 0} report rows.`);
  }

  function downloadReport() {
    const params = new URLSearchParams();
    Object.entries(reportFilters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    window.open(`/download_last_7_days_report?${params}`, "_blank");
  }

  async function loadTcpReport(name = tcpName) {
    setTcpName(name);
    const data = await getJson(`/api/tcp_table/${name}?limit=1000`);
    setTcpReport(data);
    const rem = await getJson(`/api/remaining_vehicles?group=${name}`);
    setRemaining(rem);
  }

  async function loadVehicleMaster() {
    const data = await getJson("/api/vehicle_master");
    setVehicleMaster(data.rows || []);
  }

  async function importVehicleExcel() {
    const data = await getJson("/api/vehicle_master/import_excel", { method: "POST" });
    setStatus(data.message || "Vehicle Excel imported.");
    loadVehicleMaster();
    refreshNotifications();
    if (activeTab === "logs") loadCameraLogs(selectedCamera);
    if (activeTab === "tcp") loadTcpReport(tcpName);
  }

  async function saveVehicleMaster(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    const data = await getJson("/api/vehicle_master", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus(data.message || "Vehicle information saved.");
    event.currentTarget.reset();
    loadVehicleMaster();
  }

  async function deleteLog(row) {
    if (!row.id) return;
    const data = await getJson("/api/delete_log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_table: row.source_table || "vehicle_logs", id: row.id }),
    });
    setStatus(`Deleted ${data.deleted || 0} log row.`);
    loadCameraLogs(selectedCamera);
  }

  const totals = useMemo(() => {
    return Object.values(cameraStats).reduce(
      (acc, item) => ({
        total: acc.total + Number(item.today_total || 0),
        mil: acc.mil + Number(item.today_mil || 0),
        civil: acc.civil + Number(item.today_civil || 0),
      }),
      { total: 0, mil: 0, civil: 0 }
    );
  }, [cameraStats]);

  const activeLabel = TABS.find((tab) => tab.id === activeTab)?.label || "Dashboard";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img src={leftLogo} alt="e-TCP left insignia" />
          <div>
            <strong>e-TCP</strong>
            <span>Surveillance System</span>
          </div>
        </div>
        <nav>
          {TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>
                <Icon size={18} />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <div className="site-banner">
          <img src={leftLogo} alt="e-TCP left insignia" />
          <div className="site-banner-copy">
            <strong>E-TCP</strong>
            <span>AI Based Speed Monitoring and TFC Control Post</span>
          </div>
          <img src={rightLogo} alt="e-TCP right insignia" />
        </div>

        <header className="topbar">
          <div>
            <p className="eyebrow">Operations Console</p>
            <h1>{activeLabel}</h1>
          </div>
          <div className="status-pill">{status}</div>
        </header>

        <section className="metric-row">
          <Metric label="Today Total" value={totals.total} />
          <Metric label="Military" value={totals.mil} />
          <Metric label="Civil" value={totals.civil} />
          <Metric label="Receiver Events" value={notifications.length} />
        </section>

        {activeTab === "dashboard" && (
          <DashboardPanel
            dashboard={dashboard}
            comparison={comparison}
            diagnostic={diagnostic}
            cameras={cameras}
            cameraStats={cameraStats}
            refresh={() => loadDashboard(true)}
          />
        )}

        {activeTab === "map" && (
          <MapPanel
            cameraStats={cameraStats}
            onViewStreams={(cameraId) => {
              setActiveTab("streams");
            }}
            onViewLogs={(cameraId) => {
              setActiveTab("logs");
              loadCameraLogs(cameraId);
            }}
            onViewTcp={(tcpName) => {
              setActiveTab("tcp");
              loadTcpReport(tcpName);
            }}
          />
        )}

        {activeTab === "streams" && (
          <StreamsPanel
            cameras={cameras}
            cameraStats={cameraStats}
            running={running}
            previewTick={previewTick}
            registerAllStreams={registerAllStreams}
            saveLogs={saveLogs}
            updateCameraUrl={updateCameraUrl}
            startCamera={startCamera}
            stopCamera={stopCamera}
            openLogs={(cameraId) => {
              setActiveTab("logs");
              loadCameraLogs(cameraId);
            }}
          />
        )}

        {activeTab === "upload" && (
          <UploadPanel uploadRef={uploadRef} uploadRunning={uploadRunning} uploadVideo={uploadVideo} uploadLogs={uploadLogs} />
        )}

        {activeTab === "logs" && (
          <LogsPanel
            cameras={cameras}
            selectedCamera={selectedCamera}
            loadCameraLogs={loadCameraLogs}
            rows={cameraLogs}
            deleteLog={deleteLog}
            running={running}
            previewTick={previewTick}
            startCamera={startCamera}
            stopCamera={stopCamera}
          />
        )}

        {activeTab === "reports" && (
          <ReportsPanel
            cameras={cameras}
            filters={reportFilters}
            setFilters={setReportFilters}
            rows={reportRows}
            loadReport={loadReport}
            downloadReport={downloadReport}
          />
        )}

        {activeTab === "tcp" && (
          <TcpPanel
            tcpName={tcpName}
            tcpOptions={tcpOptions}
            tcpReport={tcpReport}
            remaining={remaining}
            loadTcpReport={loadTcpReport}
          />
        )}

        {activeTab === "vehicles" && (
          <VehicleMasterPanel rows={vehicleMaster} saveVehicleMaster={saveVehicleMaster} refresh={loadVehicleMaster} importExcel={importVehicleExcel} />
        )}

        {activeTab === "alerts" && (
          <AlertsPanel
            blacklist={blacklist}
            alerts={alerts}
            searchResults={searchResults}
            plateSearch={plateSearch}
            setPlateSearch={setPlateSearch}
            addBlacklist={addBlacklist}
            deleteBlacklist={deleteBlacklist}
            searchPlate={searchPlate}
          />
        )}

        {activeTab === "receiver" && (
          <section className="panel">
            <div className="panel-toolbar">
              <button onClick={refreshNotifications}><RefreshCw size={17} /> Refresh Events</button>
            </div>
            <ReceiverTable events={notifications} />
          </section>
        )}

      </section>
    </main>
  );
}
const rootElement = document.getElementById("root");
const root = window.__SURVEILLANCE_ROOT__ || createRoot(rootElement);
window.__SURVEILLANCE_ROOT__ = root;
root.render(<App />);
