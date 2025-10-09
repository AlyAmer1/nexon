import React, { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API_BASE } from "../config";

const Upload = () => {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [uploadMessage, setUploadMessage] = useState("");

  const handleFileChange = (event) => {
    setFile(event.target.files[0]);
  };

  const navToDeploymentPage = () => {
    navigate(`/deploy?model=${file.name}`);
  };
  const navToHomePage = () => {
    navigate('/home');
  };
  const navToModelOverview = () => {
    navigate('/overview');
  };
  const goBack = () => {
    navigate(-1); // Go to the previous page
  };

  const handleUpload = async () => {
    if (!file) {
      setUploadMessage("Please select a file before uploading.");
      return;
    }

    setUploadMessage("Uploading model...");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await axios.post(`${API_BASE}/upload/`, formData);

      setUploadMessage(response.data.message);
    } catch (error) {
      setUploadMessage("Error uploading model: " + (error.response?.data?.detail || error.message));
    }
  };

  return (
    <div style={styles.container}>
      <link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons"></link>
      <i class="material-icons" style={styles.homeIcon} onClick={navToHomePage}>home</i>
      {/* Back Button */}
      <button onClick={goBack} style={styles.backButton}>← Back</button>
      <div style={styles.uploadCard}>
        <h1 style={styles.title}>Upload Your ONNX Model</h1>
        <p style={styles.description}>
          Select your ONNX model file to upload and deploy it on the platform.
        </p>

        <input type="file" onChange={handleFileChange} style={styles.fileInput} />

        <button onClick={handleUpload} style={styles.uploadButton}>
          Upload
        </button>

        {uploadMessage && <p style={styles.uploadMessage}>{uploadMessage}</p>}

        {file && uploadMessage.includes("successfully") && (
          <div style={styles.buttonContainer}>
            <button style={styles.navButton} onClick={navToDeploymentPage}>
              Deploy the model
            </button>
            <button style={styles.navButton} onClick={navToModelOverview}>
              Go to Model Overview
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Upload;

const styles = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    backgroundColor: "#1f1f2e",
    fontFamily: "'Roboto', sans-serif",
    color: "#fff",
    position: "relative",
  },
  uploadCard: {
    backgroundColor: "#2a2a3c",
    padding: "30px",
    borderRadius: "12px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.3)",
    textAlign: "center",
    width: "400px",
  },
  title: {
    fontSize: "24px",
    fontWeight: "bold",
    marginBottom: "15px",
    color: "#f9a825",
  },
  description: {
    fontSize: "16px",
    marginBottom: "20px",
    color: "#c2c2c2",
  },
  fileInput: {
    marginBottom: "20px",
    padding: "10px",
    fontSize: "14px",
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: "8px",
    outline: "none",
    cursor: "pointer",
  },
  uploadButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    border: "none",
    padding: "10px 20px",
    fontSize: "16px",
    fontWeight: "bold",
    borderRadius: "8px",
    cursor: "pointer",
    transition: "background-color 0.3s ease",
  },
  uploadMessage: {
    marginTop: "20px",
    fontSize: "14px",
    color: "#6a11cb",
  },
  buttonContainer: {
    display: "flex",
    justifyContent: "center",
    gap: "10px",
    marginTop: "15px",
  },
  navButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    padding: "10px 15px",
    borderRadius: "8px",
    border: "none",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "bold",
    transition: "background-color 0.3s ease",
  },
  backButton: {
    position: "absolute",
    top: "20px",
    left: "20px",
    background: "none",
    boxShadow: "none",
    border: "none",
    fontSize: "16px",
    cursor: "pointer",
    shadow: "none"
  },
  homeIcon: {
    position: "absolute",
    cursor: "pointer",
    top: "25px",
    right: "25px",
    fontSize: "200%"

  }
};