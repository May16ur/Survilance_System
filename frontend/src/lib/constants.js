import {
  Activity,
  BarChart3,
  Bell,
  Camera,
  Database,
  FileVideo,
  Map,
  ShieldAlert,
  Table2,
  Users,
} from "lucide-react";

export const DEFAULT_CAMERAS = [
  { id: 3, name: "Kiari to Leh", url: "rtsp://admin:Welcome%2A123@192.168.2.110:554/video/live?channel=1&subtype=0" },
  { id: 4, name: "Kiari-CThang", url: "rtsp://admin:Welcome%2A123@192.168.2.116:554/video/live?channel=1&subtype=0" },
];

export const TCP_OPTIONS = ["igoo", "kiari", "cthang", "nyoma", "loma", "hanle", "chushul"];

export const TABS = [
  { id: "dashboard", label: "Dashboard", icon: BarChart3 },
  { id: "map", label: "Map View", icon: Map },
  { id: "streams", label: "Live Cameras", icon: Camera },
  { id: "upload", label: "Video Upload", icon: FileVideo },
  { id: "logs", label: "Logs", icon: Database },
  { id: "reports", label: "Reports", icon: Table2 },
  { id: "tcp", label: "TCP Tables", icon: Activity },
  { id: "vehicles", label: "Vehicle Master", icon: Users },
  { id: "alerts", label: "Alerts", icon: ShieldAlert },
  { id: "receiver", label: "Receiver", icon: Bell },
];
