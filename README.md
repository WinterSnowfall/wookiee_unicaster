# The Wookiee Unicaster

A UDP packet forwarding script for **Linux**, written in **Python 3**, which enables UDP routing and NAT punch-through using a public IP relay server. This is particularly useful for playing some LAN/Direct IP games over the internet.

The Wookie Unicaster comes with a server mode that must run on the relay system (public IP), and a client mode, which must be run on the system hosting the game server. Any number of remote peers can connect to the game server once the Wookiee Unicaster client/server link is set up properly. Duplex traffic is automatically handled and forwarded using a high-performance multi-process worker queue model.

### Does it have any requirements?

Run it on a potato. Profiling has shown that ~98% of its execution time will be spent on waiting (aka idling) to receive UDP packets.

Also ensure port **23000** is open on both the server and the client, since it will be used for UDP packet relaying and NAT punch-through. Port **24000** also needs to be unused/available on the client (there's no requirement for it to be open, since it will only be used to locally relay traffic to the end destination).

Why is there only a single relay port, since UDP is stateless? Well, because as of now only one remote peer is supported. I plan to add support for multiple peers in the near future (using multiple input and relay ports).

### Say what? Which games support Direct IP connections through UDP?

I've developed Wookie Unicaster primarily for Supreme Commander, but there are other games our there that may benefit from it.

Here's a non-exhaustive (and rather limited) list of games I've tested and are known to work:
* Supreme Commander
* Supreme Commander - Forged Alliance
* Divinity Original Sin - Enhanced Edition

### How do I get access to a public IP? It's not like they grow on trees, you know...

Any IaaS vendor out there will typically provide a public IP for your Linux IaaS instance. Just pick whatever fits your needs and is cheapest. I'm using an Ubuntu "nanode" from [Linode](https://www.linode.com/).

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

**Note:** The Wookie Unicaster needs to run on both the relay server (in server mode) and the game server (client mode). Remote peers need only know the relay server's IP and host port to connect.

### How does it work?

It's written for Linux, so you'll need a **Linux OS** with **python 3.6+** installed on the machine you plan to run it on (at least in theory, I can't and won't test this on Windows, but it **MAY** work). Since I've only used the standard sockets library, no external/additional packets are required.

You can run **./wookiee_unicaster.py -h** to get some hints, but in short, you'll need to specify:

* -m <mode> = enables "server" or "client" mode
* -e <interface> = the name of the network interface (as listed by ifconfig) on which the script will listen for perform the relaying of UDP packets
* -s <sourceip> = source IP address - only needed in client mode, where it represents the relay server's public IP
* -d <destip> = destination IP address - only needed in client mode, where is represents the end IP of the game server
* -i <iport> = port on which the server will listen for incoming UDP packets from remote peers - only needed in server mode, and it will typically be the port that the game server uses for listening to incoming connections
* -o <oport> = end relay port - only needed in client mode, where it represents the port that the game server is using to listen for incoming connections

To give you an example, you can run the following command on the server (216.58.212.164):

```
./wookiee_unicaster.py -m server -e eth0 -i 16010 > /dev/null 2>&1 &
```

Followed by the following command on the client (10.0.0.1):

```
./wookiee_unicaster.py -m client -e enp1s0 -s 216.58.212.164 -d 10.0.0.1 -o 16010 > /dev/null 2>&1 &
```

in order to start a background process which will replicate UDP packets received by the server on port 16010 onto the 16010 port on the game server (10.0.0.1). Replies will be automatically forwarded back to the source on the same link.

**Note:** the client can actually be run on a different host, not the computer where the game server is running, however that other host will need to be in the same LAN as the game server and UDP traffic must flow freely between them. Note that this may add to the overall link latency, and is generally not recommended (although entirely possible).

