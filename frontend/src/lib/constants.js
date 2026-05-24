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
  { id: 1, name: "IGOO TCP to Leh", url: "" },
  { id: 2, name: "IGOO TCP to Kiari", url: "" },
  { id: 3, name: "Kiari to Leh", url: "" },
  { id: 4, name: "Kiari-CThang", url: "" },
  { id: 5, name: "C/Thang to Kiari", url: "" },
  { id: 6, name: "C/Thang to Nyoma", url: "" },
  { id: 7, name: "Nyoma to C/Thang", url: "" },
  { id: 8, name: "Nyoma to Loma", url: "" },
  { id: 9, name: "Loma to Nyoma", url: "" },
  { id: 10, name: "Loma to Hanle", url: "" },
  { id: 11, name: "Hanle to Loma", url: "" },
  { id: 12, name: "Hanle to Tasigang", url: "" },
  { id: 13, name: "Chushul to Tara", url: "" },
  { id: 14, name: "Chushul to Parma", url: "" },
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
