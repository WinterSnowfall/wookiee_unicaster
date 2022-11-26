#!/usr/bin/env python3
'''
@author: Winter Snowfall
@version: 2.80
@date: 26/11/2022
'''

import os
import sys
import socket
import logging
import threading
import multiprocessing
import argparse
import subprocess
import signal
import queue
import ipaddress
from configparser import ConfigParser
from time import sleep

##logging configuration block
logger_format = '%(asctime)s %(levelname)s >>> %(message)s'
#logging level for other modules
logging.basicConfig(format=logger_format, level=logging.ERROR) #DEBUG, INFO, WARNING, ERROR, CRITICAL
logger = logging.getLogger(__name__)
#logging level defaults to INFO, but can be later modified through config file values
logger.setLevel(logging.INFO)

#constants
CONF_FILE_PATH = os.path.join(os.path.dirname(sys.argv[0]), 'wookiee_unicaster.cfg')
#valid (and bindable) port range boundaries
PORTS_RANGE_LOW_BOUND = 1024
PORTS_RANGE_HIGH_BOUND = 65535
#allows send processes to end gracefully when no data is sent, 
#based on the value of a corresponding exit process event
SENDTO_QUEUE_TIMEOUT = 5 #seconds
#default number of supported remote peers
REMOTE_PEERS_DEFAULT = '1'
#default relay port base values, to be used if otherwise unspecified
SERVER_RELAY_BASE_PORT_DEFAULT = '23000'
CLIENT_RELAY_BASE_PORT_DEFAULT = '23100'
#keep alive packet content (featuring bowcaster ASCII art guards)
KEEP_ALIVE_CLIENT_PACKET = b'-=|- Hello there! -|=-'
KEEP_ALIVE_SERVER_PACKET = b'-=|- General Kenobi! -|=-'
KEEP_ALIVE_SERVER_HALT_PACKET = b'-=|- You are a bold one! -|=-'
#allow spawn threads to fully initialize their processes 
#before the next spawn thread is started
THREAD_SPAWN_WAIT_INTERVAL = 0.1 #seconds

def sigterm_handler(signum, frame):
    #exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster process due to SIGTERM...')
    except:
        pass
            
    raise SystemExit(0)

def sigint_handler(signum, frame):
    #exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster process due to SIGINT...')
    except:
        pass
            
    raise SystemExit(0)

