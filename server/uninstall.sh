#!/bin/bash
# UnLook Server Uninstaller

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${RED}====================================${NC}"
echo -e "${RED}   UnLook Server Uninstaller       ${NC}"
echo -e "${RED}====================================${NC}"

# Verifica che lo script sia eseguito come root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Errore: Questo script deve essere eseguito come root${NC}"
  echo "Riprovare con: sudo ./uninstall.sh"
  exit 1
fi

# Conferma disinstallazione
read -p "Sei sicuro di voler disinstallare UnLook Server? (s/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]; then
  echo "Disinstallazione annullata."
  exit 0
fi

# Chiedi se mantenere i dati
read -p "Vuoi mantenere i dati delle scansioni? (s/n): " -n 1 -r
echo
KEEP_DATA=false
if [[ $REPLY =~ ^[Ss]$ ]]; then
  KEEP_DATA=true
fi

# Ferma e disabilita il servizio
echo -e "\n${YELLOW}Arresto e disabilitazione del servizio...${NC}"
systemctl stop unlook-server.service || true
systemctl disable unlook-server.service || true

# Rimuovi i file di servizio
echo -e "\n${YELLOW}Rimozione dei file di servizio...${NC}"
rm -f /etc/systemd/system/unlook-server.service
systemctl daemon-reload

# Rimuovi lo script wrapper
echo -e "\n${YELLOW}Rimozione degli script di avvio...${NC}"
rm -f /usr/local/bin/unlook-server

# Rimuovi file di configurazione
echo -e "\n${YELLOW}Rimozione dei file di configurazione...${NC}"
rm -rf /etc/unlook

# Rimuovi l'installazione
echo -e "\n${YELLOW}Rimozione dei file di installazione...${NC}"
if [ "$KEEP_DATA" = true ]; then
  # Backup dei dati
  if [ -d /opt/unlook-server/scans ]; then
    echo -e "${GREEN}Backup dei dati delle scansioni in ~/unlook-scans-backup...${NC}"
    mkdir -p ~/unlook-scans-backup
    cp -r /opt/unlook-server/scans/* ~/unlook-scans-backup/ || true
  fi
fi

# Rimuovi la directory di installazione
rm -rf /opt/unlook-server

echo -e "\n${GREEN}=============================================${NC}"
echo -e "${GREEN}Disinstallazione di UnLook Server completata!${NC}"
echo -e "${GREEN}=============================================${NC}"

if [ "$KEEP_DATA" = true ] && [ -d ~/unlook-scans-backup ]; then
  echo -e "I dati delle scansioni sono stati salvati in: ${GREEN}~/unlook-scans-backup${NC}"
fi