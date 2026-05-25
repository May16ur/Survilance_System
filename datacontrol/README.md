# Data Control

Manual database sync tools.

## Sync Vehicle Details

Run from the project root:

```powershell
python datacontrol\sync_vehicle_details.py
```

Or run with a custom Excel path:

```powershell
python datacontrol\sync_vehicle_details.py --path "C:\Users\aipc1\Desktop\Survilance_System\VEH DETAILS.xlsx"
```

The script reads `VEH DETAILS.xlsx` and upserts rows into:

```text
vehicle_logsnew.vehicle_master
```

It uses `.env` for MySQL settings and `VEH_DETAILS_PATH`.
