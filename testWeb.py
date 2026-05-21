from flask import Flask, Response, render_template_string
import cv2
import os
import time

# Better RTSP stability
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

app = Flask(__name__)

# ===== RTSP CAMERA URL =====
RTSP_URL = "rtsp://admin:Welcome%2A123@192.168.1.110:554/video/live?channel=1&subtype=0"

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>RTSP Camera Feed</title>

    <style>
        body{
            background:#111;
            color:white;
            text-align:center;
            font-family:Arial;
        }

        img{
            width:80%;
            border:5px solid white;
            border-radius:10px;
            margin-top:20px;
        }

        h1{
            margin-top:20px;
        }
    </style>
</head>

<body>

    <h1>Live RTSP Camera Feed</h1>

    <img src="/video_feed">

</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

def generate_frames():

    camera = None

    try:
        while True:

            if camera is None or not camera.isOpened():
                print("Connecting to camera...")
                camera = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
                time.sleep(2)

                if not camera.isOpened():
                    print("ERROR: Cannot connect to RTSP stream, retrying...")
                    camera.release()
                    time.sleep(3)
                    continue

            success, frame = camera.read()

            if not success:
                print("Failed to read frame, reconnecting...")
                camera.release()
                camera = None
                time.sleep(2)
                continue

            # Encode frame
            ret, buffer = cv2.imencode('.jpg', frame)

            if not ret:
                print("Failed to encode frame")
                continue

            frame = buffer.tobytes()

            # Stream frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' +
                   frame +
                   b'\r\n')
    finally:
        if camera is not None:
            camera.release()

@app.route('/video_feed')
def video_feed():

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

if __name__ == '__main__':

    app.run(
        host='192.168.1.50',
        port=5006,
        debug=False,
        threaded=True
    )
