import React, { useEffect, useRef } from "react";

const CAMERA_MARKERS = [
  { id: 1, title: "IGOO TCP to Leh", lat: 33.878587, lng: 77.824860 },
  { id: 2, title: "IGOO TCP to Kiari", lat: 33.8780662, lng: 77.7829386 },
  { id: 3, title: "Kiari to Leh", lat: 33.483244, lng: 78.134193 },
  { id: 4, title: "Kiari-CThang", lat: 33.482215, lng: 78.133034 },
  { id: 5, title: "C/Thang to Kiari", lat: 33.3606122, lng: 78.3197978 },
  { id: 6, title: "C/Thang to Nyoma", lat: 33.3608113, lng: 78.3212177 },
  { id: 7, title: "Nyoma to C/Thang", lat: 33.210140, lng: 78.584674 },
  { id: 8, title: "Nyoma to Loma", lat: 33.209161, lng: 78.584674 },
  { id: 9, title: "Loma to Nyoma", lat: 33.170641, lng: 78.822536 },
  { id: 10, title: "Loma to Hanle", lat: 33.169103, lng: 78.824004 },
  { id: 11, title: "Hanle to Loma", lat: 32.794446, lng: 79.004705 },
  { id: 12, title: "Hanle to Tasigang", lat: 32.793154, lng: 79.006312 },
  { id: 13, title: "Chushul to Tara", lat: 33.593525, lng: 78.640169 },
  { id: 14, title: "Chushul to Parma", lat: 33.594526, lng: 78.6376603 }
];

const TCP_MARKERS = [
  { tcp: "igoo", title: "IGOO TCP", lat: 33.8783871, lng: 77.7826617 },
  { tcp: "kiari", title: "Kiari TCP", lat: 33.482215, lng: 78.133443 },
  { tcp: "cthang", title: "C/Thang TCP", lat: 33.3608113, lng: 78.3212177 },
  { tcp: "nyoma", title: "Nyoma TCP", lat: 33.209705, lng: 78.586486 },
  { tcp: "loma", title: "Loma TCP", lat: 33.169862, lng: 78.823201 },
  { tcp: "hanle", title: "Hanle TCP", lat: 32.793730, lng: 79.005368 },
  { tcp: "chushul", title: "Chushul TCP", lat: 33.593654, lng: 78.638218 },
];

function createCameraPopupHtml(cam, stats) {
  const mil = stats.today_mil || 0;
  const civil = stats.today_civil || 0;
  const total = stats.today_total || (mil + civil);
  return `
    <div class="map-popup-card">
      <div class="map-popup-title">${cam.title}</div>
      <table class="map-popup-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Count</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Military</td><td><strong>${mil}</strong></td></tr>
          <tr><td>Civilian</td><td><strong>${civil}</strong></td></tr>
          <tr class="total-row"><td>Total</td><td><strong>${total}</strong></td></tr>
        </tbody>
      </table>
      <div class="map-popup-actions">
        <button class="map-action-btn" onclick="window.__mapActions.viewStreams(${cam.id})">Live Feed</button>
        <button class="map-action-btn logs" onclick="window.__mapActions.viewLogs(${cam.id})">View Logs</button>
      </div>
    </div>
  `;
}

function createTcpPopupHtml(marker) {
  return `
    <div class="map-popup-card">
      <div class="map-popup-title">${marker.title}</div>
      <p class="map-popup-desc">Click below to view the report and analysis for this TCP.</p>
      <div class="map-popup-actions">
        <button class="map-action-btn tcp" onclick="window.__mapActions.viewTcp('${marker.tcp}')">View TCP Report</button>
      </div>
    </div>
  `;
}

