import cv2
import os
import time

# Better RTSP stability
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# ===== RTSP URL =====
RTSP_URL = "rtsp://admin:Welcome%2A123@192.168.1.110:554/video/live?channel=1&subtype=0"

print("Connecting to camera...")
cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

# Wait for connection
time.sleep(2)

if not cap.isOpened():
    print("ERROR: Cannot connect to RTSP stream")
    exit()

# Stream information
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS)

print(f"Connected!")
print(f"Resolution: {width}x{height}")
print(f"FPS: {fps}")

while True:
    ret, frame = cap.read()

    if not ret:
        print("Frame not received")
        break

    # Show frame
    cv2.imshow("RTSP Camera Feed", frame)

    # Print frame size
    print(f"Frame received: {frame.shape}")

    # Press ESC to exit
    key = cv2.waitKey(1)

    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()