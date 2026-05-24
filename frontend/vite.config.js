import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readBackendUrl() {
  try {
    const configPath = path.resolve(__dirname, "..", "project_config.json");
    const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    return config.server?.public_url || process.env.VITE_BACKEND_URL || "http://127.0.0.1:7073";
  } catch {
    return process.env.VITE_BACKEND_URL || "http://127.0.0.1:7073";
  }
}

const backend = readBackendUrl();

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/dashboard_full": backend,
      "/upload_video": backend,
      "/video_feed": backend,
      "/start_streams": backend,
      "/start_camera": backend,
      "/preview": backend,
      "/camera_snapshot": backend,
      "/camera_feed": backend,
      "/save_logs": backend,
      "/download_last_7_days_report": backend,
      "/NotificationInfo": backend,
      "/static": backend
    }
  }
});
