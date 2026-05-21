from flask import Flask, request
import json
import os
from datetime import datetime

app = Flask(__name__)

SAVE_DIR = "received"
os.makedirs(SAVE_DIR, exist_ok=True)


@app.route('/NotificationInfo/TollgateInfo', methods=['POST'])
def tollgate():

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # CASE 1: JSON DATA
    if request.is_json:

        data = request.get_json()

    else:

        # FORM DATA
        data = request.form.to_dict(flat=False)

    event_data = {
        "received_at": datetime.now().isoformat(),
        "content_type": request.content_type,
        "data": data,
        "files": []
    }

    # FILES
    for key in request.files:

        file = request.files[key]

        filename = timestamp + "_" + file.filename

        filepath = os.path.join(SAVE_DIR, filename)

        file.save(filepath)

        event_data["files"].append({
            "field": key,
            "filename": file.filename,
            "saved_as": filepath
        })

    json_filename = timestamp + "_event.json"
    json_filepath = os.path.join(SAVE_DIR, json_filename)

    with open(json_filepath, "w", encoding="utf-8") as json_file:
        json.dump(event_data, json_file, indent=4, ensure_ascii=False)

    return "OK", 200


@app.route('/NotificationInfo/KeepAlive', methods=['POST'])
def keepalive():

    return "OK", 200



if __name__ == '__main__':
    app.run(host='192.168.1.50', port=7072, debug=True)
