import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.VITE_BACKEND_URL || "http://192.168.2.146:7073";

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
