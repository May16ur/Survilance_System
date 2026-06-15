import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity } from "lucide-react";
import { getJson } from "./lib/api.js";
import { DEFAULT_CAMERAS, TCP_OPTIONS, TABS } from "./lib/constants.js";
import { Metric } from "./components/Metric.jsx";
import { createDateRange, DateRangeSelector } from "./components/DateRangeSelector.jsx";
import { DashboardPanel } from "./features/DashboardPanel.jsx";
import { StreamsPanel } from "./features/StreamsPanel.jsx";
import { UploadPanel } from "./features/UploadPanel.jsx";
import { LogsPanel } from "./features/LogsPanel.jsx";
import { ReportsPanel } from "./features/ReportsPanel.jsx";
import { TcpPanel } from "./features/TcpPanel.jsx";
import { VehicleMasterPanel } from "./features/VehicleMasterPanel.jsx";
import { AlertsPanel } from "./features/AlertsPanel.jsx";
import { MapPanel } from "./features/MapPanel.jsx";
import leftLogo from "./assets/etcp-left-logo.png";
import rightLogo from "./assets/etcp-right-logo.png";
import "./styles.css";

// App keeps page state and API actions; tab screens live in src/features.
function App() {
  const initialDateRange = useMemo(() => createDateRange(7), []);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [status, setStatus] = useState("Connecting to backend...");
  const [cameras, setCameras] = useState(DEFAULT_CAMERAS);
  const [tcpOptions, setTcpOptions] = useState(TCP_OPTIONS.map((key) => ({ key, label: key.toUpperCase() })));
  const [backendUrl, setBackendUrl] = useState("http://192.168.2.146:7073");
  const [cameraStats, setCameraStats] = useState({});
  const [running, setRunning] = useState({});
  const [uploadLogs, setUploadLogs] = useState([]);
  const [cameraLogs, setCameraLogs] = useState([]);
  const [cameraLogDashboard, setCameraLogDashboard] = useState(null);
  const [selectedCamera, setSelectedCamera] = useState(1);
  const [blacklist, setBlacklist] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [plateSearch, setPlateSearch] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [uploadRunning, setUploadRunning] = useState(false);
  const [dashboard, setDashboard] = useState(null);
  const [dashboardTrend, setDashboardTrend] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [diagnostic, setDiagnostic] = useState(null);
  const [sundayMilitary, setSundayMilitary] = useState(null);
  const [reportRows, setReportRows] = useState([]);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState("");
  const [dateRange, setDateRange] = useState(initialDateRange);
  const [reportFilters, setReportFilters] = useState({ vehicle_type: "all", camera_id: "", ...initialDateRange });
  const [tcpName, setTcpName] = useState("kiari");
  const [tcpReport, setTcpReport] = useState(null);
  const [tcpDashboard, setTcpDashboard] = useState(null);
  const [remaining, setRemaining] = useState(null);
  const [vehicleMaster, setVehicleMaster] = useState([]);
  const uploadRef = useRef(null);
  const dashboardRefreshRunning = useRef(false);

  useEffect(() => {
    loadAppConfig();
    refreshHealth();
    refreshCounters();
    loadDashboard();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      if (activeTab === "dashboard") {
        refreshCounters();
        loadDashboard(false);
      }
      if (activeTab === "alerts") refreshBlacklist();
      if (activeTab === "logs") loadCameraLogs(selectedCamera);
      if (activeTab === "upload" && uploadRunning) loadUploadLogs();
    }, 30000);
    return () => clearInterval(timer);
  }, [activeTab, selectedCamera, uploadRunning, cameras, dateRange]);

  useEffect(() => {
    if (activeTab === "reports") loadReport(null, reportFilters);
    if (activeTab === "alerts") refreshBlacklist();
    if (activeTab === "vehicles") loadVehicleMaster();
    if (activeTab === "tcp") loadTcpReport(tcpName);
  }, [activeTab]);

  function dateParams(range = dateRange) {
    return new URLSearchParams(range).toString();
  }

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
      }
      if (config.server?.public_url) {
        setBackendUrl(config.server.public_url);
      }
    } catch {
      loadCameras();
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

  async function refreshCounters(range = dateRange) {
    try {
      const data = await getJson(`/api/camera_range_stats?${dateParams(range)}`);
      setCameraStats(data.stats || {});
    } catch {
      setCameraStats({});
    }
  }

  async function loadDashboard(showStatus = true, range = dateRange) {
    if (dashboardRefreshRunning.current) return;
    dashboardRefreshRunning.current = true;
    try {
      const params = dateParams(range);
      const fixedTrendRange = createDateRange(7);
      const trendParams = dateParams(fixedTrendRange);
      const sameAsFixedTrend = range.start_date === fixedTrendRange.start_date
        && range.end_date === fixedTrendRange.end_date;
      const full = await getJson(`/dashboard_full?${params}`);
      setDashboard(full);
      dashboardRefreshRunning.current = false;
      if (sameAsFixedTrend) {
        setDashboardTrend(full);
      } else {
        getJson(`/dashboard_full?${trendParams}`)
          .then(setDashboardTrend)
          .catch(() => {});
      }
      if (showStatus) setStatus("Dashboard totals loaded.");
      if (!showStatus) return;

      const [cmp, diag, sunday] = await Promise.all([
        getJson(`/api/camera_comparison?${params}`),
        getJson(`/api/count_diagnostic?date=${encodeURIComponent(range.end_date)}`),
        getJson(`/api/sunday_military_report?limit=500&date=${encodeURIComponent(range.end_date)}`),
      ]);
      setComparison(cmp);
      setDiagnostic(diag);
      setSundayMilitary(sunday);
      if (showStatus) setStatus("Dashboard refreshed.");
    } catch (e) {
      if (showStatus) setStatus(`Dashboard refresh failed: ${e.message}`);
    } finally {
      dashboardRefreshRunning.current = false;
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

  async function loadCameraLogs(cameraId = selectedCamera, range = dateRange) {
    setSelectedCamera(cameraId);
    const params = dateParams(range);
    const [data, dashboardData] = await Promise.all([
      getJson(`/api/camera_logs/${cameraId}?limit=300&${params}`),
      getJson(`/api/camera_dashboard/${cameraId}?${params}`),
    ]);
    setCameraLogs(data.logs || []);
    setCameraLogDashboard(dashboardData);
  }

  async function saveLogs() {
    try {
      const data = await getJson("/save_logs", { method: "POST" });
      setStatus(data.message || "Logs saved.");
    } catch (e) {
      setStatus(`Save logs unavailable: ${e.message}`);
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

  async function loadReport(event, filtersOverride = reportFilters) {
    event?.preventDefault();
    setReportLoading(true);
    setReportError("");
    try {
      const params = new URLSearchParams();
      Object.entries(filtersOverride).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      params.set("limit", "2000");
      const data = await getJson(`/api/last_7_days_report?${params}`);
      setReportRows(data.rows || []);
      setStatus(`Loaded ${data.total || 0} report rows.`);
    } catch (error) {
      setReportRows([]);
      setReportError(`Report could not load: ${error.message}. Check that the backend and MySQL are online.`);
      setStatus(`Report load failed: ${error.message}`);
    } finally {
      setReportLoading(false);
    }
  }

  function downloadReport() {
    const params = new URLSearchParams();
    Object.entries(reportFilters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    window.open(`/download_last_7_days_report?${params}`, "_blank");
  }

  async function loadTcpReport(name = tcpName, range = dateRange) {
    setTcpName(name);
    const params = dateParams(range);
    const [data, dashboardData] = await Promise.all([
      getJson(`/api/tcp_table/${name}?limit=1000&${params}`),
      getJson(`/api/tcp_dashboard/${name}?${params}`),
    ]);
    setTcpReport(data);
    setTcpDashboard(dashboardData);
    const rem = await getJson(`/api/remaining_vehicles?group=${name}&${params}`);
    setRemaining(rem);
  }

  function applyDateRange(range) {
    setDateRange(range);
    setReportFilters((current) => ({ ...current, ...range }));
    refreshCounters(range);
    if (activeTab === "dashboard") loadDashboard(true, range);
    if (activeTab === "logs") loadCameraLogs(selectedCamera, range);
    if (activeTab === "tcp") loadTcpReport(tcpName, range);
    if (activeTab === "reports") loadReport(null, { ...reportFilters, ...range });
  }

  async function loadVehicleMaster() {
    const data = await getJson("/api/vehicle_master");
    setVehicleMaster(data.rows || []);
  }

  async function importVehicleExcel() {
    const data = await getJson("/api/vehicle_master/import_excel", { method: "POST" });
    setStatus(data.message || "Vehicle Excel imported.");
    loadVehicleMaster();
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
        total: acc.total + Number(item.today_mil || 0) + Number(item.today_civil || 0),
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

      <section className={`workspace ${activeTab === "dashboard" ? "dashboard-workspace" : ""}`}>
        {activeTab !== "dashboard" && (
          <>
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
              <div className="topbar-actions">
                <DateRangeSelector value={dateRange} onApply={applyDateRange} />
                <div className="status-pill">{status}</div>
              </div>
            </header>
          </>
        )}

        {activeTab !== "dashboard" && activeTab !== "tcp" && (
          <section className="metric-row">
            <Metric label="Range Total" value={totals.total} />
            <Metric label="Military" value={totals.mil} />
            <Metric label="Civil" value={totals.civil} />
          </section>
        )}

        {activeTab === "dashboard" && (
          <DashboardPanel
            dashboard={dashboard}
            dashboardTrend={dashboardTrend}
            comparison={comparison}
            diagnostic={diagnostic}
            sundayMilitary={sundayMilitary}
            cameras={cameras}
            cameraStats={cameraStats}
            dateRange={dateRange}
            applyDateRange={applyDateRange}
            status={status}
            refresh={() => loadDashboard(true)}
            openCameraLogs={(cameraId) => {
              setActiveTab("logs");
              loadCameraLogs(cameraId);
            }}
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
            cameraDashboard={cameraLogDashboard}
            dateRange={dateRange}
            deleteLog={deleteLog}
            running={running}
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
            loading={reportLoading}
            error={reportError}
            loadReport={loadReport}
            downloadReport={downloadReport}
          />
        )}

        {activeTab === "tcp" && (
          <TcpPanel
            tcpName={tcpName}
            tcpOptions={tcpOptions}
            tcpReport={tcpReport}
            tcpDashboard={tcpDashboard}
            remaining={remaining}
            dateRange={dateRange}
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

      </section>
    </main>
  );
}
const rootElement = document.getElementById("root");
const root = window.__SURVEILLANCE_ROOT__ || createRoot(rootElement);
window.__SURVEILLANCE_ROOT__ = root;
root.render(<App />);
