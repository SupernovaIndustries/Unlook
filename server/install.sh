#!/bin/bash

# Script di installazione per il server UnLook su Raspberry Pi
echo "=== UnLook Scanner Server - Script di installazione ==="
echo

# Verifica se lo script è eseguito come root
if [ "$(id -u)" -ne 0 ]; then
    echo "Questo script deve essere eseguito come root"
    echo "Riprova con: sudo $0"
    exit 1
fi

# Imposta le directory
INSTALL_DIR="/opt/unlook"
SERVER_DIR="$INSTALL_DIR/server"
LOG_DIR="/var/log/unlook"
DATA_DIR="/var/lib/unlook"
CONFIG_DIR="/etc/unlook"

echo "Creazione delle directory..."
mkdir -p "$SERVER_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/captures"
mkdir -p "$CONFIG_DIR"

# Imposta i permessi corretti
echo "Impostazione dei permessi..."
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chown -R root:root "$LOG_DIR"
chmod -R 755 "$LOG_DIR"
chown -R root:root "$DATA_DIR"
chmod -R 755 "$DATA_DIR"
chown -R root:root "$CONFIG_DIR"
chmod -R 755 "$CONFIG_DIR"

# Installa le dipendenze
echo "Installazione delle dipendenze di sistema..."
apt-get update
apt-get install -y python3 python3-pip python3-picamera2 python3-opencv python3-numpy

# Installa le dipendenze Python
echo "Installazione delle dipendenze Python..."
pip3 install pyzmq pillow simplejpeg psutil

# Copia i file del server
echo "Copia dei file del server..."
cp -r ./* "$SERVER_DIR/"

# Copia il file di servizio
echo "Installazione del servizio systemd..."
cp unlook.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable unlook.service

# Abilita la camera
echo "Abilitazione della camera Raspberry Pi..."
raspi-config nonint do_camera 0

# Crea ID dispositivo univoco se non esiste
if [ ! -f "$CONFIG_DIR/device_id" ]; then
    echo "Generazione dell'ID dispositivo univoco..."
    python3 -c "import uuid; print(uuid.uuid4())" > "$CONFIG_DIR/device_id"
fi

echo
echo "Installazione completata!"
echo
echo "Per avviare il servizio:"
echo "  sudo systemctl start unlook.service"
echo
echo "Per verificare lo stato:"
echo "  sudo systemctl status unlook.service"
echo
echo "Per visualizzare i log:"
echo "  sudo journalctl -u unlook.service -f"
echo
echo "Il server è raggiungibile tramite discovery automatica sulla rete locale."
echo
echo "=== Grazie per aver installato UnLook Scanner Server ==="