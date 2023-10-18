#!/usr/bin/env python3
'''
@author: Winter Snowfall
@version: 3.00
@date: 18/10/2023
'''

import os
import sys
import socket
import struct
import logging
import multiprocessing
import argparse
import subprocess
import signal
import queue
import ipaddress
from configparser import ConfigParser
from time import sleep

# logging configuration block
LOGGER_FORMAT = '%(asctime)s %(levelname)s >>> %(message)s'
# logging level for other modules
logging.basicConfig(format=LOGGER_FORMAT, level=logging.ERROR)
logger = logging.getLogger(__name__)
# logging level defaults to INFO, but can be later modified through config file values
logger.setLevel(logging.INFO) # DEBUG, INFO, WARNING, ERROR, CRITICAL

# constants
CONF_FILE_PATH = os.path.join(os.path.dirname(sys.argv[0]), 'wookiee_unicaster.cfg')
# valid (and bindable) port range boundaries
PORTS_RANGE = (1024, 65535)
# default number of supported remote peers
REMOTE_PEERS_DEFAULT = 1
# default relay port base values, to be used if otherwise unspecified
SERVER_RELAY_BASE_PORT_DEFAULT = 23000
CLIENT_RELAY_BASE_PORT_DEFAULT = 23100
# allows processes to end gracefully when no data is sent
# or received, based on the value of a shared exit event
WOOKIEE_DEFAULT_TIMEOUT = 2 #seconds

############################ WOOKIEE MODE ############################
WOOKIEE_MODE_CLIENT = b'0'
WOOKIEE_MODE_SERVER = b'1'
# [0] = client/server, [1] = source/destination, [2] = receive/relay #
WOOKIEE_MODE_NAMES = { b'000': 'client-source-receive',
                       b'001': 'client-source-relay',
                       b'010': 'client-destination-receive',
                       b'011': 'client-destination-relay',
                       b'100': 'server-source-receive',
                       b'101': 'server-source-relay',
                       b'110': 'server-destination-receive',
                       b'111': 'server-destination-relay' }
######################################################################

def sigterm_handler(signum, frame):
    # exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster process due to SIGTERM...')
    except:
        pass

    raise SystemExit(0)

def sigint_handler(signum, frame):
    # exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster process due to SIGINT...')
    except:
        pass

    raise SystemExit(0)

