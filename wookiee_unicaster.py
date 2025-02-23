#!/usr/bin/env python3
'''
@author: Winter Snowfall
@version: 3.12
@date: 22/10/2023
'''

import os
import sys
import socket
import struct
import logging
import multiprocessing
import argparse
import platform
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

# constants
CONF_FILE_PATH = os.path.join(os.path.dirname(sys.argv[0]), 'wookiee_unicaster.cfg')
# valid (and bindable) port range boundaries
PORTS_RANGE = (1024, 65535)
# default number of supported remote peers
REMOTE_PEERS_DEFAULT = 1
# default relay port base values, to be used if otherwise unspecified
SERVER_RELAY_BASE_PORT_DEFAULT = 23000
CLIENT_RELAY_BASE_PORT_DEFAULT = 23100

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

class WookieeConstants:
    '''Shared static and runtime constants'''
    
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

    ##################### WOOKIEE RUNTIME CONSTANTS ######################
    def __init__ (self, LOGGING_LEVEL, RECEIVE_BUFFER_SIZE, CLIENT_CONNECTION_TIMEOUT,
                  SERVER_CONNECTION_TIMEOUT, SERVER_PEER_CONNECTION_TIMEOUT,
                  KEEP_ALIVE_PING_INTERVAL, KEEP_ALIVE_PING_TIMEOUT):
        self.LOGGING_LEVEL = LOGGING_LEVEL
        self.RECEIVE_BUFFER_SIZE = RECEIVE_BUFFER_SIZE
        self.CLIENT_CONNECTION_TIMEOUT = CLIENT_CONNECTION_TIMEOUT
        self.SERVER_CONNECTION_TIMEOUT = SERVER_CONNECTION_TIMEOUT
        self.SERVER_PEER_CONNECTION_TIMEOUT = SERVER_PEER_CONNECTION_TIMEOUT
        self.KEEP_ALIVE_PING_INTERVAL = KEEP_ALIVE_PING_INTERVAL
        self.KEEP_ALIVE_PING_TIMEOUT = KEEP_ALIVE_PING_TIMEOUT
    ######################################################################

