#!/bin/bash

# NOTE: this script uses ufw to automatically allow network traffic on
# all of the required ports. Please make sure ufw is installed and enabled on
# target system and that the ufw command can be run by the REMOTE_SSH_USER.

# bash output styles and colors
DEFAULT="\033[0m"
BOLD="\033[1m"
BLINK="\033[5m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"

############### SCRIPT PARAMETERS - MUST BE CONFIGURED PROPERLY #################
#
# name of the Ethernet interface on which the public IP resides
REMOTE_INFT_NAME="eth0"
# remote public IP - this host should be accessible using pre-configured ssh-keys,
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
# work with the full number of advertised players, while P2P
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

echo "*** WinterSnowfall's port forwarding script for Linux ***"
echo ""
echo -e ">>> Configured remote IP : "$YELLOW$REMOTE_PUBLIC_IP$DEFAULT
echo -e ">>> Detected local IP : "$GREEN$LOCAL_PRIVATE_IP$DEFAULT
echo ""
echo "#############################################################"
echo "#                                                           #"
echo "#  (1)   Age of Mythology (+ The Titans)                    #"
echo "#  (2)   Anno 1701 (+ The Sunken Dragon)                    #"
echo "#  (3)   ARMA: Cold War Assault / ARMA / ARMA 2 (& Addons)  #"
echo "#  (4)   Baldur's Gate / II - Enhanced Edition              #"
echo "#  (5)   Civilization IV (& Addons)                         #"
echo "#  (6)   Deus Ex                                            #"
echo "#  (7)   Divinity Original Sin - Enhanced Edition           #"
echo "#  (8)   Empire Earth II                                    #"
echo "#  (9)   Factorio                                           #"
echo "#  (10)  Hammerwatch                                        #"
echo "#  (11)  Icewind Dale - Enhanced Edition                    #"
echo "#  (12)  Kohan: Immortal Sovereigns / Ahriman's Gift        #"
echo "#  (13)  Kohan II: Kings of War                             #"
echo "#  (14)  Medal of Honor: Allied Assault (& Addons)          #"
echo "#  (15)  Mobile Forces                                      #"
echo "#  (16)  Neverwinter Nights - Enhanced Edition              #"
echo "#  (17)  OpenTTD                                            #"
echo "#  (18)  Pandora: First Contact (+ Eclipse of Nashira)      #"
echo "#  (19)  Quake III Arena (+ Team Arena)                     #"
echo "#  (20)  Red Faction                                        #"
echo "#  (21)  Return to Castle Wolfenstein                       #"
echo "#  (22)  Scrapland (Remastered)                             #"
echo "#  (23)  Sins of a Solar Empire: Rebellion                  #"
echo "#  (24)  Soldier of Fortune 2                               #"
echo "#  (25)  Star Trek: Voyager - Elite Force (Holomatch)       #"
echo "#  (26)  Star Trek: Elite Force II                          #"
echo "#  (27)  Star Wars: Jedi Knight - Jedi Academy              #"
echo "#  (28)  Star Wars: Jedi Knight II                          #"
echo "#  (29)  Star Wars: Republic Commando                       #"
echo "#  (30)  Stardew Valley                                     #"
echo "#  (31)  Supreme Commander (+ Forged Alliance)              #"
echo "#  (32)  SWAT 4 (+ The Stetchkov Syndicate)                 #"
echo "#  (33)  The Wheel of Time                                  #"
echo "#  (34)  Tom Clancy's Ghost Recon                           #"
echo "#  (35)  Unreal / Unreal Tournament '99 / 2004              #"
echo "#  (36)  War for the Overworld                              #"
echo "#  (37)  Warhammer 40,000 Gladius - Relics of War           #"
echo "#  (38)  Windward                                           #"
echo "#  (39)  World in Conflict (+ Soviet Assault)               #"
echo "#  (40)  Worms Armageddon                                   #"
echo "#                                                           #"
echo "#############################################################"
echo ""
read -p ">>> Pick a game for Direct IP play or press ENTER: " GAME

