# The Wookiee Unicaster

A UDP packet forwarding script for **Linux**, written in **Python 3**, which enables UDP routing and NAT punch-through using a public IP relay server. This is particularly useful for playing some LAN/Direct IP games over the internet.

The Wookiee Unicaster comes with a server mode that must run on the relay system (public IP), and a client mode, which must be run on the system hosting the game server. Any number of remote peers can connect to the game server once the Wookiee Unicaster client/server link is set up properly. Duplex traffic is automatically handled and forwarded using a high-performance multi-process worker queue model.

### Say what? Which games support Direct IP connections through UDP?

I've developed Wookiee Unicaster primarily for Supreme Commander, but there are other games out there that may benefit from it.

Here's a non-exhaustive (and rather limited) list of games I've tested and are known to work:
* Supreme Commander (+ Forged Alliance)
* Divinity Original Sin - Enhanced Edition
* Anno 1701 (+ The Sunken Dragon)
* Civilization IV (& Addons, including "Colonization")
* Quake III Arena (+ Team Arena)
* War For The Overworld
* Star Wars - Jedi Academy
* Unreal Tournament '99
* Hammerwatch

### UDP traffic over the internet? Is that... safe?

No. Use it at your own risk. Most games will not encrypt their UDP traffic, so you'll be running cleartext exchanges over the internet as if it were your LAN. Mind you this is just game data, so nothing all that critical, but especially older DirectPlay-based games are not to be considered examples of good network security practices. In essence it's not more unsafe than any other form of unencrypted traffic over the internet (including Direct IP UDP multiplayer without using the Wookiee Unicaster, assuming the game host has an ISP-provided public IP already), although some of the ancient game code that's out there can potentially be exploited to get nasty stuff onto your system even if you are behind a firewall.

Since the Wookiee Unicaster only handles end-to-end traffic between the relay server and the game server, it can't offer a solution to this problem, like a VPN can, even if it were to encrypt the traffic it is relaying. If you are deeply worried about security, it's probably best to stick with a VPN, which typically does encrypt all traffic going over its interfaces, even if the games you are using it for do not.

That being said, will your system get hacked into if you occasionally play an Anno 1701 match over the internet with the Wookiee Unicaster (or even without it)? Probably not. But caveat emptor, since I have no desire or interest to sugar coat the situation and everyone should be aware of the risks.

### Does it have any requirements?

Run it on a potato (as long as it runs Linux). Profiling has shown that ~98% of its execution time will be spent on waiting (aka idling) to receive UDP packets.