class ServerHandler:
    '''Handles inbound connections for all remote peers'''

    def __init__(self, peers, intf, local_ip, source_port,
                 remote_peer_event_list, source_queue_list,
                 remote_peer_addr_array, remote_peer_port_array,
                 max_packet_size, source_packet_count, wookiee_constants):
        # the server will have a single source-receive queue worker process
        self.peer = 0

        self.peers = peers

        self.intf = intf
        self.local_ip = local_ip
        self.source_port = source_port

        self.remote_peer_event_list = remote_peer_event_list
        self.source_queue_list = source_queue_list
        self.remote_peer_addr_array = remote_peer_addr_array
        self.remote_peer_port_array = remote_peer_port_array

        self.max_packet_size = max_packet_size
        self.source_packet_count = source_packet_count

        self.wookiee_constants = wookiee_constants

        logger.info(f'WU P{self.peer} >>> Initializing server handler...')

        ####################### SOCKET BIND VALIDATIONS #######################
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.intf)
        except TypeError:
            logger.debug(f'WU P{self.peer} >>> Using manually specified local IP value on Linux.')
        except AttributeError:
            logger.warning(f'WU P{self.peer} >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
        except OSError:
            logger.critical(f'WU P{self.peer} >>> Interface not found or unavailable.')
            raise SystemExit(15)
        try:
            self.server_socket.bind((self.local_ip, self.source_port))
        except OSError:
            if self.intf is None:
                logger.critical(f'WU P{self.peer} >>> Invalid local IP {self.local_ip} or port {self.source_port} is in use.')
            else:
                logger.critical(f'WU P{self.peer} >>> Interface unavailable or port {self.source_port} is in use.')
            raise SystemExit(16)
        #######################################################################

        self.child_proc_started_event = multiprocessing.Event()
        self.child_proc_started_event.clear()
        self.remote_peer_worker_exit_event = multiprocessing.Event()
        self.remote_peer_worker_exit_event.clear()

    def __del__(self):
        try:
            logger.debug(f'WU P{self.peer} >>> Closing server handler socket...')
            self.server_socket.close()
            logger.debug(f'WU P{self.peer} >>> Server handler socket closed.')
        except:
            pass

    def wookiee_server_handler_start(self):
        logger.debug(f'WU P{self.peer} >>> Starting server process...')

        server_handler_process = multiprocessing.Process(target=self.wookiee_server_worker,
                                                         args=(self.peer, self.peers, self.server_socket, self.remote_peer_event_list,
                                                               self.source_queue_list, self.remote_peer_worker_exit_event,
                                                               self.remote_peer_addr_array, self.remote_peer_port_array,
                                                               self.max_packet_size, self.source_packet_count,
                                                               self.child_proc_started_event, self.wookiee_constants),
                                                         daemon=True)
        server_handler_process.start()

        logger.debug(f'WU P{self.peer} >>> Started server process.')

        return server_handler_process

    def wookiee_server_worker(self, peer, peers, isocket, remote_peer_event_list, source_queue_list,
                              remote_peer_worker_exit_event, remote_peer_addr_array, remote_peer_port_array,
                              max_packet_size, source_packet_count, child_proc_started_event, wookiee_constants):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        # set the child process logging level
        logger.setLevel(wookiee_constants.LOGGING_LEVEL)

        # 'server-source-receive'
        wookiee_name = wookiee_constants.WOOKIEE_MODE_NAMES.get(b'100')

        logger.info(f'WU P{peer} {wookiee_name} *** Server worker started.')

        try:
            remote_peer_queue_dict = {}
            queue_vacancy = [True] * peers

            # allow the other server processes to spin up before accepting remote peers
            child_proc_started_event.wait()

            while not remote_peer_worker_exit_event.is_set():
                try:
                    if len(remote_peer_queue_dict) > 0:
                        isocket.settimeout(wookiee_constants.SERVER_PEER_CONNECTION_TIMEOUT)
                    idata, iaddr = isocket.recvfrom(wookiee_constants.RECEIVE_BUFFER_SIZE)
                    #logger.debug(f'WU P{peer} {wookiee_name} *** {iaddr[0]}:{iaddr[1]} sent: {idata}')
                    if len(remote_peer_queue_dict) > 0:
                        isocket.settimeout(None)

                    logger.debug(f'WU P{peer} {wookiee_name} *** Received a packet from {iaddr[0]}:{iaddr[1]}...')
                    packet_size = len(idata)
                    logger.debug(f'WU P{peer} {wookiee_name} *** Packet size: {packet_size}')
                    # unlikely, but this is an indicator that the buffer size should be bumped,
                    # otherwise UDP packets will get truncated and hell will ensue
                    if packet_size > wookiee_constants.RECEIVE_BUFFER_SIZE:
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
                            logger.error(f'WU P{peer} {wookiee_name} *** Packet queue has hit its capacity limit!')
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

        logger.info(f'WU P{peer} {wookiee_name} *** Server worker stopped.')

class RemotePeerHandler:
    '''Handles remote peer channel workers for full duplex communication'''
    
    # allows processes to end gracefully when no data is sent
    # or received, based on the value of a shared exit event
    DEFAULT_TIMEOUT = 2 #seconds
    # keep alive packet content (featuring bowcaster ASCII art guards)
    KEEP_ALIVE_PACKET = b'-=|-WU-KEEP-ALIVE-|=-'
    KEEP_ALIVE_HALT_PACKET = b'-=|-WU-HALT-KEEP-ALIVE-|=-'

    def __init__(self, peer, wookiee_mode, intf, local_ip, source_ip, destination_ip,
                 source_port, destination_port, relay_port, source_queue,
                 destination_queue, remote_peer_event, remote_peer_handlers_reset_queue,
                 remote_peer_addr_array, remote_peer_port_array, server_socket,
                 max_packet_size, source_packet_count, destination_packet_count, wookiee_constants):
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
        self.destination_queue = destination_queue
        self.remote_peer_event = remote_peer_event
        self.remote_peer_event.clear()
        self.remote_peer_handlers_reset_queue = remote_peer_handlers_reset_queue

        self.remote_peer_addr_array = remote_peer_addr_array
        self.remote_peer_port_array = remote_peer_port_array
        self.server_socket = server_socket

        self.max_packet_size = max_packet_size
        self.source_packet_count = source_packet_count
        self.destination_packet_count = destination_packet_count

        self.wookiee_constants = wookiee_constants

        logger.info(f'WU P{self.peer} >>> Initializing remote peer handler...')

        logger.debug(f'WU P{self.peer} >>> source_ip: {self.source_ip}')
        logger.debug(f'WU P{self.peer} >>> destination_ip: {self.destination_ip}')
        logger.debug(f'WU P{self.peer} >>> source_port: {self.source_port}')
        logger.debug(f'WU P{self.peer} >>> destination_port: {self.destination_port}')
        logger.debug(f'WU P{self.peer} >>> relay_port: {self.relay_port}')

        ####################### SOCKET BIND VALIDATIONS #######################
        if self.wookiee_mode == self.wookiee_constants.WOOKIEE_MODE_SERVER:
            self.socket_timeout = self.wookiee_constants.SERVER_CONNECTION_TIMEOUT
        else:
            self.socket_timeout = self.wookiee_constants.CLIENT_CONNECTION_TIMEOUT

        if self.wookiee_mode == self.wookiee_constants.WOOKIEE_MODE_SERVER:
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
        #######################################################################

        self.link_event = multiprocessing.Event()
        self.link_event.clear()
        self.exit_event = multiprocessing.Event()
        self.exit_event.clear()

    def __del__(self):
        # can't refer to the static constant here, since it might get destroyed in __main__
        # before the destructor has had a chance to clear up the affected object
        if self.wookiee_mode == self.wookiee_constants.WOOKIEE_MODE_CLIENT:
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

    def wookiee_peer_handler_start(self):
        logger.debug(f'WU P{self.peer} >>> Starting remote peer handler processes...')
        # reset all shared process events
        self.exit_event.clear()
        self.link_event.clear()
        self.remote_peer_event.clear()

        peer_handler_process_list = []

        # only clients must spawn a peer count of client-source-receive processes,
        # since servers will only need one catch-all receive process
        if self.wookiee_mode == self.wookiee_constants.WOOKIEE_MODE_CLIENT:
            peer_handler_process = multiprocessing.Process(target=self.wookiee_receive_worker,
                                                           # + '-source-receive'
                                                           args=(self.peer, self.wookiee_mode + b'00', self.source,
                                                                 (self.source_ip, self.source_port), self.socket_timeout,
                                                                 self.link_event, self.remote_peer_event,
                                                                 self.exit_event, self.remote_peer_handlers_reset_queue,
                                                                 self.source_queue, self.destination_queue,
                                                                 self.max_packet_size, self.source_packet_count,
                                                                 self.wookiee_constants),
                                                           daemon=True)
            peer_handler_process.start()
            peer_handler_process_list.append(peer_handler_process)

        peer_handler_process = multiprocessing.Process(target=self.wookiee_relay_worker,
                                                       # + '-source-relay'
                                                       args=(self.peer, self.wookiee_mode + b'01', self.destination,
                                                             (self.destination_ip, self.destination_port), self.link_event,
                                                             self.remote_peer_event, self.exit_event, self.source_queue,
                                                             self.destination_queue, None,
                                                             None, self.destination_packet_count,
                                                             self.wookiee_constants),
                                                       daemon=True)
        peer_handler_process.start()
        peer_handler_process_list.append(peer_handler_process)

        peer_handler_process = multiprocessing.Process(target=self.wookiee_receive_worker,
                                                       # + '-destination-receive'
                                                       args=(self.peer, self.wookiee_mode + b'10', self.destination,
                                                             (None, None), self.socket_timeout,
                                                             self.link_event, self.remote_peer_event,
                                                             self.exit_event, self.remote_peer_handlers_reset_queue,
                                                             self.source_queue, self.destination_queue,
                                                             self.max_packet_size, self.source_packet_count,
                                                             self.wookiee_constants),
                                                       daemon=True)
        peer_handler_process.start()
        peer_handler_process_list.append(peer_handler_process)

        peer_handler_process = multiprocessing.Process(target=self.wookiee_relay_worker,
                                                       # + '-destination-relay'
                                                       args=(self.peer, self.wookiee_mode + b'11', self.source,
                                                             (self.source_ip, self.source_port), self.link_event,
                                                             self.remote_peer_event, self.exit_event, self.source_queue,
                                                             self.destination_queue, self.remote_peer_addr_array,
                                                             self.remote_peer_port_array, self.destination_packet_count,
                                                             self.wookiee_constants),
                                                       daemon=True)
        peer_handler_process.start()
        peer_handler_process_list.append(peer_handler_process)

        logger.debug(f'WU P{self.peer} >>> Started remote peer handler processes.')

        return peer_handler_process_list

    def wookiee_receive_worker(self, peer, wookiee_mode, isocket, iaddr,
                               socket_timeout, link_event, remote_peer_event, exit_event,
                               remote_peer_handlers_reset_queue, source_queue, destination_queue,
                               max_packet_size, source_packet_count, wookiee_constants):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        # set the child process logging level
        logger.setLevel(wookiee_constants.LOGGING_LEVEL)

        wookiee_name = wookiee_constants.WOOKIEE_MODE_NAMES.get(wookiee_mode)

        logger.info(f'WU P{peer} {wookiee_name} +++ Receive worker started.')

        try:
            # ensure no timeout is actively enforced on the socket
            isocket.settimeout(None)

            # 'client-source-receive'
            if wookiee_mode == b'000':
                ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
                if not remote_peer_event.is_set():
                    peer_connection_received = False
                    logger.info(f'WU P{peer} {wookiee_name} +++ Initiating relay connection keep alive...')

                    while not remote_peer_event.is_set() and not exit_event.is_set():
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Sending a keep alive packet...')
                        isocket.sendto(RemotePeerHandler.KEEP_ALIVE_PACKET, iaddr)

                        logger.debug(f'WU P{peer} {wookiee_name} +++ Listening for a keep alive packet...')
                        isocket.settimeout(wookiee_constants.KEEP_ALIVE_PING_TIMEOUT)

                        try:
                            kadata, kaaddr = isocket.recvfrom(wookiee_constants.RECEIVE_BUFFER_SIZE)
                            #logger.debug(f'WU P{peer} {wookiee_name} +++ {kaaddr[0]}:{kaaddr[1]} sent: {kadata}')

                            if kaaddr == iaddr:
                                if kadata == RemotePeerHandler.KEEP_ALIVE_PACKET:
                                    logger.debug(f'WU P{peer} {wookiee_name} +++ Received a keep alive packet.')

                                    if not peer_connection_received:
                                        logger.info(f'WU P{peer} {wookiee_name} +++ Server connection confirmed!')
                                        peer_connection_received = True

                                    sleep(wookiee_constants.KEEP_ALIVE_PING_INTERVAL)

                                elif kadata == RemotePeerHandler.KEEP_ALIVE_HALT_PACKET:
                                    logger.info(f'WU P{peer} {wookiee_name} +++ Connection keep alive halted.')
                                    remote_peer_event.set()

                                # the server should reset sockets on the next keep alive packet trasmission
                                else:
                                    logger.warning(f'WU P{peer} {wookiee_name} +++ Invalid keep alive packet content.')
                            else:
                                logger.warning(f'WU P{peer} {wookiee_name} +++ Received a packet from an unexpected source.')

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
                            isocket.settimeout(RemotePeerHandler.DEFAULT_TIMEOUT)
                        else:
                            isocket.settimeout(socket_timeout)
                    idata, iaddr = isocket.recvfrom(wookiee_constants.RECEIVE_BUFFER_SIZE)
                    #logger.debug(f'WU P{peer} {wookiee_name} +++ {iaddr[0]}:{iaddr[1]} sent: {idata}')
                    if remote_peer_event.is_set():
                        isocket.settimeout(None)

                    if idata != RemotePeerHandler.KEEP_ALIVE_PACKET:
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Received a packet from {iaddr[0]}:{iaddr[1]}...')
                        packet_size = len(idata)
                        logger.debug(f'WU P{peer} {wookiee_name} +++ Packet size: {packet_size}')
                        # unlikely, but this is an indicator that the buffer size should be bumped,
                        # otherwise UDP packets will get truncated (which can be bad up to very bad)
                        if packet_size > wookiee_constants.RECEIVE_BUFFER_SIZE:
                            logger.error(f'WU P{peer} {wookiee_name} +++ Packet size of {packet_size} is greater than the receive buffer size!')

                        # '*-source-receive'
                        if wookiee_mode[1:] == b'00':
                            if source_queue.full():
                                logger.error(f'WU P{peer} {wookiee_name} +++ Packet queue has hit its capacity limit!')
                            source_queue.put(idata)

                            source_packet_count.value += 1
                            # 'client-source-receive'
                            if wookiee_mode == b'000' and packet_size > max_packet_size.value:
                                max_packet_size.value = packet_size
                                logger.debug(f'WU P{peer} {wookiee_name} +++ New max_packet_size is: {max_packet_size.value}')
                        else:
                            if destination_queue.full():
                                logger.error(f'WU P{peer} {wookiee_name} +++ Packet queue has hit its capacity limit!')
                            destination_queue.put(idata)

                        logger.debug(f'WU P{peer} {wookiee_name} +++ Packet queued for replication...')

                    # can actually happen in case game servers keep pinging dropped clients
                    else:
                        logger.warning(f'WU P{peer} {wookiee_name} +++ Keep alive packet detected. Resetting sockets...')
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

        logger.info(f'WU P{peer} {wookiee_name} +++ Receive worker stopped.')

    def wookiee_relay_worker(self, peer, wookiee_mode, osocket, oaddr,
                             link_event, remote_peer_event, exit_event, source_queue,
                             destination_queue, remote_peer_addr_array,
                             remote_peer_port_array, destination_packet_count,
                             wookiee_constants):
        # catch SIGTERM and exit gracefully
        signal.signal(signal.SIGTERM, sigterm_handler)
        # catch SIGINT and exit gracefully
        signal.signal(signal.SIGINT, sigint_handler)

        # set the child process logging level
        logger.setLevel(wookiee_constants.LOGGING_LEVEL)

        wookiee_name = wookiee_constants.WOOKIEE_MODE_NAMES.get(wookiee_mode)

        logger.info(f'WU P{peer} {wookiee_name} --- Relay worker started.')

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

                    while not remote_peer_event.is_set() and not exit_event.is_set():
                        logger.debug(f'WU P{peer} {wookiee_name} --- Listening for a keep alive packet...')
                        kadata, kaaddr = osocket.recvfrom(wookiee_constants.RECEIVE_BUFFER_SIZE)
                        #logger.debug(f'WU P{peer} {wookiee_name} --- {kaaddr[0]}:{kaaddr[1]} sent: {kadata}')

                        if kadata == RemotePeerHandler.KEEP_ALIVE_PACKET:
                            logger.debug(f'WU P{peer} {wookiee_name} --- Received a keep alive packet.')

                            if not peer_connection_received:
                                logger.info(f'WU P{peer} {wookiee_name} --- Client connection confirmed!')
                                peer_connection_received = True

                            sleep(wookiee_constants.KEEP_ALIVE_PING_INTERVAL)
                        # the client should reset sockets on the next keep alive packet trasmission
                        else:
                            logger.warning(f'WU P{peer} {wookiee_name} --- Invalid keep alive packet content.')

                        if not remote_peer_event.is_set():
                            logger.debug(f'WU P{peer} {wookiee_name} --- Sending a keep alive packet...')
                            osocket.sendto(RemotePeerHandler.KEEP_ALIVE_PACKET, kaaddr)
                        else:
                            logger.debug(f'WU P{peer} {wookiee_name} --- Halting keep alive...')
                            osocket.sendto(RemotePeerHandler.KEEP_ALIVE_HALT_PACKET, kaaddr)
                            logger.info(f'WU P{peer} {wookiee_name} --- Connection keep alive halted.')

                # the server can't otherwise know the public (exit) IP address of the client
                oaddr = kaaddr

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
                                logger.info(f'WU P{peer} {wookiee_name} --- Cached remote peer IP address/port.')
                                remote_peer_addr_cached = True
                            else:
                                logger.debug(f'WU P{peer} {wookiee_name} --- Waiting to establish remote peer IP address/port.')
                                # wait times here should be minimal due to link_event sync
                                sleep(0.05)

                try:
                    # '*-source-relay'
                    if wookiee_mode[1:] == b'01':
                        odata = source_queue.get(True, RemotePeerHandler.DEFAULT_TIMEOUT)
                    else:
                        odata = destination_queue.get(True, RemotePeerHandler.DEFAULT_TIMEOUT)

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

        logger.info(f'WU P{peer} {wookiee_name} --- Relay worker stopped.')

if __name__ == "__main__":
    # catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    # catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)

    if platform.system() == 'Linux':
        # 'spawn' will be the default for Linux starting with Python 3.14
        # (since it is more thread-safe), but since we want to ensure
        # compatibility with Nuitka, set it to 'fork' manually;
        # 'spawn' is already the default on Windows and macOS
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
        LOGGING_LEVEL_STR = logging_section.get('logging_level').upper()

        if LOGGING_LEVEL_STR == 'DEBUG':
            LOGGING_LEVEL = logging.DEBUG
        elif LOGGING_LEVEL_STR == 'WARNING':
            LOGGING_LEVEL = logging.WARNING
        elif LOGGING_LEVEL_STR == 'ERROR':
            LOGGING_LEVEL = logging.ERROR
        elif LOGGING_LEVEL_STR == 'CRITICAL':
            LOGGING_LEVEL = logging.CRITICAL
        else:
            # use INFO by default
            LOGGING_LEVEL = logging.INFO
    except:
        LOGGING_LEVEL = logging.INFO

    logger.setLevel(LOGGING_LEVEL)

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

    # constants determined at runtime need to be shared with child processes (they are read in __main__)
    wookiee_constants = WookieeConstants(LOGGING_LEVEL, RECEIVE_BUFFER_SIZE, CLIENT_CONNECTION_TIMEOUT,
                                         SERVER_CONNECTION_TIMEOUT, SERVER_PEER_CONNECTION_TIMEOUT,
                                         KEEP_ALIVE_PING_INTERVAL, KEEP_ALIVE_PING_TIMEOUT)

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
        wookiee_mode = WookieeConstants.WOOKIEE_MODE_CLIENT
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
        wookiee_mode = WookieeConstants.WOOKIEE_MODE_SERVER
        if args.iport is None:
            logger.critical('WU >>> Server mode requires setting --iport')
            raise SystemExit(2)
    else:
        logger.critical('WU >>> Invalid operation mode specified.')
        raise SystemExit(1)

    # use the interface name on Linux and fallback to local IP value on Windows
    if platform.system() == 'Linux' and args.interface is not None:
        # the interface name will only be used in socket operations
        # and the API expects a byte sequence, not a string
        intf = bytes(args.interface, 'utf-8')
        logger.debug(f'WU >>> intf: {args.interface}')
        # determine the local_ip based on the network interface name
        try:
            local_ip_query_subprocess = subprocess.run(['ip', '-4', 'addr', 'show', args.interface],
                                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                       check=True)
            local_ip_query_output = local_ip_query_subprocess.stdout.decode('utf-8')
            #logger.debug(f'WU >>> local_ip_query_output: {local_ip_query_output})')
            local_ip = local_ip_query_output[local_ip_query_output.find('inet ') + 5:
                                             local_ip_query_output.find('/')]

            if local_ip == '':
                logger.critical(f'WU >>> Unable to obtain an IP address for {args.interface}. Please retry with a valid interface name.')
                raise SystemExit(6)
        except:
            logger.critical(f'WU >>> Invalid interface {args.interface}. Please retry with a valid interface name.')
            raise SystemExit(6)
    else:
        intf = None

        if args.localip is None:
            logger.critical(f'WU >>> Please specify a network interface name (Linux) or a local IP address.')
            raise SystemExit(7)

        try:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.localip)
            local_ip = args.localip
        except ValueError:
            logger.critical(f'WU >>> Invalid local IP {args.localip}. Please retry with a valid IP address.')
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
        if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
            source_ip = None
        else:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.sourceip)
            source_ip = args.sourceip

        logger.debug(f'WU >>> source_ip: {source_ip}')
    except ValueError:
        logger.critical(f'WU >>> Invalid source IP {args.sourceip}. Please retry with a valid IP address.')
        raise SystemExit(9)

    try:
        # the destination ip will be determined dynamically by the server
        if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
            destination_ip = None
        else:
            # test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.destip)
            destination_ip = args.destip

        logger.debug(f'WU >>> destination_ip: {destination_ip}')
    except ValueError:
        logger.critical(f'WU >>> Invalid destination IP {args.destip}. Please retry with a valid IP address.')
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
        source_port = int(args.iport) if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER else SERVER_RELAY_BASE_PORT
        logger.debug(f'WU >>> source_port: {source_port}')

        if source_port < PORTS_RANGE[0] or source_port > PORTS_RANGE[1]:
            logger.critical('WU >>> Invalid source port specified.')
            raise SystemExit(13)
    except ValueError:
        logger.critical('WU >>> Invalid source port specified.')
        raise SystemExit(13)

    try:
        # the server will not need a destination port (its 'destination' will be the relay port)
        destination_port = CLIENT_RELAY_BASE_PORT if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER else int(args.oport)
        logger.debug(f'WU >>> destination_port: {destination_port}')

        if destination_port < PORTS_RANGE[0] or destination_port > PORTS_RANGE[1]:
            logger.critical('WU >>> Invalid destination port specified.')
            raise SystemExit(14)
    except ValueError:
        logger.critical('WU >>> Invalid destination port specified.')
        raise SystemExit(14)
    #########################################################################################################

    # the relay port will be used internally for UDP packet forwarding
    relay_port = SERVER_RELAY_BASE_PORT if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER else CLIENT_RELAY_BASE_PORT
    logger.debug(f'WU >>> relay_port: {relay_port}')

    if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
        logger.info(f'Starting the Wookiee Unicaster in SERVER mode, listening on {local_ip}:{source_port}.')
    else:
        logger.info((f'Starting the Wookiee Unicaster in CLIENT mode, connecting to the server on {source_ip} '
                     f'and forwarding traffic to {destination_ip}:{destination_port}.'))

    if no_config_file:
        logger.info('WU >>> The Wookiee Unicaster configuration file is absent. Built-in defaults will be used.')

    #################### MULTIPROCESS SHARED MEMORY ####################
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

    source_queue_list = [multiprocessing.Queue(PACKET_QUEUE_SIZE) for peer in range(peers)]
    destination_queue_list = [multiprocessing.Queue(PACKET_QUEUE_SIZE) for peer in range(peers)]
    remote_peer_event_list = [multiprocessing.Event() for peer in range(peers)]

    ###################### SERVER HANDLER PROCESS ######################
    if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
        server_handler = ServerHandler(peers, intf, local_ip, source_port, remote_peer_event_list,
                                       source_queue_list, remote_peer_addr_array, remote_peer_port_array,
                                       max_packet_size, source_packet_count, wookiee_constants)
        server_handler_process = server_handler.wookiee_server_handler_start()
    ####################################################################

    ################### REMOTE PEER HANDLER PROCESSES ##################
    remote_peer_handlers = [None] * peers
    remote_peer_handlers_reset_queue = multiprocessing.Queue(peers)
    remote_peer_handlers_processes = [None] * peers

    server_socket = None if wookiee_mode == WookieeConstants.WOOKIEE_MODE_CLIENT else server_handler.server_socket

    for peer in range(peers):
        if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
            destination_port += 1
            relay_port += 1
        else:
            source_port += 1
            relay_port += 1

        remote_peer_handlers[peer] = RemotePeerHandler(peer + 1, wookiee_mode, intf, local_ip, source_ip,
                                                       destination_ip, source_port, destination_port, relay_port,
                                                       source_queue_list[peer], destination_queue_list[peer],
                                                       remote_peer_event_list[peer], remote_peer_handlers_reset_queue,
                                                       remote_peer_addr_array, remote_peer_port_array, server_socket,
                                                       max_packet_size, source_packet_count, destination_packet_count,
                                                       wookiee_constants)

        remote_peer_handlers_processes[peer] = remote_peer_handlers[peer].wookiee_peer_handler_start()
    ####################################################################

    if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
        # notify the server handler process that all
        # the remote peer handlers have been started
        server_handler.child_proc_started_event.set()

    try:
        # use the main process to trigger peer handler resets when signaled
        while True:
            reset_peer = remote_peer_handlers_reset_queue.get()
            reset_peer_index = reset_peer - 1
            logger.debug(f'WU >>> Resetting remote peer handler P{reset_peer}...')
            for remote_peer_handler_process in remote_peer_handlers_processes[reset_peer_index]:
                if remote_peer_handler_process.is_alive():
                    remote_peer_handler_process.join()
            remote_peer_handlers_processes[reset_peer_index] = remote_peer_handlers[reset_peer_index].wookiee_peer_handler_start()
            logger.debug(f'WU >>> Remote peer handler P{reset_peer} has been reset.')

    except SystemExit:
        # exceptions may happen here as well due to logger syncronization mayhem on shutdown
        try:
            if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
                server_handler.remote_peer_worker_exit_event.set()
            for peer_handler in remote_peer_handlers:
                peer_handler.exit_event.set()
            logger.info('WU >>> Stopping the Wookiee Unicaster...')
        except:
            if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
                server_handler.remote_peer_worker_exit_event.set()
            for peer_handler in remote_peer_handlers:
                peer_handler.exit_event.set()

    finally:
        if wookiee_mode == WookieeConstants.WOOKIEE_MODE_SERVER:
            logger.debug('WU >>> Waiting for the server handler process to complete...')

            if server_handler_process.is_alive():
                server_handler_process.join()
            # clear server handler reference to trigger the destructor
            server_handler = None

            logger.debug('WU >>> The server handler process has been stopped.')

        logger.debug('WU >>> Waiting for the remote peer handler threads to complete...')

        for peer in range(peers):
            for remote_peer_handler_process in remote_peer_handlers_processes[peer]:
                if remote_peer_handler_process.is_alive():
                    remote_peer_handler_process.join()
            # clear remote peer handler references to trigger the destructor
            remote_peer_handlers[peer] = None

        logger.debug('WU >>> The remote peer handler threads have been stopped.')

        logger.info('WU >>> *********************** STATS ***********************')
        logger.info(f'WU >>> max_packet_size (inbound): {max_packet_size.value}')
        logger.info(f'WU >>> source_packet_count (inbound): {source_packet_count.value}')
        logger.info(f'WU >>> destination_packet_count (outbound): {destination_packet_count.value}')
        logger.info('WU >>> *********************** STATS ***********************')

    logger.info('WU >>> Ruow! (Goodbye)')
