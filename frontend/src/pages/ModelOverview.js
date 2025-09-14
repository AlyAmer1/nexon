import React, { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

const ModelOverview = () => {
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null); 
  const navigate = useNavigate();
  const [notification, setNotification] = useState("");

  useEffect(() => {
    axios.get("http://127.0.0.1:8080/allModels")
      .then(response => {
        setModels(response.data);
      })
      .catch(error => console.error("Error fetching models:", error));
  }, []);

  const deleteModel = async (modelName, modelVersion) => {
  try {
    const response = await axios.delete(`http://127.0.0.1:8080/deleteModel/${modelName}/${modelVersion}`
    );
    setNotification(`✅ ${response.data.message}`);

    // Remove the notification after 3 seconds
    setTimeout(() => setNotification(""), 3000);

    // Update state to remove deleted model
    setModels(models.filter((model) => model.name !== modelName || model.version !== modelVersion));

  } catch (error) {
    setNotification("❌ Failed to delete model.");
    setTimeout(() => setNotification(""), 3000);
  }
  }

  const undeployModel = async (modelName, modelVersion) => {
    try {
      // Send a request to the backend to undeploy the model
      const response = await axios.put(`http://127.0.0.1:8080/deployment/undeploy/${modelName}`, {
         model_name: modelName,
         model_version: modelVersion 
    });
  
      // Show success notification
      setNotification(`✅ ${response.data.message}`);
  
      // Remove the notification after 3 seconds
      setTimeout(() => setNotification(""), 3000);
  
      // Update state to remove the model from deployed models
      setModels(models.map(model =>
        model.name === modelName && model.version === modelVersion
          ? { ...model, status: "Pending" } // Change status to "Pending" instead of removing
          : model
      ));
      
    } catch (error) {
      // Show error notification
      setNotification("❌ Failed to undeploy model.");
      setTimeout(() => setNotification(""), 3000);
    }
  };
  

  const goBack = () => navigate(-1);
  const navToHomePage = () => navigate('/home');
  const navToInferencePage = (modelName) => navigate(`/inference?model=${modelName}`);

  return (
    <div style={styles.container}>
      <div style={styles.backButtonContainer}>
        <link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons"></link>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css"></link>
        <i className="material-icons" style={styles.homeIcon} onClick={navToHomePage}>home</i>
        <button onClick={goBack} style={styles.backButton}>← Back</button>
      </div>
      <h1 style={styles.title}>Model Overview</h1>

      {notification && (notification.includes("Failed") ? <div style={styles.notificationFailed}>{notification}</div> : <div style={styles.notification}>{notification}</div>)}


      {models.length === 0  ? (
        <p style={styles.noModels}>No models uploaded yet.</p>
      ) : (
        <div style={styles.modelGrid}>
          {models.map((model, index) => (
            <div key={index} style={styles.modelCard} className="model-card">
              <h3 style={styles.modelName}>{model.name} - v{model.version}</h3>
              <p>📅 Uploaded: {model.upload || "Unknown"}</p>
              <p>📦 Size: {model.size || "N/A"}</p>
              <div>
                <p style={styles.statusText}>⚡ Status: {model.status === "Deployed" ? "Deployed" : "Pending"}</p>

                <div style={styles.buttonContainer}>
                  {model.status === "Deployed" ? (
                    <div style={styles.buttonDiv}>
                    <button style={styles.button} onClick={() => setSelectedModel(model)}>Details</button>
                    <button style={styles.button} onClick={() => undeployModel(model.name, model.version)}>Undeploy</button>
                    </div>
                  ) : (
                    <div>
                    <button style={styles.button} onClick={() => navigate(`/deploy?model=${model.name}`)}>Deploy</button>
                    <button style={styles.deleteButton} onClick={() => deleteModel(model.name, model.version)}>
                    <i className="fa fa-trash-o"></i>
                    </button>
                    </div>
                  )}
                </div>
              </div>

            </div>
          ))} 
        </div>
      )}

      {/* ✅ Modal for Model Details */}
      {selectedModel && (
        <div style={styles.modalOverlay}>
          <div style={styles.modalContent}>
            <h2>Model Details</h2>
            <p><strong>Name:</strong> {selectedModel.name}</p>
            <p><strong>ID:</strong> {selectedModel._id}</p>
            <p><strong>Version:</strong> {selectedModel.version}</p>
            <p><strong>Deployed:</strong> {selectedModel.deploy}</p>
            <p><strong>REST API Endpoint:</strong></p>
            <p style={styles.apiBox}>{selectedModel.endpoint}</p>
            <button style={styles.inferenceButton} onClick={() => navToInferencePage(selectedModel.name)}>Go to Inference</button>
            <button style={styles.closeButton} onClick={() => setSelectedModel(null)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ModelOverview;

const styles = {
  container: {
    padding: "40px",
    backgroundColor: "#1f1f2e",
    color: "#fff",
    fontFamily: "'Roboto', sans-serif",
    minHeight: "100vh",
  },
  title: {
    fontSize: "28px",
    marginBottom: "20px",
    color: "#f9a825",
  },
  noModels: {
    textAlign: "center",
    fontSize: "18px",
    color: "#ccc",
  },
  modelGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(4, minmax(250px, 1fr))",
    gap: "20px",
  },
  modelCard: {
    backgroundColor: "#2a2a3c",
    padding: "20px",
    borderRadius: "10px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.2)",
    textAlign: "center",
  },
  modelName: {
    fontSize: "20px",
    marginBottom: "10px",
    overflow: "auto",
    color: "#f9a825",
  },
  button: {
    flex: "1",
    marginTop: "10px",
    minWidth: "120px", 
    whiteSpace: "nowrap", 
    padding: "10px",
    border: "none",
    backgroundColor: "#2575fc",
    color: "#fff",
    borderRadius: "8px",
    cursor: "pointer",
    transition: "background 0.3s ease",
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
  },
  homeIcon: {
    position: "absolute",
    cursor: "pointer",
    top: "25px",
    right: "25px",
    fontSize: "200%",
  },
  modalOverlay: {
    position: "fixed",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
  },
  modalContent: {
    backgroundColor: "#2a2a3c",
    padding: "20px",
    borderRadius: "10px",
    textAlign: "center",
    color: "#fff",
    width: "400px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.2)",
  },
  apiBox: {
    backgroundColor: "#1f1f2e",
    padding: "10px",
    borderRadius: "5px",
    wordBreak: "break-all",
    border: "1px solid #6a11cb",
  },
  inferenceButton: {
    backgroundColor: "#2575fc",
    color: "#fff",
    padding: "10px 15px",
    borderRadius: "8px",
    border: "none",
    cursor: "pointer",
    fontSize: "16px",
    marginTop: "10px",
    marginRight: "10px",
  
  },
  closeButton: {
    backgroundColor: "#ff4d4d",
    color: "#fff",
    padding: "10px 15px",
    borderRadius: "8px",
    border: "none",
    cursor: "pointer",
    fontSize: "16px",
    marginTop: "10px",
    marginLeft: "10px"
  },
  testGrid: {
    display: "grid",
    gridTemplateRows: "repeat(auto-fit, minmax(250px, 1fr))",
    gap: "20px",
  },
  testCard: {
    backgroundColor: "#2a2a3c",
    padding: "20px",
    borderRadius: "10px",
    boxShadow: "0 4px 8px rgba(0, 0, 0, 0.2)",
    textAlign: "left",
  },
  testSpan: {
    textAlign: "left",
  },
  testButton: {
    float: "right"
  },
  deleteButton: {
    background: "red",
    padding: "10px 10px",
    marginLeft: "5px"
  },
  notification: {
    position: "fixed",
    top: "10px",
    left: "50%",
    transform: "translateX(-50%)",
    backgroundColor: "#4CAF50",
    color: "#fff",
    padding: "10px 20px",
    borderRadius: "8px",
    boxShadow: "0px 4px 6px rgba(0, 0, 0, 0.2)",
    zIndex: 1000,
    fontSize: "16px",
    fontWeight: "bold",
    transition: "opacity 0.3s ease",
  },
  notificationFailed: {
    position: "fixed",
    top: "10px",
    left: "50%",
    transform: "translateX(-50%)",
    backgroundColor: "red",
    color: "#fff",
    padding: "10px 20px",
    borderRadius: "8px",
    boxShadow: "0px 4px 6px rgba(0, 0, 0, 0.2)",
    zIndex: 1000,
    fontSize: "16px",
    fontWeight: "bold",
    transition: "opacity 0.3s ease",
  },
  buttonDiv: {
    display: "flex",        
    gap: "10px",           
    justifyContent: "center", 
    alignItems: "center",  
  }
};
