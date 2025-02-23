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
# enable ssh keep alive for TCP port forwarding connections
REMOTE_SSH_OPTIONS="-o ServerAliveInterval=20"
# path to the Wookiee Unicaster script on the remote server
REMOTE_WU_PATH="/root/wookiee_unicaster.py"
# Wookiee Unicaster script or binary name on the remote server
REMOTE_WU_NAME=$(basename $REMOTE_WU_PATH)
# path to the Wookiee Unicaster script on the local host
LOCAL_WU_PATH="/home/username/wookiee_unicaster.py"
# Wookiee Unicaster script of binary name on the local host
LOCAL_WU_NAME=$(basename $LOCAL_WU_PATH)
# number of remote players to enable with the Wookiee Unicaster
# some games that use a client-server Direct IP approach will
# work with the full number of advertised players, while P2P
# implementations will only support the default of one remote peer
# use "-p 3" to enable 3 remote peers, for a total of 4 players
WU_REMOTE_PEERS="-p 1"
# ports that will be open for WU internal relaying of traffic
# use "23001" for one remote peer, and a range, such as "23001:23003", 
# for 3 remote peers
WU_RELAY_PORT_RANGE="23001"
# local LAN interface name
LAN_INTF_NAME="enp1s0"
# local IP - this is where the game server needs to run, as all remote peers
# connecting via the public IP will be forwarded to this address
LOCAL_PRIVATE_IP=$(ip -4 addr show $LAN_INTF_NAME 2>/dev/null | grep -w inet | awk '{print $2}' | cut -d '/' -f 1)
#
#################################################################################

# can only ever happen if an invalid LAN_INTF_NAME is used
if [ -z $LOCAL_PRIVATE_IP ]
then
    echo "Unable to detect local IP address. Check the LAN_INFT_NAME parameter and retry."
    exit 1
fi

if [ $(echo $WU_RELAY_PORT_RANGE | grep ":" | wc -l) -eq 0 ]
then
    # error out in case more than one peer is set for a single relay port
    if [ ${WU_REMOTE_PEERS:0-1} -gt 1 ]
    then
        echo "The specified number of WU_REMOTE_PEERS doesn't match the WU_RELAY_PORT_RANGE."
        exit 2
    fi
else
    # split the WU_RELAY_PORT_RANGE in its two edge values for validation
    WU_RELAY_PORT_RANGE_VALIDATION=($(echo $WU_RELAY_PORT_RANGE | tr ":" "\n"))
    # the relay port range difference + 1 needs to coincide with the number of remote peers
    if [ ! ${WU_REMOTE_PEERS:0-1} -eq $(expr ${WU_RELAY_PORT_RANGE_VALIDATION[1]} - ${WU_RELAY_PORT_RANGE_VALIDATION[0]} + 1) ]
    then
        echo "The specified number of WU_REMOTE_PEERS doesn't match the WU_RELAY_PORT_RANGE."
        exit 2
    fi
fi

start_tcp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $1/tcp" > /dev/null 2>&1
    ssh -fNT $REMOTE_SSH_OPTIONS -R $1:$LOCAL_PRIVATE_IP:$1 $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP > /dev/null 2>&1
}

start_udp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $1/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $WU_RELAY_PORT_RANGE/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_WU_PATH -m server $WU_REMOTE_PEERS -e $REMOTE_INFT_NAME -i $1 >> wookiee_unicaster.log 2>&1 &" > /dev/null 2>&1
    $LOCAL_WU_PATH -m client $WU_REMOTE_PEERS -e $LAN_INTF_NAME -s $REMOTE_PUBLIC_IP -d $LOCAL_PRIVATE_IP -o $1 >> wookiee_unicaster.log 2>&1 &
}

stop_tcp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1/tcp" > /dev/null 2>&1
    pkill -f "ssh -fNT" > /dev/null 2>&1
}

