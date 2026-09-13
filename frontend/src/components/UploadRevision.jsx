import React, { useState } from "react";
import axios from "axios";

export default function UploadRevision({ manualId }) {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  const handleUpload = async () => {
    if (!file) return alert("Select a file first!");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(
        `http://127.0.0.1:8000/api/upload/${manualId}/`,
        formData
      );
      setResult(response.data);
    } catch (err) {
      console.error(err);
      alert("Upload failed");
    }
  };

  return (
    <div className="card card-pad">
      <h3 className="section-title" style={{ marginBottom: "1rem" }}>Upload Revision</h3>

      <div className="row" style={{ gap: "0.75rem" }}>
        <input className="input-file" type="file" onChange={handleFileChange} />
        <button className="btn btn-primary" onClick={handleUpload}>Upload</button>
      </div>

      {result && (
        <div className="col anim-fade-up" style={{ marginTop: "1.25rem" }}>
          <div className="row text-sm">
            <span className="subtle strong">Predicted section</span>
            <span className="badge">{result.predicted_section}</span>
          </div>
          <div>
            <p className="label" style={{ marginBottom: "0.4rem" }}>Diff preview</p>
            <div className="content-box content-box-scroll mono">{result.diff_preview}</div>
          </div>
        </div>
      )}
    </div>
  );
}
