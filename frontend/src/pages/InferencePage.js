import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate, useLocation } from "react-router-dom";

const Inference = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const queryParams = new URLSearchParams(location.search);
  const selectedModelFromURL = queryParams.get("model"); 

  const [inputs, setInputs] = useState("");
  const [results, setResults] = useState(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");

  // Fetch available models from the backend
  useEffect(() => {
    axios.get("http://127.0.0.1:8080/deployedModels")
      .then(response => {
        setModels(response.data || []); 
        if (selectedModelFromURL) {
          setSelectedModel(selectedModelFromURL);
        }
      })
      .catch(error => console.error("Error fetching models:", error));
  }, [selectedModelFromURL]);

  const handleModelChange = (event) => {
    setSelectedModel(event.target.value);
  };

  const handleInputChange = (event) => {
    setInputs(event.target.value);
  };

  const handleRunInference = async () => {
    if (!selectedModel) {
      setStatusMessage("Please select a model.");
      return;
    }
    if (!inputs) {
      setStatusMessage("Please provide input data for inference.");
      return;
    }

    setStatusMessage("Running inference...")

    try {
      const inputData = JSON.parse(inputs);
      console.log(inputData)
      const response = await axios.post(`http://127.0.0.1:8080/inference/infer/${selectedModel}`, {
      input: inputData,
      headers: { "Content-Type": "application/json" }
     });

      setResults(response.data.results);
      setStatusMessage("Inference completed successfully!");
    } catch (error) {
      setStatusMessage("Error during inference: " + (error.response?.data?.detail || error.message));
    }
  };

  const goBack = () => navigate(-1);
  const navToHomePage = () => navigate('/home');

  return (
    <div style={styles.outerContainer}>
      <div style={styles.backButtonContainer}>
        <link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons"></link>
        <i className="material-icons" style={styles.homeIcon} onClick={navToHomePage}>home</i>
        <button onClick={goBack} style={styles.backButton}>← Back</button>
      </div>
      <div style={styles.container}>
        {/* Input Section */}
        <div style={styles.inputSection}>
          <h1 style={styles.title}>Run Inference</h1>
          <p style={styles.description}>Select a deployed model and provide input data.</p>

          {/* Select Model */}
          <div style={styles.section}>
            <p style={styles.description}>Select a deployed model:</p>
            <select value={selectedModel} onChange={handleModelChange} style={styles.dropdown}>
              <option value="">-- Select a Model --</option>
              {models.map((model, index) => (
                <option key={index} value={model.name}>{model.name}</option>
              ))}
            </select>
          </div>

          {/* Input Data */}
          <div style={styles.section}>
            <label style={styles.label}>Input Data (JSON format):</label>
            <textarea
              value={inputs}
              onChange={handleInputChange}
              style={styles.textarea}
              placeholder='e.g., [[1.0, 2.0, 3.0]]'
            />
          </div>

          {/* Run Inference */}
          <button onClick={handleRunInference} style={styles.button}>Run Inference</button>

          {/* Status Message */}
          {statusMessage && <p style={styles.statusMessage}>{statusMessage}</p>}
        </div>

        {/* Results Section */}
        <div style={styles.resultsSection}>
          <h2 style={styles.resultsTitle}>Results</h2>
          <div style={styles.resultsBox}>
            {results ? (
              <pre style={styles.resultsContent}>{JSON.stringify(results, null, 2)}</pre>
            ) : (
              <p style={styles.placeholderText}>Results will appear here.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Inference;

const styles = {
  outerContainer: {
    display: "flex",
    height: "100vh",
    flexDirection: "column",
    justifyContent: "space-between",
    backgroundColor: "#1f1f2e",
    color: "#fff",
  },
  container: {
    display: "flex",
    height: "95vh",
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: "#1f1f2e",
    fontFamily: "'Roboto', sans-serif",
    color: "#fff",
  },
  inputSection: {
    flex: 1,
    padding: "30px",
    backgroundColor: "#2a2a3c",
    borderRadius: "12px",
    margin: "20px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.3)",
    overflow: "auto"
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
  section: {
    marginBottom: "20px",
  },
  label: {
    fontSize: "14px",
    color: "#c2c2c2",
    marginBottom: "10px",
    display: "block",
  },
  textarea: {
    width: "97%",
    padding: "10px",
    fontSize: "14px",
    color: "#fff",
    backgroundColor: "#1f1f2e",
    border: "1px solid #6a11cb",
    borderRadius: "8px",
    outline: "none",
    height: "340px",
  },
  button: {
    backgroundColor: "#2575fc",
    color: "#fff",
    border: "none",
    padding: "10px 20px",
    fontSize: "16px",
    fontWeight: "bold",
    borderRadius: "8px",
    cursor: "pointer",
    transition: "background-color 0.3s ease",
    width: "100%",
    marginTop: "10px",
  },
  statusMessage: {
    marginTop: "20px",
    fontSize: "14px",
    color: "#6a11cb",
  },
  resultsSection: {
    flex: 1,
    padding: "30px",
    margin: "20px",
    backgroundColor: "#2a2a3c",
    borderRadius: "12px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.3)",
    overflow: "hidden",
  },
  resultsTitle: {
    fontSize: "20px",
    fontWeight: "bold",
    marginBottom: "15px",
    color: "#f9a825",
  },
  resultsBox: {
    backgroundColor: "#1f1f2e",
    padding: "10px",
    borderRadius: "8px",
    border: "1px solid #6a11cb",
    maxHeight: "70vh",
    overflow: "auto",
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
    textAlign: "center"
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
    shadow: "none",
  },
  homeIcon: {
    position: "absolute",
    cursor: "pointer",
    top: "25px",
    right: "25px",
    fontSize: "200%"

  },
  backButtonContainer: {
    position: "relative",
  },
};

