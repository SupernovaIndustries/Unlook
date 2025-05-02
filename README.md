# UnLook 3D Scanner

<div align="center">
  <img src="http://supernovaindustries.it/wp-content/uploads/2024/08/logo_full-white-unlook-1.svg" alt="Supernova Industries Logo" width="300" />
  <h1>UnLook 3D Scanner</h1>
  
  <p><strong>Open Source Structured Light 3D Scanner</strong></p>
  <p>A professional-grade 3D scanning platform built with Raspberry Pi CM4 and advanced triangulation algorithms</p>

  <p>
    <a href="#features">Features</a> •
    <a href="#architecture">Architecture</a> •
    <a href="#how-it-works">How It Works</a> •
    <a href="#hardware-requirements">Hardware</a> •
    <a href="#installation">Installation</a> •
    <a href="#usage">Usage</a> •
    <a href="#development">Development</a> •
    <a href="#license">License</a>
  </p>
</div>

## Overview

UnLook is an open-source, modular 3D scanner system that uses structured light technology to create detailed 3D models of physical objects. Built around the Raspberry Pi Compute Module 4, UnLook offers exceptional versatility through its interchangeable optics, dual-camera system, and customized DLP projector.

The software stack features a client-server architecture that separates hardware control (server on Raspberry Pi) from the user interface and processing (client on PC), allowing for flexible deployment and operation.

Our mission is to make professional-grade 3D scanning accessible to everyone, from hobbyists and makers to professionals and researchers, by providing a fully open platform that can be customized, improved, and extended by the community.

## Features

- **Multiple Scanning Methods**
  - Structured light scanning with dual-camera system and custom DLP projector
  - Various structured light patterns (Progressive, Gray code, Binary code)
  - Real-time scanning with ToF MLX75027 sensor (in development)
  - Interchangeable optics system similar to professional cameras

- **High Performance Triangulation**
  - Advanced triangulation algorithms for precise 3D reconstruction
  - Multiple pattern types optimized for different surface materials
  - Adaptive refinement for high-detail scanning
  - Point cloud filtering and optimization

- **Robust Client-Server Architecture**
  - Automatic discovery of scanners on the network
  - Reliable ZeroMQ-based communication protocol
  - Real-time video streaming from cameras
  - Resilient error handling and recovery

- **Modern User Interface**
  - Qt-based GUI built with PySide6
  - Real-time visualization of scan progress
  - Interactive 3D point cloud manipulation
  - Detailed scan history and management

- **Comprehensive Export Options**
  - Standard 3D file formats (.ply, .obj)
  - Point cloud and mesh generation
  - Compatible with popular 3D modeling software

## Architecture

UnLook follows a client-server architecture that separates the scanning hardware control from the user interface and processing:

### Server (Raspberry Pi CM4)
- Controls dual cameras using PiCamera2
- Manages the DLP projector via I2C for pattern projection
- Coordinates 3D scanning sequences with precise timing
- Streams video to the client
- Handles modular hardware components through a unified interface

### Client (Desktop PC)
- Provides a user-friendly interface with PySide6 (Qt)
- Processes scan data using OpenCV and Open3D
- Performs 3D triangulation and point cloud generation
- Visualizes and manipulates 3D point clouds
- Automatically discovers scanners on the network

### Communication
- ZeroMQ for reliable, high-performance messaging
- Custom protocol for efficient command and data transfer
- UDP-based scanner discovery
- Optimized video streaming format

### Code Structure
```
UnLook/
├── client/                # Desktop application (PySide6-based GUI)
│   ├── controllers/       # MVC controllers
│   ├── models/            # Data models
│   ├── network/           # Network communication
│   ├── processing/        # 3D processing algorithms
│   ├── views/             # UI components
│   └── main.py            # Client application entry point
├── server/                # Raspberry Pi software
│   ├── projector/         # DLP projector control
│   ├── main.py            # Server entry point
│   └── scan_manager.py    # Scanning process coordinator
├── common/                # Shared code
│   └── protocol.py        # Communication protocol definition
├── start_unlook.py        # Launcher script
└── requirements.txt       # Python dependencies
```

## How It Works

UnLook uses structured light scanning technology to create 3D models. Here's the basic workflow:

1. **Pattern Projection**: The DLP projector projects a sequence of precisely calculated light patterns onto the object.

2. **Synchronized Capture**: The dual cameras capture images of the object with each projected pattern.

