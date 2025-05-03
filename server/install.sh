#!/bin/bash
# UnLook Server Installer
# (c) 2025 SupernovaIndustries

set -e  # Termina lo script se qualsiasi comando fallisce

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}   UnLook Server Installer v1.0    ${NC}"
echo -e "${GREEN}====================================${NC}"

# Verifica che lo script sia eseguito come root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Errore: Questo script deve essere eseguito come root${NC}"
  echo "Riprovare con: sudo ./install.sh"
  exit 1
fi

# Verifica sistema operativo
if [ ! -f /etc/os-release ] || ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
  echo -e "${YELLOW}Attenzione: Questo script è ottimizzato per Raspberry Pi.${NC}"
  echo -e "${YELLOW}L'installazione potrebbe non funzionare correttamente su altri sistemi.${NC}"
  read -p "Continuare comunque? (s/n): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Ss]$ ]]; then
    echo "Installazione annullata."
    exit 1
  fi
fi

# Directory di installazione
INSTALL_DIR="/opt/unlook-server"
CONFIG_DIR="/etc/unlook"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="unlook-server"

# Parametri di configurazione
I2C_BUS=3
I2C_ADDRESS="0x1b"
AUTO_START=true

# Prompt per parametri di configurazione
echo -e "\n${GREEN}Configurazione del server UnLook:${NC}"
read -p "Bus I2C per il proiettore DLP [3]: " input
I2C_BUS=${input:-$I2C_BUS}

read -p "Indirizzo I2C per il proiettore DLP [0x1b]: " input
I2C_ADDRESS=${input:-$I2C_ADDRESS}

read -p "Avviare automaticamente all'avvio del sistema? (s/n) [s]: " input
if [[ ${input:-s} =~ ^[Nn]$ ]]; then
  AUTO_START=false
fi

echo -e "\n${GREEN}Installazione dipendenze di sistema...${NC}"
apt-get update
apt-get install -y python3-venv python3-dev python3-pip git python3-libcamera python3-picamera2 python3-kms \
                   python3-pyqt5 python3-prctl libatlas-base-dev ffmpeg libopenjp2-7 i2c-tools

# Verifica che I2C sia abilitato
if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt; then
  echo -e "${YELLOW}Abilitazione I2C in /boot/config.txt...${NC}"
  echo "dtparam=i2c_arm=on" >> /boot/config.txt
  echo "È necessario riavviare per attivare l'I2C."
  REBOOT_REQUIRED=true
fi

# Verifica memoria GPU
if ! grep -q "^gpu_mem=" /boot/config.txt; then
  echo -e "${YELLOW}Impostazione memoria GPU a 128MB in /boot/config.txt...${NC}"
  echo "gpu_mem=128" >> /boot/config.txt
  REBOOT_REQUIRED=true
elif grep -q "^gpu_mem=[0-9]\+$" /boot/config.txt; then
  GPU_MEM=$(grep "^gpu_mem=[0-9]\+" /boot/config.txt | cut -d'=' -f2)
  if [ "$GPU_MEM" -lt 128 ]; then
    echo -e "${YELLOW}Aumento memoria GPU a 128MB in /boot/config.txt...${NC}"
    sed -i 's/^gpu_mem=[0-9]\+/gpu_mem=128/' /boot/config.txt
    REBOOT_REQUIRED=true
  fi
fi

# Crea le directory di installazione se non esistono
mkdir -p ${INSTALL_DIR}
mkdir -p ${CONFIG_DIR}
mkdir -p ${INSTALL_DIR}/logs
mkdir -p ${INSTALL_DIR}/scans

