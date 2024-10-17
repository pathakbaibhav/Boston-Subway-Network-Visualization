# **Boston T Network Visualization - EECE 5642 Homework 4**

This repository contains the solution for **Homework 4** of the course **EECE 5642: Data Visualization** at **Northeastern University**, under the guidance of **Professor Y. Raymond Fu**. This project focuses on the visualization of the Boston T (subway) network as an undirected graph using **Processing** and **Python scripts** for data collection and analysis.

---

## **Overview**

The goal of this project is to visualize Boston’s subway network, the T, as a graph with stations as nodes and connections as edges. The project includes data collection, graph construction, and implementation of the **shortest path algorithm**.

### **Key Features**
1. **Network Graph Visualization**: Displays the Boston T network with station nodes and connection edges.
2. **Interactive Visualization**: Nodes are draggable, and shortest paths can be calculated interactively.
3. **Data Collection Scripts**: Python scripts collect and store MBTA station and connection data.
4. **Shortest Path Calculation**: Implements **Dijkstra’s algorithm** to compute the shortest path between two stations.
5. **Color Effects**: Animates edge color changes to distinguish active and non-active paths.

---

## **Repository Structure**

├── README.md # Project overview and setup instructions ├── TheTDataCollection # Folder containing data collection scripts │ ├── stations.py # Extracts station names from MBTA data │ ├── connections.py # Extracts connection data between stations │ └── stations.csv # Output - List of station names │ └── connections.csv # Output - List of connections with travel times ├── Framework # Framework for graph visualization using Processing │ └── Sketch Files # Processing sketches for visualization ├── Ex_1_2_X # Sketch versions for different stages (e.g., Shortest Path, Color Effect) └── HW4-EECE 5642.pdf # Original assignment instructions


---

## **Getting Started**

### **Prerequisites**
1. **Processing IDE**: Download and install from [Processing.org](https://processing.org/).
2. **Python 3.x**: Install from [Python.org](https://www.python.org/).
3. **Required Python Libraries**:
   ```bash
   pip install pandas requests
