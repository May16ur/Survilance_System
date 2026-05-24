import json
import os


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.getenv("PROJECT_CONFIG_PATH", os.path.join(BASE_DIR, "project_config.json"))

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 7073, "public_url": "http://127.0.0.1:7073"},
    "cameras": [],
    "tcp_pairs": [],
}


def load_project_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        if not isinstance(data, dict):
            return DEFAULT_CONFIG.copy()
        config = DEFAULT_CONFIG.copy()
        config.update(data)
        return config
    except Exception as exc:
        print(f"[CONFIG] Could not load {CONFIG_PATH}: {exc}")
        return DEFAULT_CONFIG.copy()


PROJECT_CONFIG = load_project_config()


def get_server_config():
    return PROJECT_CONFIG.get("server") or {}


def get_camera_configs():
    rows = PROJECT_CONFIG.get("cameras") or []
    return [row for row in rows if isinstance(row, dict) and row.get("id")]


def get_tcp_pair_configs():
    rows = PROJECT_CONFIG.get("tcp_pairs") or []
    return [row for row in rows if isinstance(row, dict) and row.get("key")]


def get_camera_name_map():
    return {
        int(row["id"]): str(row.get("name") or f"Camera {row['id']}")
        for row in get_camera_configs()
    }


def get_tcp_pair_map():
    camera_names = get_camera_name_map()
    pairs = {}
    for row in get_tcp_pair_configs():
        in_name = camera_names.get(int(row.get("in_camera_id") or 0))
        out_name = camera_names.get(int(row.get("out_camera_id") or 0))
        if in_name and out_name:
            pairs[str(row["key"]).lower()] = (in_name, out_name)
    return pairs


def get_cp_plus_camera_map():
    mapping = {}
    for row in get_camera_configs():
        camera_id = int(row["id"])
        for key in row.get("cp_plus_keys") or []:
            key = str(key).strip()
            if key:
                mapping[key] = camera_id
    return mapping


def get_frontend_config():
    return {
        "server": get_server_config(),
        "cameras": get_camera_configs(),
        "tcp_pairs": get_tcp_pair_configs(),
    }