stop_udp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $WU_RELAY_PORT_RANGE/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "pkill -f $REMOTE_WU_NAME" > /dev/null 2>&1
    pkill -f $LOCAL_WU_NAME > /dev/null 2>&1
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
echo "#  (5)   Celtic Kings: Rage of War                          #"
echo "#  (6)   Civilization IV (& Addons)                         #"
echo "#  (7)   Codename: Panzers - Phase One / Two                #"
echo "#  (8)   Daikatana                                          #"
echo "#  (9)   Deus Ex                                            #"
echo "#  (10)  Divinity Original Sin - Enhanced Edition           #"
echo "#  (11)  Doom 3                                             #"
echo "#  (12)  Empire Earth II / III                              #"
echo "#  (13)  Empires: Dawn of the Modern World                  #"
echo "#  (14)  Etherlords                                         #"
echo "#  (15)  Etherlords II                                      #"
echo "#  (16)  Factorio                                           #"
echo "#  (17)  Haegemonia: Legions of Iron                        #"
echo "#  (18)  Haegemonia: The Solon Heritage                     #"
echo "#  (10)  Hammerwatch                                        #"
echo "#  (20)  Icewind Dale - Enhanced Edition                    #"
echo "#  (21)  Iron Storm                                         #"
echo "#  (22)  I.G.I.-2: Covert Strike                            #"
echo "#  (23)  Jazz Jackrabbit 2 (& Plus / JJ2+)                  #"
echo "#  (24)  Kingpin: Life of Crime                             #"
echo "#  (25)  Kohan: Immortal Sovereigns / Ahriman's Gift        #"
echo "#  (26)  Kohan II: Kings of War                             #"
echo "#  (27)  Master of Orion 3                                  #"
echo "#  (28)  Medal of Honor: Allied Assault (& Addons)          #"
echo "#  (29)  Mobile Forces                                      #"
echo "#  (30)  Neverwinter Nights - Enhanced Edition              #"
echo "#  (31)  OpenTTD                                            #"
echo "#  (32)  Painkiller (+ Black Edition)                       #"
echo "#  (33)  Painkiller: Overdose                               #"
echo "#  (34)  Pandora: First Contact (+ Eclipse of Nashira)      #"
echo "#  (35)  Patrician 3                                        #"
echo "#  (36)  Quake II (+ The Reckoning / Ground Zero)           #"
echo "#  (37)  Quake III Arena (+ Team Arena)                     #"
echo "#  (38)  Quake 4                                            #"
echo "#  (39)  Red Faction                                        #"
echo "#  (40)  Return to Castle Wolfenstein                       #"
echo "#  (41)  Rune Gold / Classic                                #"
echo "#  (42)  Scrapland (Remastered)                             #"
echo "#  (43)  SiN (+ Wages of Sin)                               #"
echo "#  (44)  Sins of a Solar Empire: Rebellion                  #"
echo "#  (45)  Serious Sam: The First Encounter                   #"
echo "#  (46)  Seven Kingdoms: Ancient Adversaries                #"
echo "#  (47)  Soldier of Fortune                                 #"
echo "#  (48)  Soldier of Fortune 2                               #"
echo "#  (49)  Star Trek: Voyager - Elite Force (Holomatch)       #"
echo "#  (50)  Star Trek: Elite Force II                          #"
echo "#  (51)  Star Wars: Jedi Knight - Jedi Academy              #"
echo "#  (52)  Star Wars: Jedi Knight II                          #"
echo "#  (53)  Star Wars: Republic Commando                       #"
echo "#  (54)  Stardew Valley                                     #"
echo "#  (55)  Supreme Commander (+ Forged Alliance)              #"
echo "#  (56)  SWAT 4 (+ The Stetchkov Syndicate)                 #"
echo "#  (57)  The Settlers II: 10th Anniversary                  #"
echo "#  (58)  The Wheel of Time                                  #"
echo "#  (59)  Tom Clancy's Ghost Recon                           #"
echo "#  (60)  Turok 2: Seeds of Evil (Remastered)                #"
echo "#  (61)  Tzar: The Burden of the Crown                      #"
echo "#  (62)  Unreal / Unreal Tournament '99 / 2004              #"
echo "#  (63)  War for the Overworld                              #"
echo "#  (64)  Warhammer 40,000: Fire Warrior                     #"
echo "#  (65)  Warhammer 40,000: Gladius - Relics of War          #"
echo "#  (66)  Warzone 2100                                       #"
echo "#  (67)  Windward                                           #"
echo "#  (68)  Wolfenstein: Enemy Territory                       #"
echo "#  (69)  World in Conflict (+ Soviet Assault)               #"
echo "#  (70)  Worms Armageddon                                   #"
echo "#                                                           #"
echo "#############################################################"
echo ""
read -p ">>> Pick a game for Direct IP play or press ENTER: " GAME

