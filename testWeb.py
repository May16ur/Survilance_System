from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def root():
    print("ROOT HIT", request.method, request.data[:500])
    return "OK"

@app.route("/NotificationInfo/KeepAlive", methods=["GET", "POST"])
def keep_alive():
    print("KEEP ALIVE HIT")
    print(request.data.decode(errors="ignore"))
    return "OK"

@app.route("/NotificationInfo/<path:any_path>", methods=["GET", "POST"])
def notification(any_path):
    print("\nANPR/API HIT")
    print("PATH:", any_path)
    print("METHOD:", request.method)
    print("HEADERS:", dict(request.headers))
    print("BODY:", request.data.decode(errors="ignore")[:3000])
    return "OK"

app.run(host="192.168.2.50", port=8080, debug=True)