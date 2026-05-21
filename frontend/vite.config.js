import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/dashboard_full": "http://127.0.0.1:5000",
      "/upload_video": "http://127.0.0.1:5000",
      "/video_feed": "http://127.0.0.1:5000",
      "/start_streams": "http://127.0.0.1:5000",
      "/start_camera": "http://127.0.0.1:5000",
      "/camera_snapshot": "http://127.0.0.1:5000",
      "/camera_feed": "http://127.0.0.1:5000",
      "/save_logs": "http://127.0.0.1:5000",
      "/download_last_7_days_report": "http://127.0.0.1:5000",
      "/NotificationInfo": "http://127.0.0.1:5000",
      "/static": "http://127.0.0.1:5000"
    }
  }
});