case $GAME in
    1)
        # Age of Mythology (+ The Titans)
        GAME_PROTOCOL="UDP"
        UDP_PORT="2299"
        ;;
    2)
        # Anno 1701 (+ The Sunken Dragon)
        GAME_PROTOCOL="UDP"
        UDP_PORT="21701"
        ;;
    3)
        # ARMA: Cold War Assault / ARMA / ARMA 2 (& Addons)
        GAME_PROTOCOL="UDP"
        UDP_PORT="2302"
        ;;
    4)
        # Baldur's Gate / II - Enhanced Edition
        GAME_PROTOCOL="UDP"
        UDP_PORT="47630"
        ;;
    5)
        # Celtic Kings: Rage of War
        GAME_PROTOCOL="BOTH"
        TCP_PORT="40445"
        UDP_PORT="40444"
        ;;
    6)
        # Civilization IV (& Addons)
        GAME_PROTOCOL="UDP"
        UDP_PORT="2056"
        ;;
    7)
        # Codename: Panzers - Phase One / Two
        GAME_PROTOCOL="UDP"
        UDP_PORT="5555"
        ;;
    8)
        # Daikatana
        GAME_PROTOCOL="UDP"
        UDP_PORT="27992"
        ;;
    9)
        # Deus Ex
        GAME_PROTOCOL="UDP"
        UDP_PORT="7790"
        ;;
    10)
        # Divinity Original Sin - Enhanced Edition
        GAME_PROTOCOL="UDP"
        UDP_PORT="23253"
        ;;
    11)
        # Doom 3 (+ BFG Edition)
        GAME_PROTOCOL="UDP"
        UDP_PORT="27666"
        ;;
    12)
        # Empire Earth II / III
        GAME_PROTOCOL="UDP"
        UDP_PORT="26000"
        ;;
    13)
        # Empires: Dawn of the Modern World
        GAME_PROTOCOL="BOTH"
        TCP_PORT="33335"
        UDP_PORT="33321"
        ;;
    14)
        # Etherlords
        GAME_PROTOCOL="UDP"
        UDP_PORT="9999"
        ;;
    15)
        # Etherlords II
        GAME_PROTOCOL="UDP"
        UDP_PORT="9990"
        ;;
    16)
        # Factorio
        GAME_PROTOCOL="UDP"
        UDP_PORT="34197"
        ;;
    17)
        # Haegemonia: Legions of Iron
        GAME_PROTOCOL="UDP"
        UDP_PORT="19664"
        ;;
    18)
        # Haegemonia: The Solon Heritage 
        GAME_PROTOCOL="BOTH"
        TCP_PORT="53324"
        UDP_PORT="19664"
        ;;
    19)
        # Hammerwatch
        GAME_PROTOCOL="UDP"
        UDP_PORT="9995"
        ;;
    20)
        # Icewind Dale - Enhanced Edition
        GAME_PROTOCOL="UDP"
        UDP_PORT="47630"
        ;;
    21)
        # Iron Storm
        GAME_PROTOCOL="BOTH"
        TCP_PORT="3504"
        UDP_PORT="3504"
        ;;
    22)
        # I.G.I.-2: Covert Strike 
        GAME_PROTOCOL="UDP"
        UDP_PORT="26001"
        ;;
    23)
        # Jazz Jackrabbit 2 (& Plus / JJ2+)
        GAME_PROTOCOL="BOTH"
        TCP_PORT="10052"
        UDP_PORT="10052"
        ;;
    24)
        # Kingpin: Life of Crime
        GAME_PROTOCOL="UDP"
        UDP_PORT="31510"
        ;;
    25)
        # Kohan: Immortal Sovereigns / Ahriman's Gift
        GAME_PROTOCOL="UDP"
        UDP_PORT="17437"
        ;;
    26)
        # Kohan II: Kings of War
        GAME_PROTOCOL="UDP"
        UDP_PORT="5860"
        ;;
    27)
        # Master of Orion 3
        GAME_PROTOCOL="TCP"
        TCP_PORT="25711"
        ;;
    28)
        # Medal of Honor: Allied Assault (& Addons)
        GAME_PROTOCOL="UDP"
        UDP_PORT="12203"
        ;;
    29)
        # Mobile Forces
        GAME_PROTOCOL="UDP"
        UDP_PORT="7777"
        ;;
    30)
        # Neverwinter Nights - Enhanced Edition
        GAME_PROTOCOL="UDP"
        UDP_PORT="5121"
        ;;
    31)
        # OpenTTD
        GAME_PROTOCOL="TCP"
        TCP_PORT="3979"
        ;;
    32)
        # Painkiller (+ Black Edition)
        GAME_PROTOCOL="UDP"
        UDP_PORT="3455"
        ;;
    33)
        # Painkiller: Overdose
        GAME_PROTOCOL="UDP"
        UDP_PORT="4974"
        ;;
    34)
        # Pandora: First Contact (+ Eclipse of Nashira)
        GAME_PROTOCOL="TCP"
        TCP_PORT="6121"
        ;;
    35)
        # Patrician 3
        GAME_PROTOCOL="TCP"
        TCP_PORT="36936"
        ;;
    36)
        # Quake II (+ The Reckoning / Ground Zero) 
        GAME_PROTOCOL="UDP"
        UDP_PORT="27910"
        ;;
    37)
        # Quake III Arena (+ Team Arena)
        GAME_PROTOCOL="UDP"
        UDP_PORT="27960"
        ;;
    38)
        # Quake 4
        GAME_PROTOCOL="UDP"
        UDP_PORT="28004"
        ;;
    39)
        # Red Faction
        GAME_PROTOCOL="UDP"
        UDP_PORT="7755"
        ;;
    40)
        # Return to Castle Wolfenstein
        GAME_PROTOCOL="UDP"
        UDP_PORT="27960"
        ;;
    41)
        # Rune Gold / Classic
        GAME_PROTOCOL="UDP"
        UDP_PORT="7777"
        ;;
    42)
        # Scrapland (Remastered)
        GAME_PROTOCOL="UDP"
        UDP_PORT="28086"
        ;;
    43)
        # SiN (+ Wages of Sin)
        GAME_PROTOCOL="UDP"
        UDP_PORT="27015"
        ;;
    44)
        # Sins of a Solar Empire: Rebellion
        GAME_PROTOCOL="TCP"
        TCP_PORT="6112"
        ;;
    45)
        # Serious Sam: The First Encounter
        GAME_PROTOCOL="BOTH"
        TCP_PORT="25600"
        UDP_PORT="25600"
        ;;
    46)
        # Seven Kingdoms: Ancient Adversaries
        GAME_PROTOCOL="UDP"
        UDP_PORT="19255"
        ;;
    47)
        # Soldier of Fortune
        GAME_PROTOCOL="UDP"
        UDP_PORT="28910"
        ;;
    48)
        # Soldier of Fortune 2
        GAME_PROTOCOL="UDP"
        UDP_PORT="20100"
        ;;
    49)
        # Star Trek: Voyager - Elite Force (Holomatch)
        GAME_PROTOCOL="UDP"
        UDP_PORT="27960"
        ;;
    50)
        # Star Trek: Elite Force II
        GAME_PROTOCOL="UDP"
        UDP_PORT="29253"
        ;;
    51)
        # Star Wars: Jedi Knight - Jedi Academy
        GAME_PROTOCOL="UDP"
        UDP_PORT="29070"
        ;;
    52)
        # Star Wars: Jedi Knight II
        GAME_PROTOCOL="UDP"
        UDP_PORT="28070"
        ;;
    53)
        # Star Wars: Republic Commando
        GAME_PROTOCOL="UDP"
        UDP_PORT="7777"
        ;;
    54)
        # Stardew Valley
        GAME_PROTOCOL="UDP"
        UDP_PORT="24642"
        ;;
    55)
        # Supreme Commander (+ Forged Alliance)
        GAME_PROTOCOL="UDP"
        UDP_PORT="16010"
        ;;
    56)
        # SWAT 4 (+ The Stetchkov Syndicate)
        GAME_PROTOCOL="UDP"
        UDP_PORT="10480"
        ;;
    57)
        # The Settlers II: 10th Anniversary
        GAME_PROTOCOL="TCP"
        UDP_PORT="5479"
        ;;
    58)
        # The Wheel of Time
        GAME_PROTOCOL="UDP"
        UDP_PORT="7777"
        ;;
    59)
        # Tom Clancy's Ghost Recon
        GAME_PROTOCOL="TCP"
        TCP_PORT="2346"
        ;;
    60)
        # Turok 2: Seeds of Evil (Remastered)
        GAME_PROTOCOL="UDP"
        UDP_PORT="5029"
        ;;
    61)
        # Tzar: The Burden of the Crown
        GAME_PROTOCOL="BOTH"
        TCP_PORT="40445"
        UDP_PORT="40444"
        ;;
    62)
        # Unreal / Unreal Tournament '99 / 2004
        GAME_PROTOCOL="UDP"
        UDP_PORT="7777"
        ;;
    63)
        # War for the Overworld
        GAME_PROTOCOL="UDP"
        UDP_PORT="27015"
        ;;
    64)
        # Warhammer 40,000: Fire Warrior
        GAME_PROTOCOL="UDP"
        UDP_PORT="3658"
        ;;
    65)
        # Warhammer 40,000: Gladius - Relics of War
        GAME_PROTOCOL="TCP"
        TCP_PORT="6120"
        ;;
    66)
        # Warzone 2100
        GAME_PROTOCOL="TCP"
        TCP_PORT="2100"
        ;;
    67)
        # Windward
        GAME_PROTOCOL="TCP"
        TCP_PORT="5127"
        ;;
    68)
        # Wolfenstein: Enemy Territory
        GAME_PROTOCOL="UDP"
        UDP_PORT="27960"
        ;;
    69)
        # World in Conflict (+ Soviet Assault)
        GAME_PROTOCOL="TCP"
        TCP_PORT="48000"
        ;;
    70)
        # Worms Armageddon
        GAME_PROTOCOL="TCP"
        TCP_PORT="17011"
        ;;
    *)
        read -p ">>> Select forwarding protcol (TCP, UDP or BOTH): " GAME_PROTOCOL
        
        case ${GAME_PROTOCOL^^} in
            TCP)
                read -p ">>> Select TCP forwarding port: " TCP_PORT
                ;;
            UDP)
                read -p ">>> Select UDP forwarding port: " UDP_PORT
                ;;
            BOTH)
                read -p ">>> Select TCP forwarding port: " TCP_PORT
                read -p ">>> Select UDP forwarding port: " UDP_PORT
                ;;
            *)
                echo ">>> Invalid protocol selection!"
                exit 3
                ;;
        esac
        
        if [ ! -z "$TCP_PORT" ]
        then
            if ! [[ "$TCP_PORT" =~ ^[0-9]+$ ]] || [ "$TCP_PORT" -lt 1024 -o "$TCP_PORT" -gt 65535 ]
            then
                echo ">>> Invalid TCP port selection!"
                exit 4
            fi
        fi

        if [ ! -z "$UDP_PORT" ]
        then
            if ! [[ "$UDP_PORT" =~ ^[0-9]+$ ]] || [ "$UDP_PORT" -lt 1024 -o "$UDP_PORT" -gt 65535 ]
            then
                echo ">>> Invalid UDP port selection!"
                exit 5
            fi
        fi

        ;;
