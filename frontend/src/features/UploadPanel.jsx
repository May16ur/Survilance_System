import { FileVideo, Upload } from "lucide-react";
import { LogTable } from "../components/Tables.jsx";

export function UploadPanel({ uploadRef, uploadRunning, uploadVideo, uploadLogs }) {
  return (
    <section className="panel two-column">
      <div>
        <div className="panel-toolbar">
          <input ref={uploadRef} type="file" accept="video/*" />
          <button onClick={uploadVideo}><Upload size={17} /> Start Process</button>
        </div>
        <div className="video-frame">
          {uploadRunning ? <img src="/video_feed" alt="Processed uploaded video" /> : <div className="empty-preview"><FileVideo size={34} /> Waiting for upload</div>}
        </div>
      </div>
      <LogTable rows={uploadLogs} />
    </section>
  );
}