class ServerHandler:

    def __init__(self, peers, server_socket, remote_peer_event_list,
                 source_queue_list, remote_peer_addr_array, remote_peer_port_array,
                 max_packet_size, source_packet_count):
        # the server will have a single source-receive queue worker process
        self.peer = 0

        self.peers = peers

        self.server_socket = server_socket
        self.remote_peer_event_list = remote_peer_event_list

        self.source_queue_list = source_queue_list

        self.remote_peer_addr_array = remote_peer_addr_array
        self.remote_peer_port_array = remote_peer_port_array

        self.max_packet_size = max_packet_size
        self.source_packet_count = source_packet_count

        logger.info(f'WU P{self.peer} >>> Initializing server handler...')

        self.child_proc_started_event = multiprocessing.Event()
        self.child_proc_started_event.clear()
        self.remote_peer_worker_exit_event = multiprocessing.Event()
        self.remote_peer_worker_exit_event.clear()

        self.wookiee_server_proc = None

    def __del__(self):
        try:
            logger.debug(f'WU P{self.peer} >>> Closing server handler socket...')
            self.server_socket.close()
            logger.debug(f'WU P{self.peer} >>> Server handler socket closed.')
        except:
            pass

    def wookiee_server_handler_start(self):
        logger.info(f'WU P{self.peer} >>> Starting Wookiee Unicaster server processes...')

        self.wookiee_server_proc = multiprocessing.Process(target=self.wookiee_server_worker,
                                                           args=(self.peer, self.peers, self.server_socket, self.remote_peer_event_list,
                                                                 self.source_queue_list, self.remote_peer_worker_exit_event,
                                                                 self.remote_peer_addr_array, self.remote_peer_port_array,
                                                                 self.max_packet_size, self.source_packet_count, self.child_proc_started_event),
                                                           daemon=True)
        self.wookiee_server_proc.start()

        logger.info(f'WU P{self.peer} >>> Started Wookiee Unicaster server processes.')

    def wookiee_server_worker(self, peer, peers, isocket, remote_peer_event_list, source_queue_list,
                              remote_peer_worker_exit_event, remote_peer_addr_array, remote_peer_port_array,
                              max_packet_size, source_packet_count, child_proc_started_event):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        # 'server-source-receive'
        wookiee_name = WOOKIEE_MODE_NAMES.get(b'100')

        logger.info(f'WU P{peer} {wookiee_name} *** Worker thread started.')

        try:
            remote_peer_queue_dict = {}
            queue_vacancy = [True] * peers

            # allow the other server processes to spin up before accepting remote peers
            child_proc_started_event.wait()

            while not remote_peer_worker_exit_event.is_set():
                try:
                    if len(remote_peer_queue_dict) > 0:
                        isocket.settimeout(SERVER_PEER_CONNECTION_TIMEOUT)
                    idata, iaddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                    #logger.debug(f'WU P{peer} {wookiee_name} *** {iaddr[0]}:{iaddr[1]} sent: {idata}')
                    if len(remote_peer_queue_dict) > 0:
                        isocket.settimeout(None)

                    logger.debug(f'WU P{peer} {wookiee_name} *** Received a packet from {iaddr[0]}:{iaddr[1]}...')
                    packet_size = len(idata)
                    logger.debug(f'WU P{peer} {wookiee_name} *** Packet size: {packet_size}')
                    # unlikely, but this is an indicator that the buffer size should be bumped,
                    # otherwise UDP packets will get truncated and hell will ensue
                    if packet_size > RECEIVE_BUFFER_SIZE:
                        logger.error(f'WU P{peer} {wookiee_name} *** Packet size of {packet_size} is greater than the receive buffer size!')

                    queue_index = remote_peer_queue_dict.get(iaddr, None)

                    try:
                        if queue_index is None:
                            logger.info(f'WU P{peer} {wookiee_name} *** Detected new remote peer: {iaddr[0]}:{iaddr[1]}')

                            # try to free up any dropped peers if there are no vacancies
                            if True not in queue_vacancy:
                                for vacate_queue_index in range(peers):
                                    if not remote_peer_event_list[vacate_queue_index].is_set():
                                        logger.debug(f'WU P{peer} {wookiee_name} *** Vacating queue {vacate_queue_index}...')
                                        # '!' (byte order) =  network/big-endian, 'L' (type) = unsigned long
                                        vaddr = (socket.inet_ntoa(struct.pack('!L', remote_peer_addr_array[vacate_queue_index])),
                                                 remote_peer_port_array[vacate_queue_index])
                                        if vaddr != (0, 0):
                                            try:
                                                del remote_peer_queue_dict[vaddr]
                                                remote_peer_addr_array[vacate_queue_index] = 0
                                                remote_peer_port_array[vacate_queue_index] = 0
                                                queue_vacancy[vacate_queue_index] = True
                                                logger.debug(f'WU P{peer} {wookiee_name} *** Queue marked as vacant.')
                                            except KeyError:
                                                logger.error(f'WU P{peer} {wookiee_name} *** Failed to vacate queue {vacate_queue_index}!')

                            # determine the lowest available queue index
                            queue_index = queue_vacancy.index(True)
                            logger.debug(f'WU P{peer} {wookiee_name} *** queue_index: {queue_index}')
                            # set the inbound address in the dictionary lookups
                            remote_peer_queue_dict.update({iaddr: queue_index})
                            # struct.unpack -> "The result is a tuple even if it contains exactly one item."
                            # '!' (byte order) =  network/big-endian, 'L' (type) = unsigned long
                            remote_peer_addr_array[queue_index] = struct.unpack('!L', socket.inet_aton(iaddr[0]))[0]
                            remote_peer_port_array[queue_index] = iaddr[1]
                            queue_vacancy[queue_index] = False
                            remote_peer_event_list[queue_index].set()

                        else:
                            if not remote_peer_event_list[queue_index].is_set():
                                logger.info(f'WU P{peer} {wookiee_name} *** Reinstated dropped peer: {iaddr[0]}:{iaddr[1]}')
                                remote_peer_event_list[queue_index].set()

                        logger.debug(f'WU P{peer} {wookiee_name} *** remote_peer_queue_dict: {remote_peer_queue_dict}')
                        if source_queue_list[queue_index].full():
                            logger.warning(f'WU P{peer} {wookiee_name} *** Packet queue has hit its capacity limit.')
                        source_queue_list[queue_index].put(idata)

                        source_packet_count.value += 1
                        if packet_size > max_packet_size.value:
                            max_packet_size.value = packet_size
                            logger.debug(f'WU P{peer} {wookiee_name} *** Max packet size now set to: {max_packet_size.value}')

                        logger.debug(f'WU P{peer} {wookiee_name} *** Packet queued for replication on queue {queue_index}...')

                    # will happen if more peers than are supported attempt to connect
                    except ValueError:
                        # simply ignore the packets received from extra peers in this case
                        logger.warning(f'WU P{peer} {wookiee_name} *** {iaddr[0]}:{iaddr[1]} tried to connect but found no vacancies.')

                except socket.timeout:
                    logger.debug(f'WU P{peer} {wookiee_name} *** Timed out while waiting to receive packet...')

                    if len(remote_peer_queue_dict) != 0:
                        logger.info(f'WU P{peer} {wookiee_name} *** Purging peer list...')
                        remote_peer_queue_dict.clear()
                        remote_peer_addr_array = [0] * peers
                        remote_peer_port_array = [0] * peers
                        queue_vacancy = [True] * peers

                # this is only raised on Windows, apparently
                except ConnectionResetError:
                    logger.warning(f'WU P{peer} {wookiee_name} *** Packet transmission was forcibly halted.')

        except SystemExit:
            pass

        logger.info(f'WU P{peer} {wookiee_name} *** Worker thread stopped.')