esac

case ${GAME_PROTOCOL^^} in
    TCP)
        # forward/tunnel ports through SSH based on the selected option
        echo -e ">>> Setting up TCP relaying on port(s): "$BOLD$TCP_PORT$DEFAULT
        start_tcp_forwarding $TCP_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_tcp_forwarding $TCP_PORT
        ;;
    UDP)
        # relay port traffic using the Wookiee Unicaster based on the selected option 
        echo -e ">>> Setting up UDP relaying on port(s): "$BOLD$UDP_PORT$DEFAULT
        start_udp_forwarding $UDP_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_udp_forwarding $UDP_PORT
        ;;
    BOTH)
        echo -e ">>> Setting up TCP relaying on port(s): "$BOLD$TCP_PORT$DEFAULT
        start_tcp_forwarding $TCP_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -e $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        echo -e ">>> Setting up UDP relaying on port(s): "$BOLD$UDP_PORT$DEFAULT
        start_udp_forwarding $UDP_PORT
        echo -en ">>> "$GREEN"DONE"$DEFAULT". "
        echo -en $BLINK"!!! Press any key to terminate !!!"$DEFAULT
        read
        stop_tcp_forwarding $TCP_PORT
        stop_udp_forwarding $UDP_PORT
        ;;
    *)
        echo ">>> Invalid protocol selection!"
        exit 3
        ;;
esac

echo ">>> Port forwarding connections have been severed."

