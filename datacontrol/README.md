# Data Control

Manual database sync tools.

## Sync Vehicle Details

Run from the project root:

```powershell
python datacontrol\sync_vehicle_details.py
```

Or run with a custom Excel path:

```powershell
python datacontrol\sync_vehicle_details.py --path "C:\Users\aipc1\Desktop\Survilance_System\datacontrol\veh_details.xlsx"
```

The script reads `datacontrol\veh_details.xlsx` by default and upserts rows into:

```text
vehicle_logsnew.vehicle_master
```

It uses `.env` for MySQL settings. `VEH_DETAILS_PATH` is used only when the default same-folder workbook is missing.
