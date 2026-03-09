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
    <div style={{ padding: 20 }}>
      <h2>Upload Revision</h2>
      <input type="file" onChange={handleFileChange} />
      <button onClick={handleUpload} style={{ marginLeft: 10 }}>Upload</button>

      {result && (
        <div style={{ marginTop: 20 }}>
          <p><strong>Predicted Section:</strong> {result.predicted_section}</p>
          <p><strong>Diff Preview:</strong></p>
          <pre>{result.diff_preview}</pre>
        </div>
      )}
    </div>
  );
}
