﻿# The Wookiee Unicaster

A UDP packet forwarding script, written in **Python 3**, which enables UDP routing and NAT punch-through using a public IP relay server. This is particularly useful for playing some LAN/Direct IP games over the internet.

The Wookiee Unicaster comes with a server mode that must run on the relay system (public IP), and a client mode, which must be run on the system hosting the game server. Any number of remote peers can connect to the game server once the Wookiee Unicaster client/server link is set up properly. Duplex traffic is automatically handled and forwarded using a high-performance multi-process worker queue model.

### Say what? Which games support Direct IP connections through UDP?

I've developed Wookiee Unicaster primarily for Supreme Commander, but there are other games out there that may benefit from it.

Here's a non-exhaustive list of games I've tested myself and are known to work:
* Age of Mythology (+ The Titans)
* Anno 1701 (+ The Sunken Dragon)
* ARMA: Cold War Assault (Operation Flashpoint)
* ARMA: Armed Assault (+ Queen's Gambit)
* ARMA 2 (& Addons)
* Baldur's Gate - Enhanced Edition
* Baldur's Gate II - Enhanced Edition
* Celtic Kings: Rage of War
* Civilization IV (& Addons, including "Colonization")
* Codename: Panzers - Phase One / Two
* Daikatana
* Deus Ex
* Divinity Original Sin - Enhanced Edition
* Doom 3
* Empire Earth II
* Empire Earth III
* Empires: Dawn of the Modern World
* Etherlords
* Etherlords II
* Factorio
* Haegemonia: Legions of Iron
* Haegemonia: The Solon Heritage
* Hammerwatch
* Icewind Dale - Enhanced Edition
* Iron Storm
* I.G.I.-2: Covert Strike
* Jazz Jackrabbit 2 (& Plus / JJ2+)
* Kingpin: Life of Crime
* Kohan: Immortal Sovereigns / Ahriman's Gift
* Kohan II: Kings of War
* Medal of Honor: Allied Assault (& Addons)
* Mobile Forces
* Neverwinter Nights - Enhanced Edition
* Painkiller (+ Black Edition)
* Painkiller: Overdose
* Quake II (+ The Reckoning / Ground Zero)
* Quake III Arena (+ Team Arena)
* Quake 4
* Red Faction
* Return to Castle Wolfenstein
* Rune Gold / Classic
* Scrapland (Remastered)
* SiN (+ Wages of Sin)
* Serious Sam: The First Encounter
* Seven Kingdoms: Ancient Adversaries
* Soldier of Fortune
* Soldier of Fortune 2
* Star Trek: Voyager - Elite Force (Holomatch)
* Star Trek: Elite Force II
* Star Wars: Jedi Knight - Jedi Academy
* Star Wars: Jedi Knight II
* Star Wars: Republic Commando
* Stardew Valley
* Supreme Commander (+ Forged Alliance)
* SWAT 4 (+ The Stetchkov Syndicate)
* The Wheel of Time
* Turok 2: Seeds of Evil (Remastered)
* Tzar: The Burden of the Crown
* Unreal (+ Return to Na Pali)
* Unreal Tournament '99
* Unreal Tournament 2004
* War for the Overworld
* Warhammer 40,000: Fire Warrior
* Wolfenstein: Enemy Territory

### UDP traffic over the internet? Is that... safe?

Not really. Use it at your own risk. Most games will not encrypt their UDP traffic, so you'll be running cleartext exchanges over the internet as if it were your LAN. Mind you this is just game data, so nothing all that critical, but especially older DirectPlay-based games are not to be considered examples of good network security practices. In essence it's not more unsafe than any other form of unencrypted traffic over the internet (including Direct IP UDP multiplayer without using the Wookiee Unicaster, assuming the game host has an ISP-provided public IP already), although some of the ancient game code that's out there can potentially be exploited to get nasty stuff onto your system even if you are behind a firewall.

Since the Wookiee Unicaster only handles end-to-end traffic between the relay server and the game server, it can't offer a solution to this problem, like a VPN can, even if it were to encrypt the traffic it is relaying. If you are deeply worried about security, it's probably best to stick with a VPN, which typically encrypts all traffic going over its interfaces, even if the games you are using it for do not.

That being said, will your system get hacked into if you occasionally play an Anno 1701 match over the internet with the Wookiee Unicaster (or even without it)? Probably not. But caveat emptor, since I have no desire or interest to sugar coat the situation and everyone should be aware of the risks.

### Does it have any requirements?

Run it on a potato. Profiling has shown that ~98% of its execution time will be spent on waiting (aka idling) to receive UDP packets.

Also ensure ports starting from **23601** and above are open on both the server and the client, since they will be used for UDP packet relaying and NAT punch-through (incremental port numbers will be used for multiple remote peers: 23602 will be used as well when configuring 2 remote peers, 23603 as well for 3 peers etc). Ports in the **23801+** range also need to be unused/available on the client (there's no requirement for them to be open, since they will only be used as points of origin to locally relay traffic onto the end destination).

### Does it work on Windows?

Yes. Windows is officially supported in client mode and I've briefly tested it to confirm everything works as expected. Server mode should also work on Windows, but isn't officially supported. Performance is expected to be better on Linux in both cases, so you'll have to "pick your poison" if you're not a friend of ol' Tux (either become friends or trudge through the molasses of Windows). The neat little bash setup script I've provided as an example also won't ever work on Windows, so you'll have to configure things manually if you insist on going down this route.

I strongly recommend the use of [WinPython](https://winpython.github.io/) if you're planning to run the Wookiee Unicaster in client mode directly on Windows, but the official CPython installer/environment may work as well.

**Note:** Remember that you'll have to use **CTRL + BREAK** in order to terminate the script (instead of **CTRL + C** on Linux).

### What about macOS?

What about it? I expect the Wookiee Unicaster to work on macOS as well, but your mileage may vary. I won't be able to test it or officially support it.

### Does every UDP-based Direct IP multiplayer game out there work?

In theory, yes, however there are some limitations. Some games require a direct line of sight between all peers joining a game (i.e. fully connected mesh topology) and will not work with more than one remote peer in this case. Sadly, you will still need to use a VPN for anything other than 1 vs 1 matches in those games. Other games that structure their multiplayer code on a client-server model (i.e. hub-and-spoke topology) will work with the maximum number of possible players, as advertised by the game.

To be more specific, based on the game list above, here is how things stand:

| Game Title | Maximum Number Of Players | Peer LOS Limitation | UDP Only | Comments |
| --- | :-: | :-: | :-: | --- |
| Age of Mythology (+ The Titans) | **12 players** | 🟢 | ✔ | |
| Anno 1701 (+The Sunken Dragon) | **4 players** | 🟢 | ✔ | |
| ARMA: Cold War Assault (Operation Flashpoint) | **16 players** | 🟢 | ✔ | |
| ARMA: Armed Assault (+ Queen's Gambit) | **60+ players** (in theory) | 🟡 | ✔ | The game checks the uniqueness of CD-keys even for LAN play (was unable to test the LOS limitation) |
| ARMA 2 (& Addons) | **60+ players** (in theory) | 🟡 | ✔ | The game checks the uniqueness of CD-keys even for LAN play (was unable to test the LOS limitation) |
| Baldur's Gate - Enhanced Edition | **6 players** | 🟢 | ✔ | |
| Baldur's Gate II - Enhanced Edition | **6 players** | 🟢 | ✔ | |
| Celtic Kings: Rage of War | **8 players** | 🟢 | ✘ | |
| Civilization IV (& Addons, including "Colonization") | **2 players** | 🔴 | ✔ | Multiple remote peers can attempt to join the lobby, but no more than one remote peer can connect properly due to the lack of inter-peer connectivity |
| Codename: Panzers - Phase One / Two | **8 players** | 🟢 | ✔ | |
| Daikatana | **32 players** | 🟢 | ✔ | |
| Deus Ex | **16 players** | 🟢 | ✔ | |
| Divinity Original Sin - Enhanced Edition | **2 players** | 🟢 | ✔ | The game only supports a maximum of 2 players |
| Doom 3 | **4 players** | 🟢 | ✔ | |
| Empire Earth II | **10 players** (in theory) | 🟡 | ✔ | The game checks the uniqueness of CD-keys even for LAN play (was unable to test the LOS limitation) |
| Empire Earth III | **8 players** (in theory) | 🟡 | ✔ | The game checks the uniqueness of CD-keys even for LAN play (was unable to test the LOS limitation) |
| Empires: Dawn of the Modern World | **8 players** (in theory) | 🟡 | ✘ | The game checks the uniqueness of CD-keys even for LAN play (was unable to test the LOS limitation) |
| Etherlords | **2 players** | 🔴 | ✔ | Only one remote peer can connect to the lobby, due to the lack of inter-peer connectivity (applies to "Strategy" games, since "Duel" only accepts a maximum of two players by design) |
| Etherlords II | **2 players** | 🟢 | ✔ | The game only supports a maximum of two players in "Duel" mode |
| Factorio | **"Unlimited" players** | 🟢 | ✔ | Hard limited to 65535 players in theory, but please don't use the Wookiee Unicaster for more than **32** or so |
| Hammerwatch | **4 players** | 🟢 | ✔ | The player limit imposed by the game can allegedly be increased through hacks |
| Haegemonia: Legions of Iron | **8 players** | 🟢 | ✔ | Manually enter the <public_ip> then press "Join Game" |
| Haegemonia: The Solon Heritage | **8 players** | 🟢 | ✘ (Uses TCP for map upload) | Manually enter the <public_ip> then press "Join Game" |
| Hammerwatch | **4 players** | 🟢 | ✔ | The player limit imposed by the game can allegedly be increased through hacks |
| Icewind Dale - Enhanced Edition | **6 players** | 🟢 | ✔ | |
| Iron Storm | **16 players** | 🟢 | ✘ | |
| I.G.I.-2: Covert Strike | **16 players** (in theory) | 🟡 | ✔ | The games enforces broken CD authentication checks on remote peer joins even for LAN play (was unable to test the LOS limitation) |
| Jazz Jackrabbit 2 (& Plus / JJ2+) | **8 players** | 🟢 | ✘ | Up to 4 players can play in splitscreen on a single peer, for a total of **32** players |
| Kingpin: Life of Crime | **16 players** | 🟢 | ✔ | Enter the <public_ip> in the address book and then refresh the server list |
| Kohan: Immortal Sovereigns / Ahriman's Gift | **8 players** | 🟢 | ✔ | |
| Kohan II: Kings of War | **12 players** | 🟢 | ✔ | |
| Medal of Honor: Allied Assault (& Addons) | **32 players** | 🟢 | ✔ | |
| Mobile Forces | **16 players** | 🟢 | ✔ | |
| Neverwinter Nights - Enhanced Edition | **6 players** (in theory) | 🟡 | ✔ | Multiplayer is protected by a CD-key check and multiple peers with the same key aren't allowed on a server (was unable to test the LOS limitation) |
| Painkiller (+ Black Edition) | **16 players** | 🟢 | ✔ | Fill in the <public_ip> under "Enter IP" to join |
| Painkiller: Overdose | **16 players** | 🟢 | ✔ | Fill in the <public_ip> under "Enter IP" to join |
| Quake II (+ The Reckoning / Ground Zero) | **16 players** | 🟢 | ✔ | Enter the <public_ip> in the address book and then refresh the server list |
| Quake III Arena (+ Team Arena) | **16 players** | 🟢 | ✔ | Use "Specify" to enter the <public_ip> |
| Quake 4 | **16 players** | 🟢 | ✔ | Use "Join IP Address" to enter the <public_ip> |
| Red Faction | **32 players** | 🟢 | ✔ | Use "Add Server" and enter <public_ip>:7755 to join |
| Return to Castle Wolfenstein | **16 players** | 🟢 | ✔ | Use "New Favorite" to enter the <public_ip>, then filter by "Source: Favorites" to join |
| Rune Gold / Classic | **16 players** | 🟢 | ✔ | Right click anywhere on the "LAN Servers" tab and use the "Open Location" option, then enter the <public_ip> to join |
| Scrapland (Remastered) | **16 players** | 🟢 | ✔ | |
| SiN (+ Wages of Sin) | **16 players** | 🟢 | ✔ | Enter the <public_ip> in the server address book and then refresh the server list |
| Serious Sam: The First Encounter| **16 players** | 🟢 | ✘ | Note that "The Second Encounter" has a different netcode which does not work properly with the Wookiee Unicaster |
| Seven Kingdoms: Ancient Adversaries | **2 players** | 🔴 | ✔ | Multiple remote peers can join the lobby, but the game won't start properly with more than one remote peer due to the lack of inter-peer connectivity |
| Soldier of Fortune | **32 players** | 🟢 | ✔ | Use "Advanced" to enter the <public_ip> under "Connect Directly to IP"  |
| Soldier of Fortune 2 | **16 players** | 🟢 | ✔ | Use "New Favorite" to enter the <public_ip>, then filter by "Source: Favorites" to join |
| Star Trek: Voyager - Elite Force (Holomatch) | **12 players** | 🟢 | ✔ | |
| Star Trek: Elite Force II | **32 players** | 🟢 | ✔ | |
| Star Wars: Jedi Knight - Jedi Academy | **16 players** | 🟢 | ✔ | Use "New Favorite" to enter the <public_ip>, then filter by "Source: Favorites" to join |
| Star Wars: Jedi Knight II | **16 players** | 🟢 | ✔ | Use "New Favorite" to enter the <public_ip>, then filter by "Source: Favorites" to join |
| Star Wars: Republic Commando | **8 players** | 🟢 | ✔ | The host must start a game using "Create Internet Game", otherwise some remote peers may be auto-kicked with key validation errors (happens with the GOG version of the game) |
| Stardew Valley | **4 players** | 🟢 | ✔ | |
| Supreme Commander (+ Forged Alliance) | **2 players** | 🔴 | ✔ | Multiple remote peers can join the lobby, but the game won't start with more than one remote peer due to the lack of inter-peer connectivity |
| SWAT 4 (+ The Stetchkov Syndicate) | **16 players** | 🟢 | ✔ | |
| The Wheel of Time | **16 players** | 🟢 | ✔ | The host will need to launch a dedicated server first. All peers, including the host, must use "Favorites", then right click anywhere on the screen, select "New Favorite", enter the <public_ip> and a description, then double click on the created item to connect (ping being shown as 9999 and players as 0/0 is irrelevant, the connection should work).  |
| Turok 2: Seeds of Evil (Remastered) | **16 players** | 🟢 | ✔ | |
| Tzar: The Burden of the Crown | **8 players** | 🟢 | ✘ | |
| Unreal (+ Return to Na Pali) | **16 players** | 🟢 | ✔ | Use the "Open Location" option with "unreal://<public_ip>:7777" for Direct IP multiplayer. OldUnreal patches are optional, but recommended. |
| Unreal Tournament '99 | **16 players** | 🟢 | ✔ | Use the "Open Location" option with "unreal://<public_ip>:7777" for Direct IP multiplayer. OldUnreal patches are optional, but recommended. |
| Unreal Tournament 2004 | **16 players** | 🟢 | ✔ | Use "Favorites", then right click in the bottom left side of the screen and select "Open IP" to enter the <public_ip> |
| War for the Overworld | **4 players** | 🟢 | ✔ | |
| Warhammer 40,000: Fire Warrior | **2 players** | 🔴 | ✔ | Only one remote player can join the lobby, due to the lack of inter-peer connectivity. Any additional remote peers that try to join will error out. |
| Wolfenstein: Enemy Territory | **64 players** | 🟢 | ✔ | Use "Connect to IP" to enter the <public_ip> |

### What about games with DirectPlay multiplayer that have Direct IP support?

So, you've noticed a distinct lack of DirectPlay games in the list above, eh? You've got a sharp eye. Testing these under Linux is nearly impossible due to nearly non-existent DirectPlay support in Wine (the directplay winetrick will make things work however, if you're inclined to use it), but on Windows I expect the Wookiee Unicaster to work quite well with any DirectPlay games relying on UDP. Just be careful when using this now ancient and very insecure network middleware to exchange data over the internet.

### What about Direct IP games that support TCP?

Such games won't need "tricks" like the Wookiee Unicaster, because you can simply sort them out by using remote port forwarding with SSH/Putty. More details here: https://phoenixnap.com/kb/ssh-port-forwarding

UDP packets can't, unfortunately, be tunneled through SSH, as SSH only provides support for TCP traffic. There's the option to encapsulate UDP in TCP and using an SSH tunnel, by leveraging **nc** or **socat**, however that has the downside of breaking UDP packet boundaries, which causes serious hitches and general wonkiness with games - I've experienced this firsthand, which is why I decided to write a UDP packet forwarding utility to preserve the high performance and low latency of native UDP. I've even tried to disable TCP's Nagle algorithm by setting the SCTP_NODELAY to 0, but that hasn't helped much. In case you want to try encapsulating for yourself, here's a nice discussion on the topic, along with examples: https://superuser.com/questions/53103/udp-traffic-through-ssh-tunnel

### Are there games that use both TCP and UDP?

Why yes - see the dreaded "UDP Only" ✘-mark on the list above. Some even intermittently switch between the two on the same port, for some reason...

Note that the Wookiee Unicaster won't support these games by itself, but a combination of TCP port forwarding with SSH/Putty and UDP relaying with the Wookiee Unicaster will cater for these situations. Yes, even for mixed traffic sent on the same port. It's the magic of protocol-specific socket bindings that will ensure packets for each protocol get routed and handled properly.

Also see the provided sample setup script for some ready-to-go recepies on how to handle this sort of madness.

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

The client can actually be run on a different host, not the computer where the game server is running, however that other host will need to be in the same LAN as the game server and UDP traffic must flow freely between them. This will add to the overall link latency, and is generally not recommended if it can be avoided.

Also, please don't use shoddy wireless networks in these situations and expect good performance - the Wookiee Unicaster can't magically sort out any slowdowns caused by suboptimal routing of Ethernet traffic, though it does employ some buffering.

### OK, but how do I get access to a public IP? It's not like they grow on trees, you know...

Any IaaS vendor out there will provide a public IP with a Linux IaaS instance. Just pick whatever fits your needs and is cheapest. I'm using an Ubuntu "Nanode" from [Linode](https://www.linode.com/).

### How does it work?

You'll need a **python 3.6+** environment on the machine you plan to run it on. Or you could use the latest release binaries I provide for convenience (building your own is also possible, as explained below). Since I've only used the standard sockets library, no external/additional dependencies are required.

You can run **./wookiee_unicaster.py -h** to get some hints, but in short, you'll need to specify:

* -m <mode> = enables "server" or "client" mode
* -e <interface> = the name of the network interface (as listed by `ip addr`) on which the script will listen to perform the relaying of UDP packets - to be used on Linux
* -l <localip> = directly specify the local IP address - this is only explicitly needed on Windows and replaces -e
* -s <sourceip> = source IP address - only needed in client mode, where it represents the relay server's public IP
* -d <destip> = destination IP address - only needed in client mode, where is represents the end IP of the game server
* -i <iport> = port on which the server will listen for incoming UDP packets from remote peers - only needed in server mode, where it will need to be set to the port that the game server uses for listening to incoming connections
* -o <oport> = end relay port - only needed in client mode, where it represents the port that the game server is using to listen for incoming connections (typically the same as <iport> on the server)

There are also a few optional command line arguments:

* -p <peers> = number of remote peers you want to relay - must be set identically on both server and client (defaults to **1** if unspecified)
* --server-relay-base-port <server_relay_base_port> = base port in the range used for packet relaying on both server and client (defaults to **23600** if unspecified)
* --client-relay-base-port <client_relay_base_port> = base port in the range used as source for endpoint relaying on the client (defaults to **23800** if unspecified)
* -q = quiet mode - suppresses all logging messages (defaults to **False** if unspecified)

**Note**: All port values must be specified in the bindable, non-protected range of **1024:65535**.

To give you an example, you can run the following command on the Linux server (216.58.212.164 in the diagram above):

```
./wookiee_unicaster.py -m server -e eth0 -i 16010 > /dev/null 2>&1 &
```

Followed by the following command on Linux the client (10.0.0.1 in the diagram above):

```
./wookiee_unicaster.py -m client -e enp1s0 -s 216.58.212.164 -d 10.0.0.1 -o 16010 > /dev/null 2>&1 &
```

in order to start a background process which will replicate UDP packets received by the server on port 16010 onto the 16010 port on the game server. Replies from the game server will be automatically forwarded back to the source on the same link. You can add **-p 3** to the above commands in order to enable support for 3 remote peers.

Similarly:
```
python wookiee_unicaster.py -m client -l 10.0.0.1 -s 216.58.212.164 -d 10.0.0.1 -o 16010
```

can be used on Windows to start a client with the same configuration as in the example provided for Linux.

### The Wookiee Unicaster handles a single port, but what if a game needs multiple ports?

For Direct IP multiplayer? That's very, very rare from what I've seen so far, but should you run across any such cases, it is now possible to start multiple instances of the Wookiee Unicaster in parallel without running into any conflicts by specifying your own (non-overlapping) **--server-relay-base-port** and **--client-relay-base-port** along with different **-i** and **-o** values for any additional ports you want to relay.

Even though peer handling and connection management will be entirely independent between concurrent instances of the Wookiee Unicaster, and therefore between multiple relayed ports used by the same game, this will not pose a problem since UDP is a stateless protocol anyway. If anything it should be faster and more reliable, at least in theory.

Please remember to specify the same number of peers (**-p**) for all instances, otherwise you will most certainly run into issues.

### Build scripts? What are those for? Isn't Python an interpreted language?

Yes, it is interpreted - you're not going crazy. The scripts use [Nuitka](https://nuitka.net/doc/user-manual.html), which optimizes then compiles Python code down to C, packing it, along with dependent libraries, in a portable executable. Based on my testing the improvements are only marginal when a small number of remote peers are involved, however it will help provide some extra performance when things get crowded. If you're aiming to shave every nanosecond off of your overall latency, then you should probably consider getting Nuitka and using either the .bat or .sh build script to generate a portable executable for your platform/architecture of choice.

Alternatively, the latest Wookiee Unicaster binaries can be downloaded from the GitHub Actions section of this repository, by selecting the most recent Wookiee Unicaster Build job (note that you need to be logged in in order to see the downloadable artifacts at the bottom of the job details page).

