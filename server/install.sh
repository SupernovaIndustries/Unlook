#!/bin/bash

echo "=== UnLook Scanner Server - Script di installazione ==="
echo

# Controllo privilegi di root
if [ "$EUID" -ne 0 ]; then
    echo "Questo script deve essere eseguito come root"
    exit 1
fi

echo "Creazione delle directory..."
mkdir -p /opt/unlook
mkdir -p /var/log/unlook

echo "Impostazione dei permessi..."
chown -R root:root /opt/unlook
chmod -R 755 /opt/unlook

echo "Installazione delle dipendenze di sistema..."
apt update
apt install -y python3-full python3-pip python3-venv python3-picamera2 python3-opencv python3-numpy

echo "Creazione e attivazione dell'ambiente virtuale..."
python3 -m venv /opt/unlook/venv
source /opt/unlook/venv/bin/activate

echo "Installazione delle dipendenze Python nell'ambiente virtuale..."
/opt/unlook/venv/bin/pip install -r requirements.txt

echo "Copia dei file del server..."
cp -r src/* /opt/unlook/
cp unlook.service /etc/systemd/system/

# Modifica il file service per usare l'ambiente virtuale
sed -i 's|ExecStart=.*|ExecStart=/opt/unlook/venv/bin/python3 /opt/unlook/main.py|g' /etc/systemd/system/unlook.service

echo "Installazione del servizio systemd..."
systemctl daemon-reload
systemctl enable unlook.service

echo "Abilitazione della camera Raspberry Pi..."
raspi-config nonint do_camera 0

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