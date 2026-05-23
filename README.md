# Surveillance System

New split structure:

- `backend/` - Flask API, RTSP/video processing, tollgate notification receiver, database helpers, models.
- `frontend/` - React/Vite operator UI.

## Run Backend

Copy `.env.example` to `.env` and set the port/IP for the client machine.

```powershell
cd backend
python -m pip install -r requirements.txt
python app.py
```

Backend host and port come from `.env`. For the client camera setup, use:

```text
BACKEND_HOST=0.0.0.0
BACKEND_PORT=7073
BACKEND_PUBLIC_URL=http://192.168.2.146:7073
VITE_BACKEND_URL=http://192.168.2.146:7073
```

`0.0.0.0` makes Flask listen on the client machine network card. The camera should still be configured with the machine LAN IP, not `0.0.0.0`.

For the CP Plus camera screen, set Platform Server to:

```text
http://192.168.2.146:7073
```

The backend accepts:

- `POST /NotificationInfo/TollgateInfo`
- `POST /NotificationInfo/KeepAlive`

The camera-facing endpoints return plain `OK` because the camera has `Need Response = Yes`.

If you use the old conda setup, run the backend from that environment:

```powershell
conda activate vehicle
cd C:\Users\VICTUS\Desktop\Survilance_System\backend
python app.py
```

## Run Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend defaults to `http://127.0.0.1:5173`.

## Integrated Receiver Endpoints

- `POST /NotificationInfo/TollgateInfo`
- `POST /NotificationInfo/KeepAlive`
- `GET /api/notifications/recent`

Received tollgate payloads and files are saved under `backend/received/`.

CP Plus ANPR events are now the primary detection source. The backend parses:

- `Picture.Plate.PlateNumber`
- `Picture.Plate.Confidence`
- `Picture.Vehicle.VehicleType`
- `Picture.Vehicle.VehicleColor`
- `Picture.Vehicle.Speed`
- `Picture.SnapInfo.SnapTime`
- `Picture.VehiclePic.Content`

The vehicle image is decoded and saved under `backend/flask_app/static/anpr/`, then the parsed event is inserted into `vehicle_logs` with `source_type='cp_plus_anpr'`.

## Notes

- The model files are now under `backend/`: `veh.pt`, `best.pt`, and `license.pt`.
- In the current global Python install, Torch fails to import because `torch\lib\shm.dll` cannot load. Use the known working `vehicle` conda environment or reinstall a matching Torch build before running the backend.
