import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate, useLocation } from "react-router-dom";

const API_BASE = "http://127.0.0.1:8080"; // REST base (Envoy)
const GRPC_ADDR = "127.0.0.1:8080";       // gRPC address (Envoy)
const GRPC_SERVICE = "nexon.grpc.inference.v1.InferenceService/Predict"; // FQMN

const Deploy = () => {
  const [selectedModel, setSelectedModel] = useState("");
  const [file, setFile] = useState(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [inferenceEndpoint, setInferenceEndpoint] = useState("");
  const [models, setModels] = useState([]);

  const navigate = useNavigate();
  const location = useLocation();
  const queryParams = new URLSearchParams(location.search);
  const selectedModelFromURL = queryParams.get("model");

  // Fetch available models
  useEffect(() => {
    axios
      .get(`${API_BASE}/uploadedModels`)
      .then((res) => {
        setModels(res.data || []);
        if (selectedModelFromURL) setSelectedModel(selectedModelFromURL);
      })
      .catch((err) => {
        console.error("Error fetching models:", err);
      });
  }, [selectedModelFromURL]);

  const handleModelChange = (e) => {
    setSelectedModel(e.target.value);
    setFile(null);
  };

  const handleFileChange = (e) => {
    setFile(e.target.files[0] || null);
    setSelectedModel("");
  };

  const goBack = () => navigate(-1);
  const navToHomePage = () => navigate("/home");

  const handleDeploy = async () => {
    if (!selectedModel && !file) {
      setStatusMessage("Please select a model or upload a file before deploying.");
      return;
    }
    setStatusMessage("Deploying model…");

    try {
      let response;

      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        // Original API supported deploy-file; keep it for parity
        response = await axios.post(`${API_BASE}/deployment/deploy-file/`, formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        const modelDoc = models.find((m) => m.name === selectedModel);
        response = await axios.post(`${API_BASE}/deployment/deploy-model/`, {
          model_name: selectedModel,
          model_id: modelDoc?._id,
        });
      }

      const data = response.data || {};
      // robust REST URL extraction (new and old shapes)
      const restURL =
        data.rest_envoy ||
        data.inference_endpoint ||
        (data.endpoints && data.endpoints.rest) ||
        "";

      setStatusMessage(data.message || "Deployed successfully.");
      setInferenceEndpoint(restURL);
    } catch (error) {
      setStatusMessage(
        "Deployment failed: " + (error.response?.data?.detail || error.message)
      );
      setInferenceEndpoint("");
    }
  };

  const chosenName = selectedModel || (file ? file.name : "");

  return (
    <div style={styles.container}>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/icon?family=Material+Icons"
      />
      <i className="material-icons" style={styles.homeIcon} onClick={navToHomePage}>
        home
      </i>

      <button onClick={goBack} style={styles.backButton}>
        ← Back
      </button>

      <div style={styles.card}>
        <h1 style={styles.title}>Deploy Your Model</h1>
        <p style={styles.subtitle}>Select an existing model to deploy.</p>

        <select
          value={selectedModel}
          onChange={handleModelChange}
          style={styles.dropdown}
        >
          <option value="">-- Select a Model --</option>
          {models.map((m) => (
            <option key={m._id} value={m.name}>
              {m.name}-v{m.version}
            </option>
          ))}
        </select>

        <p style={styles.orText}>OR</p>

        <div style={styles.fileUpload}>
          <label style={styles.fileLabel} htmlFor="fileInput">
            Choose a new File
          </label>
          <input
            type="file"
            id="fileInput"
            onChange={handleFileChange}
            style={styles.fileInput}
            accept=".onnx"
          />
        </div>

        <button onClick={handleDeploy} style={styles.deployButton}>
          DEPLOY
        </button>

        {statusMessage && <p style={styles.status}>{statusMessage}</p>}

        {inferenceEndpoint && (
          <>
            <h3 style={styles.endpointsTitle}>
              The model is available on the following Endpoints:
            </h3>

            <div style={styles.cards}>
              <div style={styles.cardBox}>
                <div style={styles.cardHeaderUnderlined}>REST</div>
                <pre style={styles.mono}>{inferenceEndpoint}</pre>
              </div>

              <div style={styles.cardBox}>
                <div style={styles.cardHeaderUnderlined}>gRPC</div>
                <div style={styles.grpcBlock}>
                  <div style={styles.grpcLabel}>Address:</div>
                  <pre style={styles.mono}>{GRPC_ADDR}</pre>
                  <div style={{ height: 8 }} />
                  <div style={styles.grpcLabel}>Service:</div>
                  <pre style={styles.mono}>{GRPC_SERVICE}</pre>
                </div>
              </div>
            </div>

            <div style={styles.orRow}>OR</div>

            <div style={styles.ctaBar}>
              <span style={styles.ctaLabel}>Try our Inference Page:</span>
              <button
                onClick={() =>
                  navigate(`/inference?model=${encodeURIComponent(chosenName)}`)
                }
                style={styles.inferenceButton}
              >
                GO TO INFERENCE PAGE
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default Deploy;

// ---------------- styles ----------------

const styles = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "100vh",
    backgroundColor: "#1f1f2e",
    fontFamily: "'Roboto', sans-serif",
    color: "#fff",
  },
  card: {
    backgroundColor: "#2a2a3c",
    padding: 30,
    borderRadius: 12,
    boxShadow: "0 4px 8px rgba(0,0,0,.3)",
    width: 900,
    maxWidth: "92vw",
    textAlign: "center",
  },
  title: { fontSize: 28, margin: 0, color: "#f9a825" },
  subtitle: { marginTop: 10, marginBottom: 16, color: "#c2c2c2" },

  dropdown: {
    width: "100%",
    padding: 12,
    fontSize: 14,
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: 8,
    outline: "none",
    cursor: "pointer",
  },
  orText: { fontWeight: "bold", color: "#c2c2c2", margin: "16px 0" },

  fileUpload: { marginBottom: 12 },
  fileLabel: { display: "block", marginBottom: 8, color: "#c2c2c2" },
  fileInput: {
    width: "100%",
    padding: 10,
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: 8,
    outline: "none",
  },

  deployButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    border: "none",
    padding: "10px 22px",
    fontSize: 16,
    fontWeight: "bold",
    borderRadius: 8,
    cursor: "pointer",
  },

  status: { marginTop: 16, color: "#6a11cb" },

  endpointsTitle: {
    marginTop: 18,
    marginBottom: 8,
    fontSize: 18,
    fontWeight: 700,
    color: "#ddd",
  },

  cards: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
    marginTop: 8,
    marginBottom: 12,
  },

  cardBox: {
    backgroundColor: "#1f1f2e",
    padding: 14,
    borderRadius: 8,
    textAlign: "left",
    minHeight: 120,
  },

  cardHeaderUnderlined: {
    fontWeight: 800,
    marginBottom: 8,
    letterSpacing: 0.5,
    textDecoration: "underline", // underline for visibility
  },

  // readable monospace wrapping (no mid-word breaks)
  mono: {
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    margin: 0,
  },

  grpcBlock: { lineHeight: 1.35 },
  grpcLabel: { fontStyle: "italic", color: "#bfbfe7" },

  orRow: { textAlign: "center", marginTop: 8, marginBottom: 8, color: "#c2c2c2" },

  ctaBar: {
    backgroundColor: "#1f1f2e",
    borderRadius: 8,
    padding: 14,
    display: "flex",
    alignItems: "center",
    justifyContent: "center", // centered button
    gap: 16,
  },
  ctaLabel: { color: "#c2c2c2" },
  inferenceButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    padding: "10px 16px",
    borderRadius: 8,
    border: "none",
    cursor: "pointer",
    fontSize: 16,
    fontWeight: 700,
  },

  backButton: {
    position: "fixed",
    top: 16,
    left: 16,
    background: "transparent",
    color: "#fff",
    border: "none",
    fontSize: 16,
    cursor: "pointer",
  },
  homeIcon: {
    position: "fixed",
    top: 16,
    right: 16,
    cursor: "pointer",
    fontSize: "24px",
  },
};