def wookiee_remote_peer_worker(peers, isocket, remote_peer_event_list, source_queue_list, 
                               remote_peer_worker_exit_event, remote_peer_addr_reverse_dict, 
                               max_packet_size, source_packet_count, child_proc_started_event):
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    peer = 0 #the server will have a single source-receive queue worker process
    wookiee_mode = 'server-source-receive'
    
    logger.info(f'WU P{peer} {wookiee_mode} *** Worker thread started.')
    
    try:
        remote_peer_addr_dict = {}
        queue_vacancy = [True] * peers
        vacant_queue_index = None
        
        #allow the other server processes to spin up before accepting remote peers
        child_proc_started_event.wait()
        
        while not remote_peer_worker_exit_event.is_set():
            try:
                if len(remote_peer_addr_dict) > 0:
                    isocket.settimeout(SERVER_PEER_CONNECTION_TIMEOUT)
                idata, iaddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                if len(remote_peer_addr_dict) > 0:
                    isocket.settimeout(None)
                packet_size = len(idata)
                
                logger.debug(f'WU P{peer} {wookiee_mode} *** Received a packet from {iaddr[0]}:{iaddr[1]}...')
                #logger.debug(f'WU P{peer} {wookiee_mode} *** {iaddr[0]}:{iaddr[1]} sent: {idata}')
                logger.debug(f'WU P{peer} {wookiee_mode} *** Packet size: {packet_size}')
                #unlikely, but this is an indicator that the buffer size should be bumped,
                #otherwise UDP packets will get truncated (which can be bad up to very bad)
                if packet_size >= RECEIVE_BUFFER_SIZE:
                    logger.error(f'WU P{peer} {wookiee_mode} *** Packet size is equal to receive buffer size!')
                    
                queue_index = remote_peer_addr_dict.get(iaddr, None)
                
                try:
                    if queue_index is None:
                        logger.info(f'WU P{peer} {wookiee_mode} *** Detected new remote peer: {iaddr[0]}:{iaddr[1]}')
                        
                        #try to free up any dropped peers if there are no vacancies
                        if True not in queue_vacancy:
                            for i in range(peers):
                                if not remote_peer_event_list[i].is_set():
                                    logger.debug(f'WU P{peer} {wookiee_mode} *** Vacating queue {i}...')
                                    vaddr = remote_peer_addr_reverse_dict.get(i, None)
                                    #remove the cleared element from the mapping dictionary
                                    #(the reverse dictionary key will be updated anyway on reassignment)
                                    if vaddr is not None:
                                        remote_peer_addr_dict.pop(vaddr)
                                    queue_vacancy[i] = True
                                    logger.debug(f'WU P{peer} {wookiee_mode} *** Queue marked as vacant.')
                        
                        #determine the lowest available queue index
                        vacant_queue_index = queue_vacancy.index(True)
                        logger.debug(f'WU P{peer} {wookiee_mode} *** vacant_queue_index: {vacant_queue_index}')
                        
                        #set the inbound address in the dictionary lookups
                        queue_index = vacant_queue_index
                        remote_peer_addr_dict.update({iaddr: queue_index})
                        remote_peer_addr_reverse_dict.update({queue_index: iaddr})
                        queue_vacancy[queue_index] = False
                        remote_peer_event_list[queue_index].set()
                    
                    logger.debug(f'WU P{peer} {wookiee_mode} *** remote_peer_addr_dict: {remote_peer_addr_dict}')
                    source_queue_list[queue_index].put(idata)
                    source_packet_count.value += 1
                    
                    #only consider the max_size of received & accepted packages
                    if packet_size > max_packet_size.value:
                        max_packet_size.value = packet_size
                        logger.debug(f'WU P{peer} {wookiee_mode} *** Max packet size now set to: {max_packet_size.value}')
                        
                    logger.debug(f'WU P{peer} {wookiee_mode} *** Packet queued for replication on queue {queue_index}...')
                
                #will happen if more peers than are supported attempt to connect
                except ValueError:
                    #simply ignore the packets received from the new peers in this case
                    logger.error(f'WU P{peer} {wookiee_mode} *** Number of peers exceeds current configurations!')
                    
            except socket.timeout:
                logger.debug(f'WU P{peer} {wookiee_mode} *** Timed out while waiting to receive packet...')
                
                if len(remote_peer_addr_dict) != 0 or len(remote_peer_addr_reverse_dict) != 0:
                    logger.info(f'WU P{peer} {wookiee_mode} *** Purging peer lists...')
                    remote_peer_addr_dict.clear()
                    remote_peer_addr_reverse_dict.clear()
                    queue_vacancy = [True] * peers
                    vacant_queue_index = None
                    
            #this is only raised on Windows, apparently
            except ConnectionResetError:
                logger.warning(f'WU P{peer} {wookiee_mode} *** Packet transmission was forcibly halted.')
                
    except SystemExit:
        pass
                
    logger.info(f'WU P{peer} {wookiee_mode} *** Worker thread stopped.')
    