Also ensure ports starting from **23001** and above are open on both the server and the client, since they will be used for UDP packet relaying and NAT punch-through (incremental port numbers will be used for multiple remote peers: 23002 will be used as well when configuring 2 remote peers, 23003 as well for 3 peers etc). Ports in the **23101+** range also need to be unused/available on the client (there's no requirement for them to be open, since they will only be used as points of origin to locally relay traffic onto the end destination).

### Does every UDP-based Direct IP multiplayer game out there work?

In theory, yes, however there are some limitations. Some games require a direct line of sight between all peers joining a game and will not work with more than one remote peer in this case. Sadly, you will still need to use a VPN for anything other than 1 vs 1 matches in those games. Other games that structure their multiplayer code on a client-server model will work with the maximum number of possible players, as advertised by the game.

To be more specific, based on the game list above, here is how things stand:
* Supreme Commander (+ Forged Alliance) -> **2 players only** (1 remote peer limitation)
* Divinity Original Sin - Enhanced Edition -> **2 players** (the game only supports a maximum of 2 players anyway)
* Anno 1701 (+The Sunken Dragon) -> **4 players** (as advertised by the game)
* Civilization IV (& Addons, including "Colonization") -> **2 players only** (1 remote peer limitation)
* Quake III Arena (+ Team Arena) -> **16 players** (as advertised by the game)
* War For The Overworld -> **4 players** (as advertised by the game)
* Star Wars - Jedi Academy -> **16 players** (as advertised by the game)
* Unreal Tournament '99 -> **16 players** (as advertised by the game) - use the "Open Location" option with "unreal://<public_ip>:7777" for Direct IP multiplayer
* Hammerwatch -> **4 players** (as advertised by the game)

### OK, but how do I get access to a public IP? It's not like they grow on trees, you know...

Any IaaS vendor out there will typically provide a public IP for your Linux IaaS instance. Just pick whatever fits your needs and is cheapest. I'm using an Ubuntu "Nanode" from [Linode](https://www.linode.com/).

### What about Direct IP games that support TCP?

It is fortunate most games provide support for Direct IP through TCP. Those won't need tricks like the Wookiee Unicaster, because you can simply sort them out by using remote port forwarding with SSH/Putty. More details here: https://phoenixnap.com/kb/ssh-port-forwarding

UDP packets can't, unfortunately, be tunneled through SSH, as SSH only provides support for TCP traffic. There's the option to encapsulate UDP in TCP and using an SSH tunnel, by leveraging **nc** or **socat**, however that has the downside of breaking UDP packet boundaries, which causes serious hitches and general wonkiness with games - I've experienced this firsthand, which is why I decided to write a UDP packet forwarding utility to preserve the high performance and low latency of native UDP. I've even tried to disable TCP's Nagle algorithm by setting the SCTP_NODELAY to 0, but that hasn't helped much. In case you want to try it for yourself, here's a nice discussion on the topic, along with examples: https://superuser.com/questions/53103/udp-traffic-through-ssh-tunnel

### I still don't get it... can you draw it out for me?

Say no more! ASCII art away!

```
Remote Peer 1                         Relay Server                         Game Server
 ----------                         ----------------                      ------------
|          |                       |                |                    |            |
| 10.0.1.1 |-----------------------| 216.58.212.164 |--------------------|  10.0.0.1  |
|          |          -------------|                |                    |            |
 ----------           :             ----------------                      ------------
(behind NAT)          :               (Public IP)                         (behind NAT)
     .                :
     .                :
     .                :
Remote Peer N         :
 ----------           :
|          |          :
| 10.0.N.1 |-----------
|          |
 ----------
(behind NAT)
```

**Note:** The Wookiee Unicaster needs to run on both the relay server (in server mode) and the game server (client mode). Remote peers need only know the relay server's IP and host port to connect.

The client can actually be run on a different host, not the computer where the game server is running, however that other host will need to be in the same LAN as the game server and UDP traffic must flow freely between them. This will add to the overall link latency, and is generally not recommended if it can be avoided. That being said, this deployment option can be leveraged for Windows(remote peers)-to-Windows(game server) operation, assuming the client is run on a local VM or on a Linux host that resides in the same LAN as the game server.

Also, please don't use wireless networks in these situations and expect good performance - the Wookiee Unicaster can't magically sort out any slowdowns caused by suboptimal routing of Ethernet traffic, though it does employ some buffering.

### How does it work?

It's written for Linux, so you'll need a **Linux OS** with **python 3.6+** installed on the machine you plan to run it on (at least in theory, I can't and won't test this on Windows, but it **MAY** work). Since I've only used the standard sockets library, no external/additional packets are required.

You can run **./wookiee_unicaster.py -h** to get some hints, but in short, you'll need to specify:

* -m <mode> = enables "server" or "client" mode
* -p <peers> = number of remote peers you want to relay - must be set identically on both server and client
* -e <interface> = the name of the network interface (as listed by ifconfig) on which the script will listen to perform the relaying of UDP packets
* -s <sourceip> = source IP address - only needed in client mode, where it represents the relay server's public IP
* -d <destip> = destination IP address - only needed in client mode, where is represents the end IP of the game server
* -i <iport> = port on which the server will listen for incoming UDP packets from remote peers - only needed in server mode, where it will need to be set to the port that the game server uses for listening to incoming connections
* -o <oport> = end relay port - only needed in client mode, where it represents the port that the game server is using to listen for incoming connections (typically the same as <iport> on the server)

To give you an example, you can run the following command on the server (216.58.212.164 in the diagram above):

```
./wookiee_unicaster.py -m server -e eth0 -i 16010 > /dev/null 2>&1 &
```

Followed by the following command on the client (10.0.0.1 in the diagram above):

```
./wookiee_unicaster.py -m client -e enp1s0 -s 216.58.212.164 -d 10.0.0.1 -o 16010 > /dev/null 2>&1 &
```

in order to start a background process which will replicate UDP packets received by the server on port 16010 onto the 16010 port on the game server. Replies from the game server will be automatically forwarded back to the source on the same link. You can add **-p 3** to the above commands in order to enable support for 3 remote peers.

### A build script? What's that for? Isn't Python an interpreted language?

Yes, it is interpreted - you're not going crazy. The script uses [Nuitka](https://nuitka.net/doc/user-manual.html), which optimizes then compiles Python code down to C, packing it, along with dependent libraries, in a portable executable. Based on my testing the improvements are only marginal when a small number of remote peers are involved, however it will help provide some extra performance when things get crowded. If you're aiming to shave every nanosecond off of your overall latency, then you should probably consider getting Nuitka and using the build script.