export function MapPanel({ cameraStats, onViewStreams, onViewLogs, onViewTcp }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef({});

  // Connect global popup click functions to React component callbacks
  useEffect(() => {
    window.__mapActions = {
      viewStreams: (id) => {
        if (onViewStreams) onViewStreams(id);
      },
      viewLogs: (id) => {
        if (onViewLogs) onViewLogs(id);
      },
      viewTcp: (tcpName) => {
        if (onViewTcp) onViewTcp(tcpName);
      }
    };
    return () => {
      delete window.__mapActions;
    };
  }, [onViewStreams, onViewLogs, onViewTcp]);

  // Map Initialization
  useEffect(() => {
    if (!window.L || !mapContainerRef.current) return;
    const L = window.L;

    // Initialize Map at central Leh coordinate zoom 9
    const map = L.map(mapContainerRef.current).setView([34.15, 77.58], 9);
    mapRef.current = map;

    // OpenTopoMap tile server
    L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
      maxZoom: 17,
      attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors | Style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>'
    }).addTo(map);

    // Plot TCP Markers (Yellow Triangles)
    const createTriangleMarkerHtml = (tcp, title) => {
      return `<div style="width:0;height:0;border-left:13px solid transparent;border-right:13px solid transparent;border-bottom:23px solid #ffeb00;cursor:pointer;filter:drop-shadow(0 3px 5px rgba(0,0,0,.5));" title="${title}"></div>`;
    };

    TCP_MARKERS.forEach((marker) => {
      L.marker([marker.lat, marker.lng], {
        icon: L.divIcon({
          html: createTriangleMarkerHtml(marker.tcp, marker.title),
          iconSize: [24, 24],
          className: "tcp-marker-icon"
        })
      })
        .addTo(map)
        .bindPopup(createTcpPopupHtml(marker), {
          maxWidth: 240,
          minWidth: 200,
          autoPan: true,
          keepInView: true
        });
    });

    // Plot Camera Markers (Glowing CSS Pulsing Circle Icon)
    const cameraIcon = L.divIcon({
      html: `
        <div class="custom-camera-marker">
          <div class="marker-pulse"></div>
          <div class="marker-dot"></div>
        </div>
      `,
      className: "camera-marker-container",
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });

    CAMERA_MARKERS.forEach((cam) => {
      const stats = cameraStats[cam.id] || { today_total: 0, today_mil: 0, today_civil: 0 };
      const marker = L.marker([cam.lat, cam.lng], { icon: cameraIcon })
        .addTo(map)
        .bindPopup(createCameraPopupHtml(cam, stats), {
          maxWidth: 240,
          minWidth: 200,
          autoPan: true,
          keepInView: true
        });

      markersRef.current[cam.id] = marker;
    });

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      markersRef.current = {};
    };
  }, []);

  // Update popup HTML reactively when cameraStats prop changes
  useEffect(() => {
    const L = window.L;
    if (!L) return;

    CAMERA_MARKERS.forEach((cam) => {
      const marker = markersRef.current[cam.id];
      if (marker) {
        const stats = cameraStats[cam.id] || { today_total: 0, today_mil: 0, today_civil: 0 };
        marker.setPopupContent(createCameraPopupHtml(cam, stats));
      }
    });
  }, [cameraStats]);

  // Center/Zoom/Highlight Camera marker when selected from quick list
  const handleFocusCamera = (cam) => {
    const map = mapRef.current;
    const marker = markersRef.current[cam.id];
    if (map && marker) {
      map.setView([cam.lat, cam.lng], 12);
      marker.openPopup();
    }
  };

  return (
    <section className="map-view-container">
      <div className="map-holder">
        <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }}></div>
      </div>

      <div className="map-sidebar-card">
        <h3 className="map-sidebar-title">Camera Directory</h3>
        <div className="map-sidebar-list">
          {CAMERA_MARKERS.map((cam) => {
            const stats = cameraStats[cam.id] || { today_total: 0 };
            return (
              <button
                key={cam.id}
                className="map-cam-btn"
                onClick={() => handleFocusCamera(cam)}
              >
                <div>
                  <span className="cam-id">{cam.id}.</span>
                  {cam.title}
                </div>
                <span className="cam-total-badge">{stats.today_total}</span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