def wookiee_receive_worker(peer, wookiee_mode, isocket, source_ip, source_port,
                           socket_timeout, link_event, remote_peer_event, exit_event, 
                           source_queue, destination_queue,
                           max_packet_size, source_packet_count):
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU P{peer} {wookiee_mode} +++ Worker thread started.')
    
    try:
        #ensure no timeout is actively enforced on the socket
        isocket.settimeout(None)
        
        if wookiee_mode == 'client-source-receive':
            ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
            if not remote_peer_event.is_set():
                logger.info(f'WU P{peer} {wookiee_mode} +++ Initiating relay connection keep alive...')
            
            peer_connection_received = False
            
            while not remote_peer_event.is_set():
                logger.debug(f'WU P{peer} {wookiee_mode} +++ Sending a keep alive packet...')
                isocket.sendto(KEEP_ALIVE_CLIENT_PACKET, (source_ip, source_port))
                
                sleep(KEEP_ALIVE_PING_INTERVAL)
                
                logger.debug(f'WU P{peer} {wookiee_mode} +++ Listening for a keep alive packet...')
                isocket.settimeout(KEEP_ALIVE_CLIENT_TIMEOUT)
                
                try:
                    rdata, raddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                     
                    logger.debug(f'WU P{peer} {wookiee_mode} +++ Received a keep alive packet.')
                    logger.debug(f'WU P{peer} {wookiee_mode} +++ {raddr[0]}:{raddr[1]} sent: {rdata}')
                    
                    if not peer_connection_received:
                        logger.info(f'WU P{peer} {wookiee_mode} +++ Server connection confirmed!')
                        peer_connection_received = True
                        
                    if rdata == KEEP_ALIVE_SERVER_HALT_PACKET:
                        logger.info(f'WU P{peer} {wookiee_mode} +++ Connection keep alive halted.')
                        remote_peer_event.set()
                
                except socket.timeout:
                    logger.debug(f'WU P{peer} {wookiee_mode} +++ Timed out waiting for a reply.')
                
                finally:
                    isocket.settimeout(None)
            ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
            
        if wookiee_mode == 'server-destination-receive':
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Waiting for the client connection to be established...')
            link_event.wait()
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Cleared by link event.')
            
        while not exit_event.is_set():
            try:
                if remote_peer_event.is_set():
                    isocket.settimeout(socket_timeout)
                idata, iaddr = isocket.recvfrom(RECEIVE_BUFFER_SIZE)
                if remote_peer_event.is_set():
                    isocket.settimeout(None)
                packet_size = len(idata)
                    
                logger.debug(f'WU P{peer} {wookiee_mode} +++ Received a packet from {iaddr[0]}:{iaddr[1]}...')
                #logger.debug(f'WU P{peer} {wookiee_mode} +++ {iaddr[0]}:{iaddr[1]} sent: {idata}')
                logger.debug(f'WU P{peer} {wookiee_mode} +++ Packet size: {packet_size}')
                #unlikely, but this is an indicator that the buffer size should be bumped,
                #otherwise UDP packets will get truncated (which can be bad up to very bad)
                if packet_size >= RECEIVE_BUFFER_SIZE:
                    logger.warning(f'WU P{peer} {wookiee_mode} +++ Packet size is equal to receive buffer size!')
                if wookiee_mode == 'client-source-receive' and packet_size > max_packet_size.value:
                    max_packet_size.value = packet_size
                    logger.debug(f'WU P{peer} {wookiee_mode} +++ New max_packet_size is: {max_packet_size.value}')
                
                #count the total number of received UDP packets
                if wookiee_mode.endswith('-source-receive'):
                    source_queue.put(idata)
                    source_packet_count.value += 1
                else:
                    destination_queue.put(idata)
                    
                logger.debug(f'WU P{peer} {wookiee_mode} +++ Packet queued for replication...')
                
            except socket.timeout:
                if wookiee_mode.endswith('-destination-receive') and not exit_event.is_set():
                    logger.warning(f'WU P{peer} {wookiee_mode} +++ The UDP connection has timed out. Resetting sockets...')
                    exit_event.set()
                else:
                    logger.debug(f'WU P{peer} {wookiee_mode} +++ Timed out while waiting to receive packet...')
                    
            #this is only raised on Windows, apparently
            except ConnectionResetError:
                logger.warning(f'WU P{peer} {wookiee_mode} +++ Packet transmission was forcibly halted.')
    
    except SystemExit:
        pass
                
    try:
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Closing process socket instance...')
        isocket.close()
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Process socket instance closed.')
    except:
        pass
                
    logger.info(f'WU P{peer} {wookiee_mode} +++ Worker thread stopped.')
    
def wookiee_relay_worker(peer, wookiee_mode, osocket, oaddr, 
                         link_event, remote_peer_event, exit_event, source_queue, 
                         destination_queue, remote_peer_addr_reverse_dict,
                         destination_packet_count):
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU P{peer} {wookiee_mode} --- Worker thread started.')
    
    try:
        #ensure no timeout is actively enforced on the socket
        osocket.settimeout(None)
        
        if wookiee_mode == 'server-source-relay':
            ####################### UDP KEEP ALIVE LOGIC - SERVER #########################
            if not remote_peer_event.is_set():
                logger.info(f'WU P{peer} {wookiee_mode} --- Initiating relay connection keep alive...')
            
            peer_connection_received = False
            
            while not remote_peer_event.is_set():
                logger.debug(f'WU P{peer} {wookiee_mode} --- Listening for a keep alive packet...')
                odata, oaddr = osocket.recvfrom(RECEIVE_BUFFER_SIZE)
                logger.debug(f'WU P{peer} {wookiee_mode} --- Received a keep alive packet.')
                logger.debug(f'WU P{peer} {wookiee_mode} --- {oaddr[0]}:{oaddr[1]} sent: {odata}')
                
                if not peer_connection_received:
                    logger.info(f'WU P{peer} {wookiee_mode} --- Client connection confirmed!')
                    peer_connection_received = True
                    
                sleep(KEEP_ALIVE_PING_INTERVAL)
                
                if not remote_peer_event.is_set():
                    logger.debug(f'WU P{peer} {wookiee_mode} --- Sending a keep alive packet...')
                    osocket.sendto(KEEP_ALIVE_SERVER_PACKET, oaddr)
                else:
                    logger.debug(f'WU P{peer} {wookiee_mode} --- Halting keep alive...')
                    osocket.sendto(KEEP_ALIVE_SERVER_HALT_PACKET, oaddr)
                    logger.info(f'WU P{peer} {wookiee_mode} --- Connection keep alive halted.')
                 
            ####################### UDP KEEP ALIVE LOGIC - SERVER #########################
                    
            logger.debug(f'WU P{peer} {wookiee_mode} --- Clearing link event...')
            link_event.set()
            logger.debug(f'WU P{peer} {wookiee_mode} --- Link event cleared.')
                    
        while not exit_event.is_set():
            if wookiee_mode == 'server-destination-relay':
                remote_peer_event.wait()
                oaddr = remote_peer_addr_reverse_dict.get(peer - 1, None)
    
            try:
                if wookiee_mode.endswith('-source-relay'):
                    odata = source_queue.get(True, SENDTO_QUEUE_TIMEOUT)
                else:
                    odata = destination_queue.get(True, SENDTO_QUEUE_TIMEOUT)
                
                try:
                    logger.debug(f'WU P{peer} {wookiee_mode} --- Using remote peer: {oaddr}')
                    osocket.sendto(odata, oaddr)
                    logger.debug(f'WU P{peer} {wookiee_mode} --- Replicated a packet to {oaddr[0]}:{oaddr[1]}...')
                    
                    if wookiee_mode.endswith('-destination-relay'):
                        destination_packet_count.value += 1
                #sometimes when a peer is dropped relay packets may still get sent its way;
                #simply ignore/drop them on relay if that's the case
                except TypeError:
                    logger.warning(f'WU P{peer} {wookiee_mode} --- Unknown or dropped remote peer. Dropping packet.')
                    
            except queue.Empty:
                logger.debug(f'WU P{peer} {wookiee_mode} --- Timed out while waiting to send packet...')
    
    except SystemExit:
        pass
            
    try:
        logger.debug(f'WU P{peer} {wookiee_mode} --- Closing process socket instance...')
        osocket.close()
        logger.debug(f'WU P{peer} {wookiee_mode} --- Process socket instance closed.')
    except:
        pass
            
    logger.info(f'WU P{peer} {wookiee_mode} --- Worker thread stopped.')
    
