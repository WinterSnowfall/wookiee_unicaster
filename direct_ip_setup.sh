#!/bin/bash

#NOTE: this script uses ufw to automatically allow network traffic on
#all of the required ports. Please make sure ufw is installed and enabled on
#target system and that the ufw command can be run by the REMOTE_SSH_USER

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
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw allow $1,23000/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_WU_PATH -m server -e $REMOTE_INFT_NAME -i $1 >> wookiee_unicaster.log 2>&1 &" > /dev/null 2>&1
    $LOCAL_WU_PATH -m client -e $LAN_INTF_NAME -s $REMOTE_PUBLIC_IP -d $LOCAL_PRIVATE_IP -o $1 >> wookiee_unicaster.log 2>&1 &
}

stop_tcp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1/tcp" > /dev/null 2>&1
    kill $(ps -ef | grep "ssh -fNT" | grep -v grep | awk '{print $2;}') 
}

stop_udp_forwarding () {
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "$REMOTE_SSH_SUDO ufw delete allow $1,23000/udp" > /dev/null 2>&1
    ssh $REMOTE_SSH_USER@$REMOTE_PUBLIC_IP "killall wookiee_unicaster" > /dev/null 2>&1
    killall wookiee_unicaster
}

echo "*** WinterSnowfall's port fowarding setup script for Mint/Ubuntu ***"
echo ""
echo ">>> Configured remote IP : $REMOTE_PUBLIC_IP"
echo ">>> Detected local IP : $LOCAL_PRIVATE_IP"
echo ""
echo "######################################################"
echo "#                                                    #"
echo "#   (1)  Sins Of A Solar Empire - Rebellion          #"
echo "#   (2)  Warhammer 40,000 Gladius - Relics Of War    #"
echo "#   (3)  Supreme Commander (+ Forged Alliance)       #"
echo "#   (4)  Worms Armageddon                            #"
echo "#   (5)  Divinity Original Sin - Enhanced Edition    #"
echo "#                                                    #"
echo "######################################################"
echo ""
read -p ">>> Pick a game for Direct IP play: " game

# forward/tunnel ports through SSH based on the selected option
case $game in
    1)
        ### Ports: 6112 (TCP)
        echo ">>> Setting up Sins Of A Solar Empire - Rebellion..."
        start_tcp_forwarding 6112
        ;;
    2)
        ### Ports: 6120 (TCP)
        echo ">>> Setting up Warhammer 40,000 Gladius - Relics Of War..."
        start_tcp_forwarding 6120
        ;;
    3)
        ### Ports: 16010 (UDP) + 23000 (UDP) - WU relay port
        echo ">>> Setting up Supreme Commander (+ Forged Alliance)..."
        start_udp_forwarding 16010
        ;;
    4)
        ### Ports: 17011 (TCP)
        echo ">>> Setting up Worms Armageddon..."
        start_tcp_forwarding 17011      
        ;;
    5)
        ### Ports: 23253 (UDP) + 23000 (UDP) - WU relay port
        echo ">>> Setting up Divinity Original Sin - Enhanced Edition..."
        start_udp_forwarding 23253
        ;;
    *)
        echo ">>> Invalid option!"
        exit 1
        ;;
esac

echo ">>> Port forwarding has been configured."

read -p ">>> Press any key to terminate..."

case $game in
    1)
        ### Ports: 6112 (TCP)
        echo ">>> Deconfiguring Sins Of A Solar Empire - Rebellion..."
        stop_tcp_forwarding 6112
        ;;
    2)
        ### Ports: 6120 (TCP)
        echo ">>> Deconfiguring Warhammer 40,000 Gladius - Relics Of War..."
        stop_tcp_forwarding 6120
        ;;
    3)
        ### Ports: 16010 (UDP) + 23000 (UDP) - WU relay port
        echo ">>> Deconfiguring Supreme Commander (+ Forged Alliance)..."
        stop_udp_forwarding 16010
        ;;
    4)
        ### Ports: 17011 (TCP)
        echo ">>> Deconfiguring Worms Armageddon..."
        stop_tcp_forwarding 17011
        ;;
    5)
        ### Ports: 23253 (UDP) + 23000 (UDP) - WU relay port
        echo ">>> Deconfiguring Divinity Original Sin - Enhanced Edition..."
        stop_udp_forwarding 23253
        ;;
    *)
        ;;
esac

echo ">>> Port forwarding connections have been severed."

