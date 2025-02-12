import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

const Deploy = () => {
  const [selectedModel, setSelectedModel] = useState("");
  const [file, setFile] = useState(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [inferenceEndpoint, setInferenceEndpoint] = useState("");
  const [models, setModels] = useState([]);
  const navigate = useNavigate();

  // Fetch available models from the backend
  useEffect(() => {
    axios.get("http://127.0.0.1:8000/uploadedModels")
      .then(response => {
        setModels(response.data || []); // Ensure we get an array
      })
      .catch(error => {
        console.error("Error fetching models:", error);
      });
  }, []);

  const handleModelChange = (event) => {
    setSelectedModel(event.target.value);
    setFile(null);
  };

  const handleFileChange = (event) => {
    setFile(event.target.files[0]);
    setSelectedModel("");
  };

  const goBack = () => {
    navigate(-1); // Go to the previous page
  };
  const navToHomePage = () => {
    navigate('/home');
  };

  const handleDeploy = async () => {
    if (!selectedModel && !file) {
      setStatusMessage("Please select a model or upload a file before deploying.");
      return;
    }

    setStatusMessage("Deploying model...");

    try {
      let response;

      if (file) {
        const formData = new FormData();
        formData.append("file", file);

        response = await axios.post("http://127.0.0.1:8000/deployment/deploy-file/", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        response = await axios.post("http://127.0.0.1:8000/deployment/deploy-model/", {
          model_name: selectedModel,
        });
      }

      setStatusMessage(response.data.message);
      setInferenceEndpoint(response.data.inference_endpoint);
    } catch (error) {
      setStatusMessage(
        "Deployment failed: " + (error.response?.data?.detail || error.message)
      );
    }
  };

  return (
    <div style={styles.container}>
       <link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons"></link>
      <i class="material-icons" style={styles.homeIcon} onClick={navToHomePage}>home</i>
      {/* Back Button */}
      <button onClick={goBack} style={styles.backButton}>← Back</button>
      <div style={styles.deployCard}>
        <h1 style={styles.title}>Deploy Your Model</h1>
        <p style={styles.description}>Select an existing model to deploy.</p>

        <select value={selectedModel} onChange={handleModelChange} style={styles.dropdown}>
          <option value="">-- Select a Model --</option>
          {models.map((model, index) => (
            <option key={index} value={model}>{model}</option>
          ))}
        </select>

        <p style={styles.orText}>OR</p>

        <div style={styles.fileUpload}>
          <label style={styles.fileLabel} htmlFor="fileInput">
            Choose a new File
          </label>
          <input type="file" id="fileInput" onChange={handleFileChange} style={styles.fileInput} />
        </div>

        <button onClick={handleDeploy} style={styles.deployButton}>
          Deploy
        </button>

        {statusMessage && <p style={styles.statusMessage}>{statusMessage}</p>}

        {inferenceEndpoint && (
          <div style={styles.apiContainer}>
            <div style={styles.apiBox}>
              <p>The model is available on the following Endpoint:</p>
              <p>{inferenceEndpoint}</p>
            </div>
            <p style={styles.orText}>OR</p>
            <div style={styles.apiBox}>
              <p>Try our Inference Page:</p>
              <button onClick={() => navigate("/inference")} style={styles.inferenceButton}>
                Go to Inference Page
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Deploy;

const styles = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    backgroundColor: "#1f1f2e",
    fontFamily: "'Roboto', sans-serif",
    color: "#fff",
  },
  deployCard: {
    backgroundColor: "#2a2a3c",
    padding: "30px",
    borderRadius: "12px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.3)",
    textAlign: "center",
    width: "800px",
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
  dropdown: {
    width: "100%",
    padding: "10px",
    fontSize: "14px",
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: "8px",
    marginBottom: "20px",
    outline: "none",
    cursor: "pointer",
  },
  orText: {
    fontSize: "16px",
    fontWeight: "bold",
    margin: "20px 0",
    color: "#c2c2c2",
  },
  fileUpload: {
    marginBottom: "20px",
  },
  fileLabel: {
    display: "block",
    marginBottom: "10px",
    fontSize: "14px",
    color: "#c2c2c2",
  },
  fileInput: {
    width: "100%",
    padding: "10px",
    fontSize: "14px",
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: "8px",
    outline: "none",
    cursor: "pointer",
  },
  deployButton: {
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
  statusMessage: {
    marginTop: "20px",
    fontSize: "14px",
    color: "#6a11cb",
  },

  apiContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: "20px",
    gap: "10px",
  },
  apiBox: {
    backgroundColor: "#1f1f2e",
    padding: "10px",
    borderRadius: "5px",
    color: "#fff",
    wordBreak: "break-all",
    flex: "1",
    height: "100px"
  },
  inferenceButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    padding: "10px 15px",
    borderRadius: "8px",
    border: "none",
    cursor: "pointer",
    fontSize: "16px",
    flexShrink: "0",
  },
  backButton: {
    position: "absolute",
    top: "20px",
    left: "20px",
    background: "transparent",
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