def wookiee_peer_handler(peer, wookiee_mode, intf, local_ip, source_ip, destination_ip, 
                         source_port, destination_port, relay_port, source_queue, destination_queue, 
                         link_event, exit_event, remote_peer_event, wookie_peer_handler_exit_event, 
                         remote_peer_addr_reverse_dict, remote_peer_socket, max_packet_size, 
                         source_packet_count, destination_packet_count):
    
    logger.info(f'WU P{peer} >>> Starting Wookiee Unicaster peer handler thread...')
    
    logger.debug(f'WU P{peer} >>> source_ip: {source_ip}')
    logger.debug(f'WU P{peer} >>> destination_ip: {destination_ip}')
    logger.debug(f'WU P{peer} >>> source_port: {source_port}')
    logger.debug(f'WU P{peer} >>> destination_port: {destination_port}')
    logger.debug(f'WU P{peer} >>> relay_port: {relay_port}')

    socket_timeout = SERVER_CONNECTION_TIMEOUT if wookiee_mode == 'server' else CLIENT_CONNECTION_TIMEOUT
    
    if wookiee_mode == 'server':
        source = remote_peer_socket
    else:
        source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            source.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, intf)
        except TypeError:
            logger.debug(f'WU P{peer} >>> Using manually specified local IP value on Linux.')
        except AttributeError:
            logger.warning(f'WU P{peer} >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
        except OSError:
            logger.critical(f'WU P{peer} >>> Interface not found or unavailable.')
            raise SystemExit(17)
        logger.debug(f'WU P{peer} >>> Binding source to: {local_ip}:{source_port}')
        try:
            source.bind((local_ip, source_port))
        except OSError:
            if intf is None:
                logger.critical(f'WU P{peer} >>> Invalid local IP {local_ip} or port {source_port} is in use.')
            else:
                logger.critical(f'WU P{peer} >>> Interface unavailable or port {source_port} is in use.')
            raise SystemExit(18)
        
    destination = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        destination.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, intf)
    except TypeError:
        logger.debug(f'WU P{peer} >>> Using manually specified local IP value on Linux.')
    except AttributeError:
        logger.warning(f'WU P{peer} >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
    except OSError:
        logger.critical(f'WU P{peer} >>> Interface not found or unavailable.')
        raise SystemExit(19)
    logger.debug(f'WU P{peer} >>> Binding destination to: {local_ip}:{relay_port}')
    try:
        destination.bind((local_ip, relay_port))
    except OSError:
        if intf is None:
            logger.critical(f'WU P{peer} >>> Invalid local IP {local_ip} or port {relay_port} is in use.')
        else:
            logger.critical(f'WU P{peer} >>> Interface unavailable or port {relay_port} is in use.')
        raise SystemExit(20)
    
    try:
        while not wookie_peer_handler_exit_event.is_set():
            logger.info(f'WU P{peer} >>> Starting Wookiee Unicaster child processes...')
            #reset all shared process events
            link_event.clear()
            remote_peer_event.clear()
            exit_event.clear()
            
            #only clients must spawn a peer count of -source-receive processes, since servers will only need one receive process
            if wookiee_mode != 'server':
                wookiee_proc_source_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                                      args=(peer, ''.join((wookiee_mode, '-source-receive')), source,
                                                                            source_ip, source_port, socket_timeout, link_event, remote_peer_event, 
                                                                            exit_event, source_queue, destination_queue, 
                                                                            max_packet_size, source_packet_count), 
                                                                      daemon=True)
            wookiee_proc_source_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                                args=(peer, ''.join((wookiee_mode, '-source-relay')), destination, 
                                                                      ((destination_ip, destination_port)), link_event, remote_peer_event, 
                                                                      exit_event, source_queue, destination_queue, None,
                                                                      destination_packet_count), 
                                                                daemon=True)
            wookiee_proc_destination_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                                       args=(peer, ''.join((wookiee_mode, '-destination-receive')), destination,
                                                                             None, None, socket_timeout, link_event, remote_peer_event, 
                                                                             exit_event, source_queue, destination_queue,
                                                                             max_packet_size, source_packet_count), 
                                                                       daemon=True)
            wookiee_proc_destination_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                                     args=(peer, ''.join((wookiee_mode, '-destination-relay')), source, 
                                                                           ((source_ip, source_port)), link_event, remote_peer_event, exit_event,
                                                                           source_queue, destination_queue, remote_peer_addr_reverse_dict,
                                                                           destination_packet_count), 
                                                                     daemon=True)
            if wookiee_mode != 'server':
                wookiee_proc_source_receive.start()
            wookiee_proc_source_relay.start()
            wookiee_proc_destination_receive.start()
            wookiee_proc_destination_relay.start()
        
            if wookiee_mode != 'server':
                wookiee_proc_source_receive.join()
            wookiee_proc_source_relay.join()
            wookiee_proc_destination_receive.join()
            wookiee_proc_destination_relay.join()
            
            logger.info(f'WU P{peer} >>> Stopped all Wookiee Unicaster child processes.')
            
    except:
        pass
         
    if wookiee_mode != 'server':
        try:
            logger.debug(f'WU P{peer} >>> Closing source socket...')
            source.close()
            logger.debug(f'WU P{peer} >>> Source socket closed.')
        except:
            pass
    
    try:
        logger.debug(f'WU P{peer} >>> Closing destination socket...')
        destination.close()
        logger.debug(f'WU P{peer} >>> Destination socket closed.')
    except:
        pass
    
    logger.info(f'WU P{peer} >>> Stopping Wookiee Unicaster peer handler thread...')

