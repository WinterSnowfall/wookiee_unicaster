#!/bin/bash

# NOTE: this script uses ufw to automatically allow network traffic on
# all of the required ports. Please make sure ufw is installed and enabled on
# target system and that the ufw command can be run by the REMOTE_SSH_USER.

#bash output styles and colors
DEFAULT="\033[0m"
BOLD="\033[1m"
BLINK="\033[5m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"

############### SCRIPT PARAMETERS - MUST BE CONFIGURED PROPERLY #################
#
# name of the ethernet interface on which the public IP resides
REMOTE_INFT_NAME="eth0"
# remote public IP - this host should be accesible using pre-configured ssh-keys,
# otherwise you will be prompted for a password during the connection setup stage
REMOTE_PUBLIC_IP="216.58.212.164"
# remote SSH user - using root is less of a hassle, otherwise passwordless sudo
# rights for using ufw are highly recommended
REMOTE_SSH_USER="root"
# leave blank for direct root SSH connections, otherwise set it to "sudo"
REMOTE_SSH_SUDO=""
# path to the Wookiee Unicaster script on the remote server
REMOTE_WU_PATH="/root/wookiee_unicaster.py"
# path to the Wookiee Unicaster script on the local host
LOCAL_WU_PATH="/home/username/wookiee_unicaster.py"
# number of remote players to enable with the Wookiee Unicaster
# some games that use a client-server Direct IP approach will
# work with the full number of advertized players, while P2P
# implementations will only support the default of one remote peer
# -> leave the value blank in order to set up one remote peer only
# -> use "-p 3" to enable 3 remote peers, for a total of 4 players
WU_REMOTE_PEERS=""
# ports that will be open for WU internal relaying of traffic
# use "23001" for one remote peer, and a range such as "23001:23003" 
# for 3 remote peers
WU_RELAY_PORT_RANGE="23001"
# local LAN interface name
LAN_INTF_NAME="enp1s0"
# local IP - this is where the game server needs to run, as all remote peers
# connecting via the public IP will be forwarded to this address
LOCAL_PRIVATE_IP=$(ifconfig $LAN_INTF_NAME | grep -w inet | awk '{print $2;}')
#
#################################################################################

start_tcp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $1/tcp" > /dev/null 2>&1
    ssh -fNT -R $1:$LOCAL_PRIVATE_IP:$1 $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP
}

start_udp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $1/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $WU_RELAY_PORT_RANGE/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_WU_PATH -m server $WU_REMOTE_PEERS -e $REMOTE_INFT_NAME -i $1 >> wookiee_unicaster.log 2>&1 &" > /dev/null 2>&1
    $LOCAL_WU_PATH -m client $WU_REMOTE_PEERS -e $LAN_INTF_NAME -s $REMOTE_PUBLIC_IP -d $LOCAL_PRIVATE_IP -o $1 >> wookiee_unicaster.log 2>&1 &
}

stop_tcp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1/tcp" > /dev/null 2>&1
    kill $(ps -ef | grep "ssh -fNT" | grep -v grep | awk '{print $2;}') 
}

stop_udp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $WU_RELAY_PORT_RANGE/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "killall wookiee_unicaster" > /dev/null 2>&1
    killall wookiee_unicaster > /dev/null 2>&1
}

echo "*** WinterSnowfall's port forwarding setup script for Linux ***"
echo ""
echo -e ">>> Configured remote IP : "$YELLOW$REMOTE_PUBLIC_IP$DEFAULT
echo -e ">>> Detected local IP : "$GREEN$LOCAL_PRIVATE_IP$DEFAULT
echo ""
echo "######################################################"
echo "#                                                    #"
echo "#   (1)  Sins Of A Solar Empire - Rebellion          #"
echo "#   (2)  Warhammer 40,000 Gladius - Relics Of War    #"
echo "#   (3)  Supreme Commander (+ Forged Alliance)       #"
echo "#   (4)  Worms Armageddon                            #"
echo "#   (5)  Divinity Original Sin - Enhanced Edition    #"
echo "#   (6)  Anno 1701 (+ The Sunken Dragon)             #"
echo "#   (7)  Civilization IV (& Addons)                  #"
echo "#   (8)  Quake III - Arena (+ Team Arena)            #"
echo "#   (9)  War For The Overworld                       #"
echo "#                                                    #"
echo "######################################################"
echo ""
read -p ">>> Pick a game for Direct IP play: " GAME

case $GAME in
    1)
        #Sins Of A Solar Empire - Rebellion
        GAME_PROTO="TCP"
        GAME_PORTS="6112"
        ;;
    2)
        #Warhammer 40,000 Gladius - Relics Of War
        GAME_PROTO="TCP"
        GAME_PORTS="6120"
        ;;
    3)
        #Supreme Commander (+ Forged Alliance)
        GAME_PROTO="UDP"
        GAME_PORTS="16010"
        ;;
    4)
        #Worms Armageddon
        GAME_PROTO="TCP"
        GAME_PORTS="17011"
        ;;
    5)
        #Divinity Original Sin - Enhanced Edition
        GAME_PROTO="UDP"
        GAME_PORTS="23253"
        ;;
    6)
        #Anno 1701 (+ The Sunken Dragon)
        GAME_PROTO="UDP"
        GAME_PORTS="21701"
        ;;
    7)
        #Civilization IV (& Addons)
        GAME_PROTO="UDP"
        GAME_PORTS="2056"
        ;;
    8)
        #Quake III - Arena (+ Team Arena)
        GAME_PROTO="UDP"
        GAME_PORTS="27960"
        ;;
    9)
        #War For The Overworld
        GAME_PROTO="UDP"
        GAME_PORTS="27015"
        ;;
    *)
        echo ">>> Invalid option!"
        exit 1
        ;;
esac

case $GAME_PROTO in
    TCP)
        # forward/tunnel ports through SSH based on the selected option
        echo -e ">>> Setting up TCP relaying on port(s): "$BOLD$GAME_PORTS$DEFAULT
        start_tcp_forwarding $GAME_PORTS
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_tcp_forwarding $GAME_PORTS
        ;;
    UDP)
        # relay port traffic using the Wookiee Unicaster based on the selected option 
        echo -e ">>> Setting up UDP relaying on port(s): "$BOLD$GAME_PORTS$DEFAULT
        start_udp_forwarding $GAME_PORTS
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_udp_forwarding $GAME_PORTS
        ;;
    *)
        echo ">>> Invalid option!"
        exit 1
        ;;
esac

echo ">>> Port forwarding connections have been severed."

