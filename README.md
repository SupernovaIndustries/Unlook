# UnLook 3D Scanner

<p align="center">
  <img src="https://via.placeholder.com/200x200?text=UnLook+Logo" alt="UnLook Logo" width="200" height="200"/>
</p>

<p align="center">
  <strong>Open Source Structured Light 3D Scanner based on Raspberry Pi CM4</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#hardware">Hardware</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#development">Development</a> •
  <a href="#license">License</a>
</p>

## Overview

UnLook is an open-source, modular 3D scanner system that uses structured light technology to create detailed 3D models of physical objects. Built around the Raspberry Pi Compute Module 4, UnLook offers exceptional versatility through its interchangeable optics, dual-camera system, and customized DLP projector.

Our mission is to make professional-grade 3D scanning accessible to everyone, from hobbyists and makers to professionals and researchers, by providing a fully open platform that can be customized, improved, and extended by the community.

## Features

- **Multiple Scanning Methods**:
  - Structured light scanning with dual-camera system and custom DLP projector
  - Real-time scanning with ToF MLX75027 sensor (in development)
  - Interchangeable optics system similar to professional cameras

- **High Performance**:
  - High precision 3D reconstruction using advanced triangulation algorithms
  - Adjustable resolution and quality settings
  - Optimized for speed and accuracy

- **Open & Extensible**:
  - Fully open-source software stack
  - Modular hardware design
  - Supports custom scanning patterns and algorithms
  - Expandable through plugins (in development)

- **User-Friendly**:
  - Modern Qt-based GUI on the client side
  - Real-time visualization of scan progress
  - Automatic scanner discovery on the network
  - Interactive 3D point cloud manipulation

- **Export Options**:
  - Standard 3D file formats (.ply, .obj)
  - Point cloud and mesh generation
  - Compatible with popular 3D modeling software

## Architecture

UnLook follows a client-server architecture that separates the scanning hardware control from the user interface and processing:

### Server (Raspberry Pi CM4)
- Controls cameras using PiCamera2
- Manages the DLP projector for pattern projection
- Coordinates 3D scanning sequences
- Streams video to the client
- Handles modular hardware components

### Client (Desktop PC)
- Provides a user-friendly interface with PySide6 (Qt)
- Processes scan data using OpenCV and Open3D
- Visualizes and manipulates 3D point clouds
- Configures scanning parameters
- Automatically discovers scanners on the network

### Communication
- ZeroMQ for reliable, high-performance messaging
- Zeroconf for automatic scanner discovery
- Custom protocol for commands and data transfer

## Hardware

### Core Components
- Raspberry Pi Compute Module 4 (server)
- Two Pi Camera modules (configurable resolution)
- Custom DLP342X-based projector
- Optional ToF MLX75027 sensor
- Interchangeable lens system

### Recommended Setup
- Raspberry Pi CM4 with at least 2GB RAM
- Dual Raspberry Pi Camera v2 or HQ Camera
- DLP projector with DLPC342X controller
- PC with OpenGL support for client software

## Installation

### Prerequisites
- Raspberry Pi OS Bullseye (64-bit recommended) for server
- Python 3.8+ on both client and server
- OpenCV, NumPy, and Open3D for client processing
- PySide6 for client GUI

### Server Setup
```bash
# Clone the repository
git clone https://github.com/supernovaindustries/unlook.git
cd unlook/server

# Install dependencies
sudo ./install.sh

# Start the server as a service
sudo systemctl start unlook.service
```

### Client Setup
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

1. **Preparation**
   - Position the object to be scanned on the scan platform
   - Ensure proper lighting conditions
   - Turn on the UnLook scanner

2. **Connection**
   - Launch the UnLook client application
   - The client automatically discovers scanners on your network
   - Select your scanner from the list and connect

3. **Configuration**
   - Adjust scan quality, resolution, and pattern type
   - Preview camera feeds to check object positioning
   - Configure export options as needed

4. **Scanning**
   - Start the scan process
   - Monitor real-time progress through the client interface
   - Review the results in the preview window

5. **Processing**
   - Process the scan data to generate a 3D point cloud
   - Apply optional filters and optimizations
   - Export the model in your desired format

### Advanced Features

- **Pattern Selection**: Choose between different structured light patterns (Gray Code, Progressive, Binary) for optimal results with different surface types
- **Quality Settings**: Balance between scan speed and detail level
- **Manual Calibration**: Fine-tune camera parameters for improved accuracy
- **Point Cloud Editing**: Basic editing tools for cleaning and optimizing 3D models

## Development

### Code Structure
- `client/`: Desktop application (PySide6-based GUI)
- `server/`: Raspberry Pi software for hardware control
- `common/`: Shared code and protocol definitions
- `projector/`: DLP projector control modules

### Building from Source
```bash
# Install development dependencies
pip install -r requirements.txt

# Run the diagnostic tool
python diagnostic.py
```

### Contributing
We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.

## Acknowledgements

- Based on algorithms from the Structured-light-stereo project
- Uses OpenCV for image processing
- 3D visualization powered by Open3D
- Network communication via ZeroMQ

---

<p align="center">
  Made with ❤️ by Supernova Industries
</p>

<p align="center">
  <a href="https://supernovaindustries.com">Website</a> •
  <a href="https://github.com/supernovaindustries">GitHub</a>
</p>