3. **Pattern Decoding**: The software decodes the distortion of the patterns as seen by the cameras.

4. **Triangulation**: Using stereo vision principles and the decoded patterns, the system calculates the 3D position of each point.

5. **Point Cloud Generation**: The triangulated points form a dense point cloud representing the 3D surface.

6. **Post-Processing**: Filtering, mesh generation, and optimization create the final 3D model.

### Pattern Types

UnLook supports multiple structured light pattern types:

- **Progressive Patterns**: Lines that get progressively thinner, offering a good balance of speed and quality
- **Gray Code**: Binary encoding with error resistance for high precision
- **Binary Code**: Standard binary pattern sequence for faster scanning
- **Phase Shift**: Sinusoidal patterns for capturing complex surfaces (in development)

## Hardware Requirements

### Server (Scanner)
- **Core Components**:
  - Raspberry Pi Compute Module 4 (minimum 2GB RAM)
  - Two Pi Camera modules (PiCamera v2 or HQ Camera)
  - Custom DLP342X-based projector
  - Optional ToF MLX75027 sensor (for future extensions)
  - Custom carrier board with I2C connections

- **Additional Requirements**:
  - Stable power supply (5V, 3A minimum)
  - Proper heat dissipation
  - Rigid mounting system

### Client (Computer)
- **Minimum Requirements**:
  - Python 3.8 or newer
  - OpenGL-capable graphics
  - 4GB RAM (8GB recommended)
  - Network connectivity (Ethernet recommended for best performance)

## Installation

### Server Setup (Raspberry Pi)

```bash
# Clone the repository
git clone https://github.com/supernovaindustries/unlook.git
cd unlook/server

# Install dependencies
sudo ./install.sh

# Configure environment variables (if needed)
sudo nano /etc/unlook/environment

# Start the server
sudo systemctl start unlook.service

# Enable server autostart on boot
sudo systemctl enable unlook.service
```

### Client Setup (Desktop)

```bash
# Clone the repository
git clone https://github.com/supernovaindustries/unlook.git
cd unlook

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the client
python start_unlook.py
```

## Usage

### Basic Scanning Workflow

1. **Connection**
   - Launch the UnLook client application
   - The client will automatically discover scanners on your network
   - Select your scanner from the list and connect

2. **Preparation**
   - Position the object to be scanned on the platform
   - Ensure proper lighting conditions (dim, controlled lighting works best)
   - Use the live preview to check camera alignment and focus

3. **Configuration**
   - Select a scanning profile or configure custom settings:
     - Pattern type (Progressive, Gray Code, Binary)
     - Quality level (higher quality takes longer)
     - Resolution settings

4. **Scanning**
   - Start the scan process
   - Monitor real-time progress through the client interface
   - The system will project patterns and capture synchronized images

5. **Processing**
   - After capture, the system processes the data to generate a 3D point cloud
   - Apply optional filters and optimizations
   - Preview the result in the 3D viewer

6. **Export**
   - Save the 3D model in your preferred format (.ply, .obj)
   - Export for use in other 3D software

### Advanced Features

- **Camera Calibration**: Tools for calibrating the stereo camera system
- **Custom Pattern Sequences**: Define your own structured light pattern sequences
- **Batch Scanning**: Process multiple scans in sequence
- **Point Cloud Editing**: Basic tools for cleaning and optimizing 3D models

## Development

### Building from Source

```bash
# Install development dependencies
pip install -r requirements.txt

# Run tests
pytest

# Check code style
flake8
black .
```

### Contributing

We welcome contributions to the UnLook project! Here's how you can help:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Commit your changes** (`git commit -m 'Add some amazing feature'`)
4. **Push to the branch** (`git push origin feature/amazing-feature`)
5. **Open a Pull Request**

Please make sure your code follows our coding standards and includes appropriate tests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- Based on algorithms from structured light scanning research
- Built with OpenCV for image processing
- 3D visualization powered by Open3D
- Network communication via ZeroMQ

---

<p align="center">
  <a href="https://supernovaindustries.it">
    <img src="http://supernovaindustries.it/wp-content/uploads/2024/08/supernova-industries-logo.svg" alt="Supernova Industries Logo" width="200" />
  </a>
</p>

<p align="center">
  Made with ❤️ by <a href="https://supernovaindustries.it">Supernova Industries</a>
</p>

<p align="center">
  <a href="https://supernovaindustries.it">Website</a> •
  <a href="https://github.com/supernovaindustries">GitHub</a>
</p>