if __name__=="__main__":
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
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
        
    #parsing logging parameters
    try:
        LOGGING_LEVEL = logging_section.get('logging_level').upper()
        
        #DEBUG, INFO, WARNING, ERROR, CRITICAL
        if LOGGING_LEVEL == 'DEBUG':
            logger.setLevel(logging.DEBUG)
        elif LOGGING_LEVEL == 'WARNING':
            logger.setLevel(logging.WARNING)
        elif LOGGING_LEVEL == 'ERROR':
            logger.setLevel(logging.ERROR)
        elif LOGGING_LEVEL == 'CRITICAL':
            logger.setLevel(logging.CRITICAL)
    except:
        #will use the default level (INFO)
        pass
        
    #parsing connection parameters
    try:
        RECEIVE_BUFFER_SIZE = connection_section.getint('receive_buffer_size')
        logger.debug(f'WU >>> RECEIVE_BUFFER_SIZE: {RECEIVE_BUFFER_SIZE}')
    except:
        RECEIVE_BUFFER_SIZE = 2048 #bytes
    try:
        PACKET_QUEUE_SIZE = connection_section.getint('packet_queue_size')
        logger.debug(f'WU >>> PACKET_QUEUE_SIZE: {PACKET_QUEUE_SIZE}')
    except:
        PACKET_QUEUE_SIZE = 8 #packets
    try:
        SERVER_PEER_CONNECTION_TIMEOUT = connection_section.getint('server_peer_connection_timeout')
        logger.debug(f'WU >>> SERVER_PEER_CONNECTION_TIMEOUT: {SERVER_PEER_CONNECTION_TIMEOUT}')
    except:
        SERVER_PEER_CONNECTION_TIMEOUT = 30 #seconds
    try:
        SERVER_CONNECTION_TIMEOUT = connection_section.getint('server_connection_timeout')
        logger.debug(f'WU >>> SERVER_CONNECTION_TIMEOUT: {SERVER_CONNECTION_TIMEOUT}')
    except:
        SERVER_CONNECTION_TIMEOUT = 15 #seconds
    try:
        CLIENT_CONNECTION_TIMEOUT = connection_section.getint('client_connection_timeout')
        logger.debug(f'WU >>> CLIENT_CONNECTION_TIMEOUT: {CLIENT_CONNECTION_TIMEOUT}')
    except:
        CLIENT_CONNECTION_TIMEOUT = 15 #seconds
        
    #parsing keep alive parameters
    try:
        KEEP_ALIVE_PING_INTERVAL = keep_alive_section.getint('ping_interval')
        logger.debug(f'WU >>> KEEP_ALIVE_PING_INTERVAL: {KEEP_ALIVE_PING_INTERVAL}')
    except:
        KEEP_ALIVE_PING_INTERVAL = 2 #seconds
    try:
        KEEP_ALIVE_CLIENT_TIMEOUT = keep_alive_section.getint('client_timeout')
        logger.debug(f'WU >>> KEEP_ALIVE_CLIENT_TIMEOUT: {KEEP_ALIVE_CLIENT_TIMEOUT}')
    except:
        KEEP_ALIVE_CLIENT_TIMEOUT = 3 #seconds
    
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
                          default=REMOTE_PEERS_DEFAULT)
    optional.add_argument('-s', '--sourceip', help='Source IP address. Only needed in client mode.')
    optional.add_argument('-d', '--destip', help='Destination IP address. Only needed in client mode.')
    optional.add_argument('-i', '--iport', help='Port on which the server will listen for incoming UDP packets from remote peers.')
    optional.add_argument('-o', '--oport', help='End relay port. Only needed in client mode.')
    optional.add_argument('--server-relay-base-port', help=('Base port in the range used for packet relaying on both server and client. '
                                                          f'Defaults to {SERVER_RELAY_BASE_PORT_DEFAULT} if unspecified.'),
                          default=SERVER_RELAY_BASE_PORT_DEFAULT)
    optional.add_argument('--client-relay-base-port', help=('Base port in the range used as source for endpoint relaying on the client. ' 
                                                          f'Defaults to {CLIENT_RELAY_BASE_PORT_DEFAULT} if unspecified.'),
                          default=CLIENT_RELAY_BASE_PORT_DEFAULT)
    optional.add_argument('-q', '--quiet', help='Disable all logging output.', action='store_true')
    
    args = parser.parse_args()
    
    #disable all logging in quiet mode
    if args.quiet:
        logging.disable(logging.CRITICAL)
    
    #input validation
    if args.mode == 'server':
        if args.iport is None:
            logger.critical('WU >>> Server mode requires setting --iport')
            raise SystemExit(2)
    elif args.mode == 'client':
        if args.sourceip is None:
            logger.critical('WU >>> Client mode requires setting --sourceip')
            raise SystemExit(3)
        if args.destip is None:
            logger.critical('WU >>> Client mode requires setting --destip')
            raise SystemExit(4)
        if args.oport is None:
            logger.critical('WU >>> Client mode requires setting --oport')
            raise SystemExit(5)
    else:
        logger.critical('WU >>> Invalid operation mode specified.')
        raise SystemExit(1)
    
    wookiee_mode = args.mode

    #use the interface name on Linux and fallback to local IP value on Windows
    if args.interface is not None:
        #the interface name will only be used in socket operations 
        #and the API expects a byte sequence, not a string
        intf = bytes(args.interface, 'utf-8')
        logger.debug(f'WU >>> intf: {args.interface}')
        #determine the local_ip based on the network interface name
        local_ip_query_subprocess = subprocess.Popen(''.join(('ifconfig ', args.interface, ' | grep -w inet | awk \'{print $2;}\'')), 
                                                     shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        local_ip = local_ip_query_subprocess.communicate()[0].decode('utf-8').strip()
        
        if local_ip == '':
            logger.critical(f'Invalid interface {args.interface}. Please retry with a valid interface name.')
            raise SystemExit(6)
    else:
        intf = None
        
        try:
            #test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.localip)
            local_ip = args.localip
        except ValueError:
            logger.critical(f'Invalid local IP {args.localip}. Please retry with a valid IP address.')
            raise SystemExit(7)
    
    logger.debug(f'WU >>> Local IP address is: {local_ip}')
    #the number of remote peers (defaults to 1 if otherwise unspecified)
    try:
        peers = int(args.peers)
        logger.debug(f'WU >>> peers: {peers}')
        
        if peers < 1:
            logger.critical('WU >>> These are not the peers you are looking for.')
            raise SystemExit(8)
        
    except ValueError:
        logger.critical('WU >>> Invalid number of peers specified.')
        raise SystemExit(8)
    #the actual source_ip will be determined dynamically by the server
    try:
        if wookiee_mode == 'server':
            source_ip = None
        else:
            #test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.sourceip)
            source_ip = args.sourceip
            
        logger.debug(f'WU >>> source_ip: {source_ip}')
    except ValueError:
        logger.critical(f'Invalid source IP {args.sourceip}. Please retry with a valid IP address.')
        raise SystemExit(9)
    #the destination ip will be determined dynamically by the server
    try:
        if wookiee_mode == 'server':
            destination_ip = None  
        else:
            #test to see if the provided string is a valid IP address
            ipaddress.ip_address(args.destip)
            destination_ip = args.destip
        
        logger.debug(f'WU >>> destination_ip: {destination_ip}')
    except ValueError:
        logger.critical(f'Invalid destination IP {args.destip}. Please retry with a valid IP address.')
        raise SystemExit(10)
    #determine the value of the server relay port (can be passed as a parameter)
    try:
        SERVER_RELAY_BASE_PORT = int(args.server_relay_base_port)
        logger.debug(f'WU >>> SERVER_RELAY_BASE_PORT: {SERVER_RELAY_BASE_PORT}')
        
        if SERVER_RELAY_BASE_PORT < PORTS_RANGE_LOW_BOUND or SERVER_RELAY_BASE_PORT > PORTS_RANGE_HIGH_BOUND - peers:
            logger.critical('WU >>> Invalid server relay base port specified.')
            raise SystemExit(11)
    except ValueError:
        logger.critical('WU >>> Invalid server relay base port specified.')
        raise SystemExit(11)
    #determine the value of the server relay port (can be passed as a parameter)
    try:
        CLIENT_RELAY_BASE_PORT = int(args.client_relay_base_port)
        logger.debug(f'WU >>> CLIENT_RELAY_BASE_PORT: {CLIENT_RELAY_BASE_PORT}')
        
        if CLIENT_RELAY_BASE_PORT < PORTS_RANGE_LOW_BOUND or CLIENT_RELAY_BASE_PORT > PORTS_RANGE_HIGH_BOUND - peers:
            logger.critical('WU >>> Invalid client relay base port specified.')
            raise SystemExit(12)
    except ValueError:
        logger.critical('WU >>> Invalid client relay base port specified.')
        raise SystemExit(12)
    #the client will use the SERVER_RELAY_BASE_PORT as source
    try:
        source_port = int(args.iport) if wookiee_mode == 'server' else SERVER_RELAY_BASE_PORT
        logger.debug(f'WU >>> source_port: {source_port}')
        
        if source_port < PORTS_RANGE_LOW_BOUND or source_port > PORTS_RANGE_HIGH_BOUND:
            logger.critical('WU >>> Invalid source port specified.')
            raise SystemExit(13)
    except ValueError:
        logger.critical('WU >>> Invalid source port specified.')
        raise SystemExit(13)
    #the server will not need a destination port (its "destination" will be the relay port)
    try:
        destination_port = CLIENT_RELAY_BASE_PORT if wookiee_mode == 'server' else int(args.oport)
        logger.debug(f'WU >>> destination_port: {destination_port}')
        
        if destination_port < PORTS_RANGE_LOW_BOUND or destination_port > PORTS_RANGE_HIGH_BOUND:
            logger.critical('WU >>> Invalid destination port specified.')
            raise SystemExit(14)
    except ValueError:
        logger.critical('WU >>> Invalid destination port specified.')
        raise SystemExit(14)
    #the relay port will be used internally for UDP packet forwarding
    relay_port = SERVER_RELAY_BASE_PORT if wookiee_mode == 'server' else CLIENT_RELAY_BASE_PORT
    logger.debug(f'WU >>> relay_port: {relay_port}')
    
    if wookiee_mode == 'server':
        logger.info(f'Starting the Wookiee Unicaster in SERVER mode, listening on {local_ip}:{source_port}.')
    else:
        logger.info((f'Starting the Wookiee Unicaster in CLIENT mode, connecting to the server on {source_ip} ' 
                     f'and forwarding to {destination_ip}:{destination_port}.'))
        
    if no_config_file:
        logger.info('WU >>> The Wookiee Unicaster configuration file is absent. Built-in defaults will be used.')
    
    link_event_list = [multiprocessing.Event() for i in range(peers)]
    exit_event_list = [multiprocessing.Event() for i in range(peers)]
    remote_peer_event_list = [multiprocessing.Event() for i in range(peers)]
    source_queue_list = [multiprocessing.Queue(PACKET_QUEUE_SIZE) for i in range(peers)]
    destination_queue_list = [multiprocessing.Queue(PACKET_QUEUE_SIZE) for i in range(peers)]
    
    manager = multiprocessing.Manager()
    remote_peer_addr_reverse_dict = manager.dict()
    max_packet_size = multiprocessing.Value('i', 0)
    source_packet_count = multiprocessing.Value('i', 0)
    destination_packet_count = multiprocessing.Value('i', 0)
    
    wookiee_peer_handler_threads = [None] * peers
    wookie_peer_handler_exit_event = threading.Event()
    wookie_peer_handler_exit_event.clear()
    
    remote_peer_socket = None
    
    if wookiee_mode == 'server':
        remote_peer_worker_exit_event = multiprocessing.Event()
        remote_peer_worker_exit_event.clear()
        
        child_proc_started_event = multiprocessing.Event()
        child_proc_started_event.clear()
        
        remote_peer_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            remote_peer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, intf)
        except TypeError:
            logger.debug(f'WU >>> Using manually specified local IP value on Linux.')
        except AttributeError:
            logger.warning('WU >>> SO_BINDTODEVICE is not available. This is normal on Windows.')
        except OSError:
            logger.critical('WU >>> Interface not found or unavailable.')
            raise SystemExit(15)
        try:
            remote_peer_socket.bind((local_ip, source_port))
        except OSError:
            if intf is None:
                logger.critical(f'WU >>> Invalid local IP {local_ip} or port {source_port} is in use.')
            else:
                logger.critical(f'WU >>> Interface unavailable or port {source_port} is in use.')
            raise SystemExit(16)
        
        wookiee_remote_peer_proc = multiprocessing.Process(target=wookiee_remote_peer_worker, 
                                                           args=(peers, remote_peer_socket, remote_peer_event_list,
                                                                 source_queue_list, remote_peer_worker_exit_event, 
                                                                 remote_peer_addr_reverse_dict, max_packet_size, 
                                                                 source_packet_count, child_proc_started_event), 
                                                           daemon=True)
        wookiee_remote_peer_proc.start()
        
    for peer in range(peers):
        sleep(THREAD_SPAWN_WAIT_INTERVAL)
        
        if wookiee_mode == 'server':
            relay_port += 1
            destination_port += 1
        else:
            source_port += 1
            relay_port += 1
        
        wookiee_peer_handler_threads[peer] = threading.Thread(target=wookiee_peer_handler, 
                                                              args=(peer + 1, wookiee_mode, intf, local_ip, source_ip, 
                                                                    destination_ip, source_port, destination_port, relay_port,
                                                                    source_queue_list[peer], destination_queue_list[peer], 
                                                                    link_event_list[peer], exit_event_list[peer],
                                                                    remote_peer_event_list[peer], wookie_peer_handler_exit_event,
                                                                    remote_peer_addr_reverse_dict, remote_peer_socket,
                                                                    max_packet_size, source_packet_count, destination_packet_count), 
                                                              daemon=True)
        wookiee_peer_handler_threads[peer].start()
        
    if wookiee_mode == 'server':
        sleep(THREAD_SPAWN_WAIT_INTERVAL)
        #signal the main remote peer process that all child threads have been started
        child_proc_started_event.set()
        
    try:
        wookie_peer_handler_exit_event.wait()
         
    except SystemExit:
        #exceptions may happen here as well due to logger syncronization mayhem on shutdown
        try:
            if wookiee_mode == 'server':
                remote_peer_worker_exit_event.set()
            wookie_peer_handler_exit_event.set()
            logger.info('WU >>> Stopping the Wookiee Unicaster...')
        except:
            if wookiee_mode == 'server':
                remote_peer_worker_exit_event.set()
            wookie_peer_handler_exit_event.set()
            
    finally:
        if wookiee_mode == 'server':
            logger.info('WU >>> Waiting for remote peer process to complete...')
            
            wookiee_remote_peer_proc.join()
            
            logger.info('WU >>> The remote peer process has been stopped.')
            
            try:
                logger.debug('WU >>> Closing remote peer socket...')
                remote_peer_socket.close()
                logger.debug('WU >>> Remote peer socket closed.')
            except:
                pass
        
        logger.info('WU >>> Waiting for the peer handler threads to complete...')
        
        for i in range(peers):
            wookiee_peer_handler_threads[i].join()
        
        logger.info('WU >>> The peer handler threads have been stopped.')
        
        logger.info('WU >>> *********************** STATS ***********************')
        logger.info(f'WU >>> max_packet_size (inbound): {max_packet_size.value}')
        logger.info(f'WU >>> source_packet_count (inbound): {source_packet_count.value}')
        logger.info(f'WU >>> destination_packet_count (outbound): {destination_packet_count.value}')   
        logger.info('WU >>> *********************** STATS ***********************')
        
        manager.shutdown()
    
    logger.info('WU >>> Ruow! (Goodbye)')