class RemotePeerHandler:
    # keep alive packet content (featuring bowcaster ASCII art guards)
    KEEP_ALIVE_CLIENT_PACKET = b'-=|- Hello there! -|=-'
    KEEP_ALIVE_SERVER_PACKET = b'-=|- General Kenobi! -|=-'
    KEEP_ALIVE_SERVER_HALT_PACKET = b'-=|- You are a bold one! -|=-'

    def __init__(self, peer, wookiee_mode, intf, local_ip, source_ip, destination_ip,
                 source_port, destination_port, relay_port, source_queue,
                 remote_peer_event, remote_peer_handlers_reset_queue,
                 remote_peer_addr_array, remote_peer_port_array, server_socket, max_packet_size,
                 source_packet_count, destination_packet_count):
        self.peer = peer
        self.wookiee_mode = wookiee_mode

        self.intf = intf
        self.local_ip = local_ip
        self.source_ip = source_ip
        self.destination_ip = destination_ip
        self.source_port = source_port
        self.destination_port = destination_port
        self.relay_port = relay_port

        self.source_queue = source_queue
        self.remote_peer_event = remote_peer_event
        self.remote_peer_event.clear()
        self.remote_peer_handlers_reset_queue = remote_peer_handlers_reset_queue

        self.remote_peer_addr_array = remote_peer_addr_array
        self.remote_peer_port_array = remote_peer_port_array
        self.server_socket = server_socket

        self.max_packet_size = max_packet_size
        self.source_packet_count = source_packet_count
        self.destination_packet_count = destination_packet_count

        logger.info(f'WU P{self.peer} >>> Initializing remote peer handler...')

        self.destination_queue = multiprocessing.Queue(PACKET_QUEUE_SIZE)

        self.link_event = multiprocessing.Event()
        self.link_event.clear()
        self.exit_event = multiprocessing.Event()
        self.exit_event.clear()

        self.socket_timeout = None
        self.source = None
        self.destination = None

        self.wookiee_processes = [None, None, None, None]

        logger.debug(f'WU P{self.peer} >>> source_ip: {self.source_ip}')
        logger.debug(f'WU P{self.peer} >>> destination_ip: {self.destination_ip}')
        logger.debug(f'WU P{self.peer} >>> source_port: {self.source_port}')
        logger.debug(f'WU P{self.peer} >>> destination_port: {self.destination_port}')
        logger.debug(f'WU P{self.peer} >>> relay_port: {self.relay_port}')

        self.socket_timeout = SERVER_CONNECTION_TIMEOUT if self.wookiee_mode == WOOKIEE_MODE_SERVER else CLIENT_CONNECTION_TIMEOUT

        if self.wookiee_mode == WOOKIEE_MODE_SERVER:
            self.source = self.server_socket
        else:
            self.source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                self.source.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.intf)
            except TypeError:
                logger.debug(f'WU P{self.peer} >>> Using manually specified local IP value on Linux.')
            except AttributeError:
                logger.warning(f'WU P{self.peer} >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
            except OSError:
                logger.critical(f'WU P{self.peer} >>> Interface not found or unavailable.')
                raise SystemExit(17)
            logger.debug(f'WU P{self.peer} >>> Binding source to: {self.local_ip}:{self.source_port}')
            try:
                self.source.bind((self.local_ip, self.source_port))
            except OSError:
                if self.intf is None:
                    logger.critical(f'WU P{self.peer} >>> Invalid local IP {self.local_ip} or port {self.source_port} is in use.')
                else:
                    logger.critical(f'WU P{self.peer} >>> Interface unavailable or port {self.source_port} is in use.')
                raise SystemExit(18)

        self.destination = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self.destination.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.intf)
        except TypeError:
            logger.debug(f'WU P{self.peer} >>> Using manually specified local IP value on Linux.')
        except AttributeError:
            logger.warning(f'WU P{self.peer} >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
        except OSError:
            logger.critical(f'WU P{self.peer} >>> Interface not found or unavailable.')
            raise SystemExit(19)
        logger.debug(f'WU P{self.peer} >>> Binding destination to: {self.local_ip}:{self.relay_port}')
        try:
            self.destination.bind((self.local_ip, self.relay_port))
        except OSError:
            if self.intf is None:
                logger.critical(f'WU P{self.peer} >>> Invalid local IP {self.local_ip} or port {self.relay_port} is in use.')
            else:
                logger.critical(f'WU P{self.peer} >>> Interface unavailable or port {self.relay_port} is in use.')
            raise SystemExit(20)

    def __del__(self):
        if self.wookiee_mode == WOOKIEE_MODE_CLIENT:
            try:
                logger.debug(f'WU P{self.peer} >>> Closing remote peer handler source socket...')
                self.source.close()
                logger.debug(f'WU P{self.peer} >>> Remote peer handler source socket closed.')
            except:
                pass

        try:
            logger.debug(f'WU P{self.peer} >>> Closing remote peer handler destination socket...')
            self.destination.close()
            logger.debug(f'WU P{self.peer} >>> Remote peer handler destination socket closed.')
        except:
            pass

    def wookiee_receive_worker(self, peer, wookiee_mode, isocket, iaddr,
                               socket_timeout, link_event, remote_peer_event, exit_event,
                               remote_peer_handlers_reset_queue, source_queue, destination_queue,
                               max_packet_size, source_packet_count):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        wookiee_name = WOOKIEE_MODE_NAMES.get(wookiee_mode)

        logger.info(f'WU P{peer} {wookiee_name} +++ Worker thread started.')

        try:
            # ensure no timeout is actively enforced on the socket
            isocket.settimeout(None)

            # 'client-source-receive'
            if wookiee_mode == b'000':
                ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
                if not remote_peer_event.is_set():
                    peer_connection_received = False
                    logger.info(f'WU P{peer} {wookiee_name} +++ Initiating relay connection keep alive...')

                    while not remote_peer_event.is_set():
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Sending a keep alive packet...')
                        isocket.sendto(RemotePeerHandler.KEEP_ALIVE_CLIENT_PACKET, iaddr)

                        logger.debug(f'WU P{peer} {wookiee_name} +++ Listening for a keep alive packet...')
                        isocket.settimeout(KEEP_ALIVE_PING_TIMEOUT)

                        try:
                            idata, iaddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                            #logger.debug(f'WU P{peer} {wookiee_name} +++ {iaddr[0]}:{iaddr[1]} sent: {idata}')

                            if idata == RemotePeerHandler.KEEP_ALIVE_SERVER_PACKET:
                                logger.debug(f'WU P{peer} {wookiee_name} +++ Received a keep alive packet.')

                                if not peer_connection_received:
                                    logger.info(f'WU P{peer} {wookiee_name} +++ Server connection confirmed!')
                                    peer_connection_received = True

                                sleep(KEEP_ALIVE_PING_INTERVAL)

                            elif idata == RemotePeerHandler.KEEP_ALIVE_SERVER_HALT_PACKET:
                                logger.info(f'WU P{peer} {wookiee_name} +++ Connection keep alive halted.')
                                remote_peer_event.set()

                            else:
                                logger.warning(f'WU P{peer} {wookiee_name} +++ Invalid keep alive packet content.')

                        except socket.timeout:
                            logger.debug(f'WU P{peer} {wookiee_name} +++ Timed out waiting for a reply.')

                        finally:
                            isocket.settimeout(None)

                logger.debug(f'WU P{peer} {wookiee_name} +++ Clearing link event...')
                link_event.set()
                logger.debug(f'WU P{peer} {wookiee_name} +++ Link event cleared.')
                ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################

            # '*-destination-receive'
            if wookiee_mode[1:] == b'10':
                logger.debug(f'WU P{peer} {wookiee_name} +++ Waiting for the peer connection to be established...')
                link_event.wait()
                logger.debug(f'WU P{peer} {wookiee_name} +++ Cleared by link event.')

            while not exit_event.is_set():
                try:
                    if remote_peer_event.is_set():
                        # '*-source-receive'
                        if wookiee_mode[1:] == b'00':
                            isocket.settimeout(WOOKIEE_DEFAULT_TIMEOUT)
                        else:
                            isocket.settimeout(socket_timeout)
                    idata, iaddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                    #logger.debug(f'WU P{peer} {wookiee_name} +++ {iaddr[0]}:{iaddr[1]} sent: {idata}')
                    if remote_peer_event.is_set():
                        isocket.settimeout(None)

                    if idata != RemotePeerHandler.KEEP_ALIVE_SERVER_PACKET and idata != RemotePeerHandler.KEEP_ALIVE_CLIENT_PACKET:
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Received a packet from {iaddr[0]}:{iaddr[1]}...')
                        packet_size = len(idata)
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Packet size: {packet_size}')
                        # unlikely, but this is an indicator that the buffer size should be bumped,
                        # otherwise UDP packets will get truncated (which can be bad up to very bad)
                        if packet_size > RECEIVE_BUFFER_SIZE:
                            logger.error(f'WU P{peer} {wookiee_name} +++ Packet size of {packet_size} is greater than the receive buffer size!')

                        # '*-source-receive'
                        if wookiee_mode[1:] == b'00':
                            if source_queue.full():
                                logger.warning(f'WU P{peer} {wookiee_name} +++ Packet queue has hit its capacity limit.')
                            source_queue.put(idata)

                            source_packet_count.value += 1
                            # 'client-source-receive'
                            if wookiee_mode == b'000' and packet_size > max_packet_size.value:
                                max_packet_size.value = packet_size
                                logger.debug(f'WU P{peer} {wookiee_name} +++ New max_packet_size is: {max_packet_size.value}')
                        else:
                            if destination_queue.full():
                                logger.warning(f'WU P{peer} {wookiee_name} +++ Packet queue has hit its capacity limit.')
                            destination_queue.put(idata)

                        logger.debug(f'WU P{peer} {wookiee_name} +++ Packet queued for replication...')

                    # can actually happen in case game servers keep pinging dropped clients
                    else:
                        logger.warning(f'WU P{peer} {wookiee_name} +++ Keep alive packet detected during normal operation. Resetting sockets...')
                        remote_peer_handlers_reset_queue.put(peer)
                        exit_event.set()

                except socket.timeout:
                    # '*-destination-receive'
                    if wookiee_mode[1:] == b'10' and not exit_event.is_set():
                        logger.warning(f'WU P{peer} {wookiee_name} +++ The UDP connection has timed out. Resetting sockets...')
                        remote_peer_handlers_reset_queue.put(peer)
                        exit_event.set()
                    else:
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Timed out while waiting to receive packet...')

                # this is only raised on Windows, apparently
                except ConnectionResetError:
                    logger.warning(f'WU P{peer} {wookiee_name} +++ Packet transmission was forcibly halted.')

        except SystemExit:
            pass

        try:
            logger.debug(f'WU P{peer} {wookiee_name} +++ Closing process socket instance...')
            isocket.close()
            logger.debug(f'WU P{peer} {wookiee_name} +++ Process socket instance closed.')
        except:
            pass

        logger.info(f'WU P{peer} {wookiee_name} +++ Worker thread stopped.')

    def wookiee_relay_worker(self, peer, wookiee_mode, osocket, oaddr,
                             link_event, remote_peer_event, exit_event, source_queue,
                             destination_queue, remote_peer_addr_array, remote_peer_port_array,
                             destination_packet_count):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        wookiee_name = WOOKIEE_MODE_NAMES.get(wookiee_mode)

        logger.info(f'WU P{peer} {wookiee_name} --- Worker thread started.')

        # 'server-destination-relay'
        if wookiee_mode == b'111':
            remote_peer_addr_cached = False

        try:
            # ensure no timeout is actively enforced on the socket
            osocket.settimeout(None)

            # 'server-source-relay'
            if wookiee_mode == b'101':
                ####################### UDP KEEP ALIVE LOGIC - SERVER #########################
                if not remote_peer_event.is_set():
                    peer_connection_received = False
                    logger.info(f'WU P{peer} {wookiee_name} --- Initiating relay connection keep alive...')

                    while not remote_peer_event.is_set():
                        logger.debug(f'WU P{peer} {wookiee_name} --- Listening for a keep alive packet...')
                        odata, oaddr = osocket.recvfrom(RECEIVE_BUFFER_SIZE)
                        #logger.debug(f'WU P{peer} {wookiee_name} --- {oaddr[0]}:{oaddr[1]} sent: {odata}')

                        if odata == RemotePeerHandler.KEEP_ALIVE_CLIENT_PACKET:
                            logger.debug(f'WU P{peer} {wookiee_name} --- Received a keep alive packet.')

                            if not peer_connection_received:
                                logger.info(f'WU P{peer} {wookiee_name} --- Client connection confirmed!')
                                peer_connection_received = True

                            sleep(KEEP_ALIVE_PING_INTERVAL)
                        else:
                            logger.warning(f'WU P{peer} {wookiee_name} --- Invalid keep alive packet content.')

                        if not remote_peer_event.is_set():
                            logger.debug(f'WU P{peer} {wookiee_name} --- Sending a keep alive packet...')
                            osocket.sendto(RemotePeerHandler.KEEP_ALIVE_SERVER_PACKET, oaddr)
                        else:
                            logger.debug(f'WU P{peer} {wookiee_name} --- Halting keep alive...')
                            osocket.sendto(RemotePeerHandler.KEEP_ALIVE_SERVER_HALT_PACKET, oaddr)
                            logger.info(f'WU P{peer} {wookiee_name} --- Connection keep alive halted.')

                logger.debug(f'WU P{peer} {wookiee_name} --- Clearing link event...')
                link_event.set()
                logger.debug(f'WU P{peer} {wookiee_name} --- Link event cleared.')
                ####################### UDP KEEP ALIVE LOGIC - SERVER #########################

            while not exit_event.is_set():
                # 'server-destination-relay'
                if wookiee_mode == b'111':
                    link_event.wait()
                    # cache the remote peer address value and keep using it until the worker resets
                    if not remote_peer_addr_cached:
                        oaddr = (0, 0)
                        while oaddr == (0, 0):
                            # '!' (byte order) =  network/big-endian, 'L' (type) = unsigned long
                            oaddr = (socket.inet_ntoa(struct.pack('!L', remote_peer_addr_array[peer - 1])),
                                     remote_peer_port_array[peer - 1])
                            if oaddr != (0, 0):
                                logger.info(f'WU P{peer} {wookiee_name} --- Updated peer IP address/port.')
                                remote_peer_addr_cached = True
                            else:
                                logger.debug(f'WU P{peer} {wookiee_name} --- Waiting on IP address/port update.')
                                # wait times here should be minimal due to link_event sync
                                sleep(0.05)

                try:
                    # '*-source-relay'
                    if wookiee_mode[1:] == b'01':
                        odata = source_queue.get(True, WOOKIEE_DEFAULT_TIMEOUT)
                    else:
                        odata = destination_queue.get(True, WOOKIEE_DEFAULT_TIMEOUT)

                    try:
                        logger.debug(f'WU P{peer} {wookiee_name} --- Using remote peer: {oaddr}')
                        osocket.sendto(odata, oaddr)

                        # '*-destination-relay'
                        if wookiee_mode[1:] == b'11':
                            destination_packet_count.value += 1

                        logger.debug(f'WU P{peer} {wookiee_name} --- Replicated a packet to {oaddr[0]}:{oaddr[1]}...')

                    # sometimes when a peer is dropped relay packets may still get sent its way;
                    # simply ignore/drop them on relay if that's the case
                    except TypeError:
                        logger.debug(f'WU P{peer} {wookiee_name} --- Unknown or dropped remote peer. Ignoring packet.')

                except queue.Empty:
                    logger.debug(f'WU P{peer} {wookiee_name} --- Timed out while waiting to send packet...')

        except SystemExit:
            pass

        try:
            logger.debug(f'WU P{peer} {wookiee_name} --- Closing process socket instance...')
            osocket.close()
            logger.debug(f'WU P{peer} {wookiee_name} --- Process socket instance closed.')
        except:
            pass

        logger.info(f'WU P{peer} {wookiee_name} --- Worker thread stopped.')

    def wookiee_peer_handler_start(self):
        logger.info(f'WU P{self.peer} >>> Starting Wookiee Unicaster child processes...')

        # reset all shared process events
        self.exit_event.clear()
        self.link_event.clear()
        self.remote_peer_event.clear()

        # only clients must spawn a peer count of client-source-receive processes,
        # since servers will only need one catch-all receive process
        if self.wookiee_mode == WOOKIEE_MODE_CLIENT:
            self.wookiee_processes[0] = multiprocessing.Process(target=self.wookiee_receive_worker,
                                                                  # + '-source-receive'
                                                                  args=(self.peer, self.wookiee_mode + b'00', self.source,
                                                                        (self.source_ip, self.source_port), self.socket_timeout, self.link_event, self.remote_peer_event,
                                                                        self.exit_event, self.remote_peer_handlers_reset_queue,
                                                                        self.source_queue, self.destination_queue,
                                                                        self.max_packet_size, self.source_packet_count),
                                                                  daemon=True)
            self.wookiee_processes[0].start()

        self.wookiee_processes[1] = multiprocessing.Process(target=self.wookiee_relay_worker,
                                                            # + '-source-relay'
                                                            args=(self.peer, self.wookiee_mode + b'01', self.destination,
                                                                  (self.destination_ip, self.destination_port), self.link_event, self.remote_peer_event,
                                                                  self.exit_event, self.source_queue, self.destination_queue, None, None,
                                                                  self.destination_packet_count),
                                                            daemon=True)
        self.wookiee_processes[1].start()

        self.wookiee_processes[2] = multiprocessing.Process(target=self.wookiee_receive_worker,
                                                                   # + '-destination-receive'
                                                                   args=(self.peer, self.wookiee_mode + b'10', self.destination,
                                                                         (None, None), self.socket_timeout, self.link_event, self.remote_peer_event,
                                                                         self.exit_event, self.remote_peer_handlers_reset_queue,
                                                                         self.source_queue, self.destination_queue,
                                                                         self.max_packet_size, self.source_packet_count),
                                                                   daemon=True)
        self.wookiee_processes[2].start()

        self.wookiee_processes[3] = multiprocessing.Process(target=self.wookiee_relay_worker,
                                                                 # + '-destination-relay'
                                                                 args=(self.peer, self.wookiee_mode + b'11', self.source,
                                                                       (self.source_ip, self.source_port), self.link_event, self.remote_peer_event, self.exit_event,
                                                                       self.source_queue, self.destination_queue, self.remote_peer_addr_array, self.remote_peer_port_array,
                                                                       self.destination_packet_count),
                                                                 daemon=True)
        self.wookiee_processes[3].start()

        logger.info(f'WU P{self.peer} >>> Started Wookiee Unicaster child processes.')

if __name__ == "__main__":
    # catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    # catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)

    # 'spawn' will be the default starting with Python 3.14
    # (since it is more thread-safe), but since we want to ensure
    # compatibility with Nuitka, set it to 'fork' manually
    multiprocessing.set_start_method('fork')

    configParser = ConfigParser()
    no_config_file = False

    try:
        configParser.read(CONF_FILE_PATH)
        logging_section = configParser['LOGGING']
        connection_section = configParser['CONNECTION']
        keep_alive_section = configParser['KEEP-ALIVE']
    except:
        no_config_file = True
        logging_section = None
        connection_section = None
        keep_alive_section = None

    # parsing logging parameters
    try:
        LOGGING_LEVEL = logging_section.get('logging_level').upper()

        if LOGGING_LEVEL == 'DEBUG':
            logger.setLevel(logging.DEBUG)
        elif LOGGING_LEVEL == 'WARNING':
            logger.setLevel(logging.WARNING)
        elif LOGGING_LEVEL == 'ERROR':
            logger.setLevel(logging.ERROR)
        elif LOGGING_LEVEL == 'CRITICAL':
            logger.setLevel(logging.CRITICAL)
    except:
        # will use 'INFO' by default
        pass

    # parsing connection parameters
    try:
        RECEIVE_BUFFER_SIZE = connection_section.getint('receive_buffer_size')
        logger.debug(f'WU >>> RECEIVE_BUFFER_SIZE: {RECEIVE_BUFFER_SIZE}')
    except:
        RECEIVE_BUFFER_SIZE = 2048 # bytes
    try:
        PACKET_QUEUE_SIZE = connection_section.getint('packet_queue_size')
        logger.debug(f'WU >>> PACKET_QUEUE_SIZE: {PACKET_QUEUE_SIZE}')
    except:
        PACKET_QUEUE_SIZE = 256 # packets
    try:
        CLIENT_CONNECTION_TIMEOUT = connection_section.getint('client_connection_timeout')
        logger.debug(f'WU >>> CLIENT_CONNECTION_TIMEOUT: {CLIENT_CONNECTION_TIMEOUT}')
    except:
        CLIENT_CONNECTION_TIMEOUT = 20 # seconds
    try:
        SERVER_CONNECTION_TIMEOUT = connection_section.getint('server_connection_timeout')
        logger.debug(f'WU >>> SERVER_CONNECTION_TIMEOUT: {SERVER_CONNECTION_TIMEOUT}')
    except:
        SERVER_CONNECTION_TIMEOUT = 20 # seconds
    try:
        SERVER_PEER_CONNECTION_TIMEOUT = connection_section.getint('server_peer_connection_timeout')
        logger.debug(f'WU >>> SERVER_PEER_CONNECTION_TIMEOUT: {SERVER_PEER_CONNECTION_TIMEOUT}')
    except:
        SERVER_PEER_CONNECTION_TIMEOUT = 60 # seconds

    # parsing keep alive parameters
    try:
        KEEP_ALIVE_PING_INTERVAL = keep_alive_section.getint('ping_interval')
        logger.debug(f'WU >>> KEEP_ALIVE_PING_INTERVAL: {KEEP_ALIVE_PING_INTERVAL}')
    except:
        KEEP_ALIVE_PING_INTERVAL = 1 # second
    try:
        KEEP_ALIVE_PING_TIMEOUT = keep_alive_section.getint('ping_timeout')
        logger.debug(f'WU >>> KEEP_ALIVE_PING_TIMEOUT: {KEEP_ALIVE_PING_TIMEOUT}')
    except:
        KEEP_ALIVE_PING_TIMEOUT = 2 # seconds

    parser = argparse.ArgumentParser(description=('-=|- The Wookiee Unicaster -|=- Relays UDP packets between a private host '
                                                  'and multiple remote peers by leveraging a public IP(v4) address. '
                                                  'Useful for UDP based multiplayer/LAN games enjoyed using '
                                                  'Direct IP connections over the internet.'), add_help=False)

    required = parser.add_argument_group('required arguments')
    group = required.add_mutually_exclusive_group(required=True)
    optional = parser.add_argument_group('optional arguments')

    required.add_argument('-m', '--mode', help='Can be either server or client, depending on the run location.', required=True)
    group.add_argument('-e', '--interface', help='Local ethernet interface name. Must be the public facing interface in server mode.')
    group.add_argument('-l', '--localip', help=('Local IP address. Must be a public IP address in server mode. '
                                               'Can be identical to destination IP in client mode. Only needed on Windows.'))

    optional.add_argument('-h', '--help', action='help', help='show this help message and exit')
    optional.add_argument('-p', '--peers', help='Number of remote peers. Is only useful for client-server UDP implementations.',
                          default=str(REMOTE_PEERS_DEFAULT))
    optional.add_argument('-s', '--sourceip', help='Source IP address. Only needed in client mode.')
    optional.add_argument('-d', '--destip', help='Destination IP address. Only needed in client mode.')
    optional.add_argument('-i', '--iport', help='Port on which the server will listen for incoming UDP packets from remote peers.')
    optional.add_argument('-o', '--oport', help='End relay port. Only needed in client mode.')
    optional.add_argument('--server-relay-base-port', help=('Base port in the range used for packet relaying on both server and client. '
                                                          f'Defaults to {SERVER_RELAY_BASE_PORT_DEFAULT} if unspecified.'),
                          default=str(SERVER_RELAY_BASE_PORT_DEFAULT))
    optional.add_argument('--client-relay-base-port', help=('Base port in the range used as source for endpoint relaying on the client. '
                                                          f'Defaults to {CLIENT_RELAY_BASE_PORT_DEFAULT} if unspecified.'),
                          default=str(CLIENT_RELAY_BASE_PORT_DEFAULT))
    optional.add_argument('-q', '--quiet', help='Disable all logging output.', action='store_true')

    args = parser.parse_args()

    # disable all logging in quiet mode
    if args.quiet:
        logging.disable(logging.CRITICAL)

    ########################################### INPUT VALIDATION ############################################
    if args.mode == 'client':
        wookiee_mode = WOOKIEE_MODE_CLIENT
        if args.sourceip is None:
            logger.critical('WU >>> Client mode requires setting --sourceip')
            raise SystemExit(3)
        if args.destip is None:
            logger.critical('WU >>> Client mode requires setting --destip')
            raise SystemExit(4)
        if args.oport is None:
            logger.critical('WU >>> Client mode requires setting --oport')
            raise SystemExit(5)
    elif args.mode == 'server':
        wookiee_mode = WOOKIEE_MODE_SERVER
        if args.iport is None:
            logger.critical('WU >>> Server mode requires setting --iport')
            raise SystemExit(2)
    else:
        logger.critical('WU >>> Invalid operation mode specified.')
        raise SystemExit(1)

    # use the interface name on Linux and fallback to local IP value on Windows
    if args.interface is not None:
        # the interface name will only be used in socket operations
        # and the API expects a byte sequence, not a string
        intf = bytes(args.interface, 'utf-8')
        logger.debug(f'WU >>> intf: {args.interface}')
        # determine the local_ip based on the network interface name
        local_ip_query_subprocess = subprocess.Popen(''.join(('ifconfig ', args.interface, ' | grep -w inet | awk \'{print $2}\'')),
                                                     shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        local_ip = local_ip_query_subprocess.communicate()[0].decode('utf-8').strip()

        if local_ip == '':
            logger.critical(f'Invalid interface {args.interface}. Please retry with a valid interface name.')
            raise SystemExit(6)
    else:
        intf = None

        try:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.localip)
            local_ip = args.localip
        except ValueError:
            logger.critical(f'Invalid local IP {args.localip}. Please retry with a valid IP address.')
            raise SystemExit(7)

    logger.debug(f'WU >>> Local IP address is: {local_ip}')

    try:
        # the number of remote peers (defaults to 1 if otherwise unspecified)
        peers = int(args.peers)
        logger.debug(f'WU >>> peers: {peers}')

        if peers < 1:
            logger.critical('WU >>> These are not the peers you are looking for.')
            raise SystemExit(8)

    except ValueError:
        logger.critical('WU >>> Invalid number of peers specified.')
        raise SystemExit(8)

    try:
        # the actual source_ip will be determined dynamically by the server
        if wookiee_mode == WOOKIEE_MODE_SERVER:
            source_ip = None
        else:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.sourceip)
            source_ip = args.sourceip

        logger.debug(f'WU >>> source_ip: {source_ip}')
    except ValueError:
        logger.critical(f'Invalid source IP {args.sourceip}. Please retry with a valid IP address.')
        raise SystemExit(9)

    try:
        # the destination ip will be determined dynamically by the server
        if wookiee_mode == WOOKIEE_MODE_SERVER:
            destination_ip = None
        else:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.destip)
            destination_ip = args.destip

        logger.debug(f'WU >>> destination_ip: {destination_ip}')
    except ValueError:
        logger.critical(f'Invalid destination IP {args.destip}. Please retry with a valid IP address.')
        raise SystemExit(10)

    try:
        # determine the value of the server relay port (can be passed as a parameter)
        SERVER_RELAY_BASE_PORT = int(args.server_relay_base_port)
        logger.debug(f'WU >>> SERVER_RELAY_BASE_PORT: {SERVER_RELAY_BASE_PORT}')

        if SERVER_RELAY_BASE_PORT < PORTS_RANGE[0] or SERVER_RELAY_BASE_PORT > PORTS_RANGE[1] - peers:
            logger.critical('WU >>> Invalid server relay base port specified.')
            raise SystemExit(11)
    except ValueError:
        logger.critical('WU >>> Invalid server relay base port specified.')
        raise SystemExit(11)

    try:
        # determine the value of the server relay port (can be passed as a parameter)
        CLIENT_RELAY_BASE_PORT = int(args.client_relay_base_port)
        logger.debug(f'WU >>> CLIENT_RELAY_BASE_PORT: {CLIENT_RELAY_BASE_PORT}')

        if CLIENT_RELAY_BASE_PORT < PORTS_RANGE[0] or CLIENT_RELAY_BASE_PORT > PORTS_RANGE[1] - peers:
            logger.critical('WU >>> Invalid client relay base port specified.')
            raise SystemExit(12)
    except ValueError:
        logger.critical('WU >>> Invalid client relay base port specified.')
        raise SystemExit(12)

    try:
        # the client will use the SERVER_RELAY_BASE_PORT as source
        source_port = int(args.iport) if wookiee_mode == WOOKIEE_MODE_SERVER else SERVER_RELAY_BASE_PORT
        logger.debug(f'WU >>> source_port: {source_port}')

        if source_port < PORTS_RANGE[0] or source_port > PORTS_RANGE[1]:
            logger.critical('WU >>> Invalid source port specified.')
            raise SystemExit(13)
    except ValueError:
        logger.critical('WU >>> Invalid source port specified.')
        raise SystemExit(13)

    try:
        # the server will not need a destination port (its 'destination' will be the relay port)
        destination_port = CLIENT_RELAY_BASE_PORT if wookiee_mode == WOOKIEE_MODE_SERVER else int(args.oport)
        logger.debug(f'WU >>> destination_port: {destination_port}')

        if destination_port < PORTS_RANGE[0] or destination_port > PORTS_RANGE[1]:
            logger.critical('WU >>> Invalid destination port specified.')
            raise SystemExit(14)
    except ValueError:
        logger.critical('WU >>> Invalid destination port specified.')
        raise SystemExit(14)
    #########################################################################################################

    # the relay port will be used internally for UDP packet forwarding
    relay_port = SERVER_RELAY_BASE_PORT if wookiee_mode == WOOKIEE_MODE_SERVER else CLIENT_RELAY_BASE_PORT
    logger.debug(f'WU >>> relay_port: {relay_port}')

    if wookiee_mode == WOOKIEE_MODE_SERVER:
        logger.info(f'Starting the Wookiee Unicaster in SERVER mode, listening on {local_ip}:{source_port}.')
    else:
        logger.info((f'Starting the Wookiee Unicaster in CLIENT mode, connecting to the server on {source_ip} '
                     f'and forwarding traffic to {destination_ip}:{destination_port}.'))

    if no_config_file:
        logger.info('WU >>> The Wookiee Unicaster configuration file is absent. Built-in defaults will be used.')

    #################### multiprocess shared memory ####################
    # 'I' = unsigned int
    remote_peer_port_array = multiprocessing.Array('I', [0] * peers)
    # 'L' = unsigned long
    remote_peer_addr_array = multiprocessing.Array('L', [0] * peers)
    # 'I' = unsigned int
    max_packet_size = multiprocessing.Value('I', 0)
    # 'L' = unsigned long
    source_packet_count = multiprocessing.Value('L', 0)
    # 'L' = unsigned long
    destination_packet_count = multiprocessing.Value('L', 0)
    ####################################################################

    # these two need to be shared between the server handler and remote peer handlers
    source_queue_list = [multiprocessing.Queue(PACKET_QUEUE_SIZE) for peer in range(peers)]
    remote_peer_event_list = [multiprocessing.Event() for peer in range(peers)]

    ###################### server handler process ######################
    if wookiee_mode == WOOKIEE_MODE_SERVER:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, intf)
        except TypeError:
            logger.debug(f'WU >>> Using manually specified local IP value on Linux.')
        except AttributeError:
            logger.warning('WU >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
        except OSError:
            logger.critical('WU >>> Interface not found or unavailable.')
            raise SystemExit(15)
        try:
            server_socket.bind((local_ip, source_port))
        except OSError:
            if intf is None:
                logger.critical(f'WU >>> Invalid local IP {local_ip} or port {source_port} is in use.')
            else:
                logger.critical(f'WU >>> Interface unavailable or port {source_port} is in use.')
            raise SystemExit(16)

        server_handler = ServerHandler(peers, server_socket, remote_peer_event_list,
                                       source_queue_list, remote_peer_addr_array, remote_peer_port_array,
                                       max_packet_size, source_packet_count)
        server_handler.wookiee_server_handler_start()
    else:
        server_socket = None
    ####################################################################

    ################### remote peer handler processes ##################
    remote_peer_handlers = [None] * peers
    remote_peer_handlers_reset_queue = multiprocessing.Queue(peers)

    for peer in range(peers):
        if wookiee_mode == WOOKIEE_MODE_SERVER:
            destination_port += 1
            relay_port += 1
        else:
            source_port += 1
            relay_port += 1

        remote_peer_handlers[peer] = RemotePeerHandler(peer + 1, wookiee_mode, intf, local_ip, source_ip,
                                                       destination_ip, source_port, destination_port, relay_port,
                                                       source_queue_list[peer], remote_peer_event_list[peer],
                                                       remote_peer_handlers_reset_queue, remote_peer_addr_array,
                                                       remote_peer_port_array, server_socket,
                                                       max_packet_size, source_packet_count, destination_packet_count)

        remote_peer_handlers[peer].wookiee_peer_handler_start()
    ####################################################################

    if wookiee_mode == WOOKIEE_MODE_SERVER:
        # notify the server handler process that all
        # the remote peer handlers have been started
        server_handler.child_proc_started_event.set()

    try:
        # use the main process to trigger peer handler resets when signaled
        while True:
            reset_peer = remote_peer_handlers_reset_queue.get()
            reset_peer_index = reset_peer - 1
            logger.debug(f'WU >>> Resetting remote peer handler P{reset_peer}...')
            for process in remote_peer_handlers[reset_peer_index].wookiee_processes:
                if process is not None and process.is_alive():
                    process.join()
            remote_peer_handlers[reset_peer_index].wookiee_peer_handler_start()
            logger.debug(f'WU >>> Remote peer handler P{reset_peer} has been reset.')

    except SystemExit:
        # exceptions may happen here as well due to logger syncronization mayhem on shutdown
        try:
            if wookiee_mode == WOOKIEE_MODE_SERVER:
                server_handler.remote_peer_worker_exit_event.set()
            for peer_handler in remote_peer_handlers:
                peer_handler.exit_event.set()
            logger.info('WU >>> Stopping the Wookiee Unicaster...')
        except:
            if wookiee_mode == WOOKIEE_MODE_SERVER:
                server_handler.remote_peer_worker_exit_event.set()
            for peer_handler in remote_peer_handlers:
                peer_handler.exit_event.set()

    finally:
        if wookiee_mode == WOOKIEE_MODE_SERVER:
            logger.info('WU >>> Waiting for the server handler process to complete...')

            if server_handler.wookiee_server_proc.is_alive():
                server_handler.wookiee_server_proc.join()
            # clear server handler reference to trigger the destructor
            server_handler = None

            logger.info('WU >>> The server handler process has been stopped.')

        logger.info('WU >>> Waiting for the remote peer handler threads to complete...')

        for peer in range(peers):
            for process in remote_peer_handlers[peer].wookiee_processes:
                if process is not None and process.is_alive():
                    process.join()
            # clear remote peer handler references to trigger the destructor
            remote_peer_handlers[peer] = None

        logger.info('WU >>> The remote peer handler threads have been stopped.')

        logger.info('WU >>> *********************** STATS ***********************')
        logger.info(f'WU >>> max_packet_size (inbound): {max_packet_size.value}')
        logger.info(f'WU >>> source_packet_count (inbound): {source_packet_count.value}')
        logger.info(f'WU >>> destination_packet_count (outbound): {destination_packet_count.value}')
        logger.info('WU >>> *********************** STATS ***********************')

    logger.info('WU >>> Ruow! (Goodbye)')