case $GAME in
    1)
        # Age of Mythology (+ The Titans)
        GAME_PROTOCOL="UDP"
        GAME_PORT="2299"
        ;;
    2)
        # Anno 1701 (+ The Sunken Dragon)
        GAME_PROTOCOL="UDP"
        GAME_PORT="21701"
        ;;
    3)
        # ARMA: Cold War Assault / ARMA / ARMA 2 (& Addons)
        GAME_PROTOCOL="UDP"
        GAME_PORT="2302"
        ;;
    4)
        # Baldur's Gate / II - Enhanced Edition
        GAME_PROTOCOL="UDP"
        GAME_PORT="47630"
        ;;
    5)
        # Civilization IV (& Addons)
        GAME_PROTOCOL="UDP"
        GAME_PORT="2056"
        ;;
    6)
        # Deus Ex
        GAME_PROTOCOL="UDP"
        GAME_PORT="7790"
        ;;
    7)
        # Divinity Original Sin - Enhanced Edition
        GAME_PROTOCOL="UDP"
        GAME_PORT="23253"
        ;;
    8)
        # Empire Earth II
        GAME_PROTOCOL="UDP"
        GAME_PORT="26000"
        ;;
    9)
        # Factorio
        GAME_PROTOCOL="UDP"
        GAME_PORT="34197"
        ;;
    10)
        # Hammerwatch
        GAME_PROTOCOL="UDP"
        GAME_PORT="9995"
        ;;
    11)
        # Icewind Dale - Enhanced Edition
        GAME_PROTOCOL="UDP"
        GAME_PORT="47630"
        ;;
    12)
        # Kohan: Immortal Sovereigns / Ahriman's Gift
        GAME_PROTOCOL="UDP"
        GAME_PORT="17437"
        ;;
    13)
        # Kohan II: Kings of War
        GAME_PROTOCOL="UDP"
        GAME_PORT="5860"
        ;;
    14)
        # Medal of Honor: Allied Assault (& Addons)
        GAME_PROTOCOL="UDP"
        GAME_PORT="12203"
        ;;
    15)
        # Mobile Forces
        GAME_PROTOCOL="UDP"
        GAME_PORT="7777"
        ;;
    16)
        # Neverwinter Nights - Enhanced Edition
        GAME_PROTOCOL="UDP"
        GAME_PORT="5121"
        ;;
    17)
        # OpenTTD
        GAME_PROTOCOL="TCP"
        GAME_PORT="3979"
        ;;
    18)
        # Pandora: First Contact (+ Eclipse of Nashira)
        GAME_PROTOCOL="TCP"
        GAME_PORT="6121"
        ;;
    19)
        # Quake III Arena (+ Team Arena)
        GAME_PROTOCOL="UDP"
        GAME_PORT="27960"
        ;;
    20)
        # Red Faction
        GAME_PROTOCOL="UDP"
        GAME_PORT="7755"
        ;;
    21)
        # Return to Castle Wolfenstein
        GAME_PROTOCOL="UDP"
        GAME_PORT="27960"
        ;;
    22)
        # Scrapland (Remastered)
        GAME_PROTOCOL="UDP"
        GAME_PORT="28086"
        ;;
    23)
        # Sins of a Solar Empire: Rebellion
        GAME_PROTOCOL="TCP"
        GAME_PORT="6112"
        ;;
    24)
        # Soldier of Fortune 2
        GAME_PROTOCOL="UDP"
        GAME_PORT="20100"
        ;;
    25)
        # Star Trek: Voyager - Elite Force (Holomatch)
        GAME_PROTOCOL="UDP"
        GAME_PORT="27960"
        ;;
    26)
        # Star Trek: Elite Force II
        GAME_PROTOCOL="UDP"
        GAME_PORT="29253"
        ;;
    27)
        # Star Wars: Jedi Knight - Jedi Academy
        GAME_PROTOCOL="UDP"
        GAME_PORT="29070"
        ;;
    28)
        # Star Wars: Jedi Knight II
        GAME_PROTOCOL="UDP"
        GAME_PORT="28070"
        ;;
    29)
        # Star Wars: Republic Commando
        GAME_PROTOCOL="UDP"
        GAME_PORT="7777"
        ;;
    30)
        # Stardew Valley
        GAME_PROTOCOL="UDP"
        GAME_PORT="24642"
        ;;
    31)
        # Supreme Commander (+ Forged Alliance)
        GAME_PROTOCOL="UDP"
        GAME_PORT="16010"
        ;;
    32)
        # SWAT 4 (+ The Stetchkov Syndicate)
        GAME_PROTOCOL="UDP"
        GAME_PORT="10480"
        ;;
    33)
        # The Wheel of Time
        GAME_PROTOCOL="UDP"
        GAME_PORT="7777"
        ;;
    34)
        # Tom Clancy's Ghost Recon
        GAME_PROTOCOL="TCP"
        GAME_PORT="2346"
        ;;
    35)
        # Unreal / Unreal Tournament '99 / 2004
        GAME_PROTOCOL="UDP"
        GAME_PORT="7777"
        ;;
    36)
        # War for the Overworld
        GAME_PROTOCOL="UDP"
        GAME_PORT="27015"
        ;;
    37)
        # Warhammer 40,000 Gladius - Relics of War
        GAME_PROTOCOL="TCP"
        GAME_PORT="6120"
        ;;
    38)
        # Windward
        GAME_PROTOCOL="TCP"
        GAME_PORT="5127"
        ;;
    39)
        # World in Conflict (+ Soviet Assault)
        GAME_PROTOCOL="TCP"
        GAME_PORT="48000"
        ;;
    40)
        # Worms Armageddon
        GAME_PROTOCOL="TCP"
        GAME_PORT="17011"
        ;;
    *)
        read -p ">>> Select forwarding protcol (TCP or UDP): " GAME_PROTOCOL
        read -p ">>> Select forwarding port: " GAME_PORT

        if ! [[ "$GAME_PORT" =~ ^[0-9]+$ ]] || [ "$GAME_PORT" -lt 1024 -o "$GAME_PORT" -gt 65535 ]
        then
            echo ">>> Invalid port selection!"
            exit 2
        fi
        ;;
esac

case ${GAME_PROTOCOL^^} in
    TCP)
        # forward/tunnel ports through SSH based on the selected option
        echo -e ">>> Setting up TCP relaying on port(s): "$BOLD$GAME_PORT$DEFAULT
        start_tcp_forwarding $GAME_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_tcp_forwarding $GAME_PORT
        ;;
    UDP)
        # relay port traffic using the Wookiee Unicaster based on the selected option 
        echo -e ">>> Setting up UDP relaying on port(s): "$BOLD$GAME_PORT$DEFAULT
        start_udp_forwarding $GAME_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_udp_forwarding $GAME_PORT
        ;;
    *)
        echo ">>> Invalid protocol selection!"
        exit 1
        ;;
esac

echo ">>> Port forwarding connections have been severed."