# Determina la directory del progetto (quella dello script o la directory corrente)
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Copia i file di progetto
echo -e "\n${GREEN}Copia dei file di progetto...${NC}"
cp -r "${PROJECT_DIR}"/* ${INSTALL_DIR}/

# Crea l'ambiente virtuale
echo -e "\n${GREEN}Creazione ambiente virtuale Python...${NC}"
python3 -m venv ${VENV_DIR}
source ${VENV_DIR}/bin/activate

# Installa le dipendenze
echo -e "\n${GREEN}Installazione dipendenze Python...${NC}"
pip install --upgrade pip
pip install wheel
pip install -r ${INSTALL_DIR}/requirements.txt

# Verifica che picamera2 sia installata
if ! pip list | grep -q "picamera2"; then
  echo -e "${YELLOW}picamera2 non trovata nel venv, tentativo di installazione...${NC}"
  pip install picamera2
fi

# Crea il file di configurazione
echo -e "\n${GREEN}Creazione file di configurazione...${NC}"
cat > ${CONFIG_DIR}/unlook-server.conf << EOL
# Configurazione UnLook Server

# Parametri proiettore DLP
I2C_BUS=${I2C_BUS}
I2C_ADDRESS=${I2C_ADDRESS}

# Parametri di avvio
DEBUG=false
LOG_LEVEL=INFO

# Directory
SCAN_DIR=${INSTALL_DIR}/scans
LOG_DIR=${INSTALL_DIR}/logs
EOL

# Crea lo script wrapper
echo -e "\n${GREEN}Creazione script di avvio...${NC}"
cat > /usr/local/bin/unlook-server << EOL
#!/bin/bash
# Script di avvio per UnLook Server

# Carica configurazione
if [ -f /etc/unlook/unlook-server.conf ]; then
  source /etc/unlook/unlook-server.conf
fi

# Imposta variabili d'ambiente
export UNLOOK_I2C_BUS=\${I2C_BUS:-3}
export UNLOOK_I2C_ADDRESS=\${I2C_ADDRESS:-"0x1b"}
export UNLOOK_SCAN_DIR=\${SCAN_DIR:-"/opt/unlook-server/scans"}
export UNLOOK_LOG_DIR=\${LOG_DIR:-"/opt/unlook-server/logs"}

# Attiva l'ambiente virtuale
source /opt/unlook-server/venv/bin/activate

# Avvia il server
cd /opt/unlook-server
exec python3 server/main_standalone.py --i2c-address \${UNLOOK_I2C_ADDRESS} --i2c-bus \${UNLOOK_I2C_BUS} \$@
EOL

chmod +x /usr/local/bin/unlook-server

# Crea il file di servizio systemd
echo -e "\n${GREEN}Creazione servizio systemd...${NC}"
cat > /etc/systemd/system/unlook-server.service << EOL
[Unit]
Description=UnLook 3D Scanner Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/unlook-server
Restart=on-failure
RestartSec=5
StandardOutput=append:/opt/unlook-server/logs/unlook-server.log
StandardError=append:/opt/unlook-server/logs/unlook-server-error.log
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOL

# Ricaricare systemd
systemctl daemon-reload

# Avvio automatico se richiesto
if [ "$AUTO_START" = true ]; then
  echo -e "\n${GREEN}Abilitazione avvio automatico...${NC}"
  systemctl enable unlook-server.service

  # Avvia il servizio solo se non serve riavviare
  if [ "$REBOOT_REQUIRED" != true ]; then
    echo -e "\n${GREEN}Avvio del servizio...${NC}"
    systemctl start unlook-server.service
  fi
fi

echo -e "\n${GREEN}=============================================${NC}"
echo -e "${GREEN}Installazione di UnLook Server completata!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo -e "Directory installazione: ${INSTALL_DIR}"
echo -e "File configurazione: ${CONFIG_DIR}/unlook-server.conf"

if [ "$REBOOT_REQUIRED" = true ]; then
  echo -e "\n${YELLOW}ATTENZIONE: È necessario riavviare il sistema per completare l'installazione.${NC}"
  read -p "Riavviare adesso? (s/n): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Ss]$ ]]; then
    echo "Riavvio in corso..."
    reboot
  else
    echo "Per favore riavvia il sistema manualmente quando possibile."
  fi
else
  echo -e "\nPer avviare manualmente il server: ${GREEN}unlook-server${NC}"
  echo -e "Per controllare lo stato del servizio: ${GREEN}systemctl status unlook-server${NC}"
  echo -e "Per visualizzare i log: ${GREEN}journalctl -u unlook-server -f${NC}"

  if [ "$AUTO_START" = true ]; then
    echo -e "\nStato del servizio:"
    systemctl status unlook-server --no-pager
  fi
fi