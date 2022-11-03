#!/usr/bin/env python3
'''
@author: Winter Snowfall
@version: 2.02
@date: 04/11/2022
'''

import socket
import logging
import threading
import multiprocessing
import argparse
import subprocess
import signal
import queue
from time import sleep

##logging configuration block
logger_format = '%(asctime)s %(levelname)s >>> %(message)s'
#logging level for other modules
logging.basicConfig(format=logger_format, level=logging.ERROR) #DEBUG, INFO, WARNING, ERROR, CRITICAL
logger = logging.getLogger(__name__)
#logging level for current logger
logger.setLevel(logging.INFO) #DEBUG, INFO, WARNING, ERROR, CRITICAL

#constants
SERVER_PEER_UDP_CONNECTION_TIMEOUT = 30 #seconds
SERVER_UDP_CONNECTION_TIMEOUT = 20 #seconds
CLIENT_UDP_CONNECTION_TIMEOUT = 30 #seconds
SENDTO_QUEUE_TIMEOUT = 5 #seconds
UDP_KEEP_ALIVE_INTERVAL = 0.5 #seconds
THREAD_SPAWN_WAIT_INTERVAL = 0.2 #seconds
SERVER_RELAY_BASE_PORT = 23000
CLIENT_RELAY_BASE_PORT = 24000
#might need to be bumped in case applications use very large packet sizes,
#but 2048/4096 seems like a resonable amount in most cases (i.e. gaming)
RECV_BUFFER_SIZE = 2048
INTF_SOCKOPT_REF = 25

def sigterm_handler(signum, frame):
    #exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster process due to SIGTERM...')
    except:
        raise SystemExit(0)
            
    raise SystemExit(0)

def sigint_handler(signum, frame):
    #exceptions may happen here as well due to logger syncronization mayhem on shutdown
    try:
        logger.debug('WU >>> Stopping Wookiee Unicaster child process due to SIGINT...')
    except:
        raise SystemExit(0)
            
    raise SystemExit(0)

def wookiee_remote_peer_worker(peers, intf, isocket, remote_peer_event_list, 
                               source_queue_list, remote_peer_addr_reverse_dict,
                               max_packet_size, source_packet_count):
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    peer = 0 #the server will have a single source-receive queue worker process
    wookiee_mode = 'server-source-receive'
    
    remote_peer_addr_dict = {}
    queue_vacancy = [True] * peers
    vacant_queue_index = None
    
    #allow the other processes to spin up before accepting remote peers
    sleep(THREAD_SPAWN_WAIT_INTERVAL * 8)
    
    logger.info(f'WU P{peer} {wookiee_mode} *** Worker thread started.')
    
    while True:
        try:            
            if len(remote_peer_addr_dict) > 0:
                isocket.settimeout(SERVER_PEER_UDP_CONNECTION_TIMEOUT)
            idata, iaddr = isocket.recvfrom(RECV_BUFFER_SIZE)
            if len(remote_peer_addr_dict) > 0:
                isocket.settimeout(None)
            packet_size = len(idata)
            
            logger.debug(f'WU P{peer} {wookiee_mode} *** Detected remote peer: {iaddr}')
            logger.debug(f'WU P{peer} {wookiee_mode} *** Received a packet from {intf}/{iaddr[0]}:{iaddr[1]}...')
            #logger.debug(f'WU P{peer} {wookiee_mode} *** {iaddr[0]}:{iaddr[1]} sent: {idata}')
            logger.debug(f'WU P{peer} {wookiee_mode} *** Packet size: {packet_size}')
            #unlikely, but this is an indicator that the buffer size should be bumped,
            #otherwise UDP packets will get truncated (which can be bad up to very bad)
            if packet_size >= RECV_BUFFER_SIZE:
                logger.error(f'WU P{peer} {wookiee_mode} *** Packet size is equal to receive buffer size!')
                
            queue_index = remote_peer_addr_dict.get(iaddr, None)
            
            try:
                if queue_index is None:
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
            
            logger.debug(f'WU P{peer} {wookiee_mode} *** Purging peer lists...')
            remote_peer_addr_dict.clear()
            remote_peer_addr_reverse_dict.clear()
            queue_vacancy = [True] * peers
            vacant_queue_index = None
                
    logger.info(f'WU P{peer} {wookiee_mode} *** Worker thread stopped.')
    
def wookiee_receive_worker(peer, wookiee_mode, intf, isocket, source_ip, source_port,
                           socket_timeout, link_event, remote_peer_event, exit_event, 
                           source_queue, destination_queue,
                           max_packet_size, source_packet_count):
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU P{peer} {wookiee_mode} +++ Worker thread started.')
    
    #ensure no timeout is actively enforced on the socket
    isocket.settimeout(None)
    
    if wookiee_mode == 'client-source-receive':
        ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
        logger.info(f'WU P{peer} {wookiee_mode} +++ Initiating relay connection keep alive...')
        
        peer_connection_received = False
        
        while not remote_peer_event.is_set():
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Sending a keep alive packet...')
            isocket.sendto(bytes('Hello there!', 'utf-8'), (source_ip, source_port))
            
            sleep(UDP_KEEP_ALIVE_INTERVAL)
            
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Listening for a keep alive packet...')
            rdata, raddr = isocket.recvfrom(RECV_BUFFER_SIZE)
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Received a keep alive packet.')
            logger.debug(f'WU P{peer} {wookiee_mode} +++ {raddr[0]}:{raddr[1]} sent: {rdata}')
            
            if not peer_connection_received:
                logger.info(f'WU P{peer} {wookiee_mode} +++ Server connection confirmed!')
                peer_connection_received = True
            
            if rdata == b'STOP! Hammer time!':
                logger.info(f'WU P{peer} {wookiee_mode} +++ Connection keep alive halted.')
                remote_peer_event.set()
        ####################### UDP KEEP ALIVE LOGIC - CLIENT #########################
        
    if wookiee_mode == 'server-destination-receive':
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Waiting for connection to be established...')
        link_event.wait()
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Cleared by link event.')
        
    while not exit_event.is_set():
        try:
            if remote_peer_event.is_set():
                isocket.settimeout(socket_timeout)
            idata, iaddr = isocket.recvfrom(RECV_BUFFER_SIZE)
            if remote_peer_event.is_set():
                isocket.settimeout(None)
            packet_size = len(idata)
                
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Received a packet from {intf}/{iaddr[0]}:{iaddr[1]}...')
            #logger.debug(f'WU P{peer} {wookiee_mode} +++ {iaddr[0]}:{iaddr[1]} sent: {idata}')
            logger.debug(f'WU P{peer} {wookiee_mode} +++ Packet size: {packet_size}')
            #unlikely, but this is an indicator that the buffer size should be bumped,
            #otherwise UDP packets will get truncated (which can be bad up to very bad)
            if packet_size >= RECV_BUFFER_SIZE:
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
                
    try:
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Closing process socket instance...')
        isocket.close()
        logger.debug(f'WU P{peer} {wookiee_mode} +++ Process socket instance closed')
    except:
        pass
                
    logger.info(f'WU P{peer} {wookiee_mode} +++ Worker thread stopped.')
    
def wookiee_relay_worker(peer, wookiee_mode, intf, osocket, oaddr, 
                         link_event, remote_peer_event, exit_event, source_queue, 
                         destination_queue, remote_peer_addr_reverse_dict,
                         destination_packet_count):
    #catch SIGING and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU P{peer} {wookiee_mode} --- Worker thread started.')
    
    #ensure no timeout is actively enforced on the socket
    osocket.settimeout(None)
    
    if wookiee_mode == 'server-source-relay':
        ####################### UDP KEEP ALIVE LOGIC - SERVER #########################
        logger.info(f'WU P{peer} {wookiee_mode} --- Initiating relay connection keep alive...')
        
        peer_connection_received = False
        
        while not remote_peer_event.is_set():
            logger.debug(f'WU P{peer} {wookiee_mode} --- Listening for a keep alive packet...')
            odata, oaddr = osocket.recvfrom(RECV_BUFFER_SIZE)
            logger.debug(f'WU P{peer} {wookiee_mode} --- Received a keep alive packet.')
            logger.debug(f'WU P{peer} {wookiee_mode} --- {oaddr[0]}:{oaddr[1]} sent: {odata}')
            
            if not peer_connection_received:
                logger.info(f'WU P{peer} {wookiee_mode} --- Client connection confirmed!')
                peer_connection_received = True
                
            sleep(UDP_KEEP_ALIVE_INTERVAL)
            
            if not remote_peer_event.is_set():
                logger.debug(f'WU P{peer} {wookiee_mode} --- Sending a keep alive packet...')
                osocket.sendto(bytes('General Kenobi!', 'utf-8'), oaddr)
            else:
                logger.debug(f'WU P{peer} {wookiee_mode} --- Halting keep alive...')
                osocket.sendto(bytes('STOP! Hammer time!', 'utf-8'), oaddr)
             
        logger.info(f'WU P{peer} {wookiee_mode} --- Connection keep alive halted.')
        ####################### UDP KEEP ALIVE LOGIC - SERVER #########################
                
        logger.debug(f'WU P{peer} {wookiee_mode} --- Clearing link event...')
        link_event.set()
        logger.debug(f'WU P{peer} {wookiee_mode} --- Link event cleared.')
                
    while not exit_event.is_set():
        if wookiee_mode == 'server-destination-relay':
            remote_peer_event.wait()
            oaddr = remote_peer_addr_reverse_dict.get(peer-1, None)

        try:
            if wookiee_mode.endswith('-source-relay'):
                odata = source_queue.get(True, SENDTO_QUEUE_TIMEOUT)
            else:
                odata = destination_queue.get(True, SENDTO_QUEUE_TIMEOUT)
            
            logger.debug(f'WU P{peer} {wookiee_mode} --- Using remote peer: {oaddr}')
            osocket.sendto(odata, oaddr)
            logger.debug(f'WU P{peer} {wookiee_mode} --- Replicated a packet on {intf}/{oaddr[0]}:{oaddr[1]}...')
            
            if wookiee_mode.endswith('-destination-relay'):
                destination_packet_count.value += 1
                
        except queue.Empty:
            logger.debug(f'WU P{peer} {wookiee_mode} --- Timed out while waiting to send packet...')
            
    try:
        logger.debug(f'WU P{peer} {wookiee_mode} --- Closing process socket instance...')
        osocket.close()
        logger.debug(f'WU P{peer} {wookiee_mode} --- Process socket instance closed')
    except:
        pass
            
    logger.info(f'WU P{peer} {wookiee_mode} +++ Worker thread stopped.')
    
def wookie_peer_handler(peer, wookiee_mode, intf, local_ip, source_ip,  
                        destination_ip, source_port, destination_port, relay_port, 
                        source_queue, destination_queue, link_event, exit_event,
                        remote_peer_event, process_loop_event, remote_peer_addr_reverse_dict,
                        main_proc_socket, max_packet_size, 
                        source_packet_count, destination_packet_count):
    logger.debug(f'WU P{peer} >>> source_ip: {source_ip}')
    logger.debug(f'WU P{peer} >>> destination_ip: {destination_ip}')
    logger.debug(f'WU P{peer} >>> source_port: {source_port}')
    logger.debug(f'WU P{peer} >>> destination_port: {destination_port}')
    logger.debug(f'WU P{peer} >>> relay_port: {relay_port}')

    socket_timeout = SERVER_UDP_CONNECTION_TIMEOUT if wookiee_mode == 'server' else CLIENT_UDP_CONNECTION_TIMEOUT
    reset_loop = True
    
    if wookiee_mode == 'server':
        source = main_proc_socket
    else:
        source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        source.setsockopt(socket.SOL_SOCKET, INTF_SOCKOPT_REF, bytes(intf, 'utf-8'))
        logger.debug(f'WU P{peer} >>> Binding source to: {local_ip}:{source_port}')
        source.bind((local_ip, source_port))
        
    destination = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    destination.setsockopt(socket.SOL_SOCKET, INTF_SOCKOPT_REF, bytes(intf, 'utf-8'))
    logger.debug(f'WU P{peer} >>> Binding destination to: {local_ip}:{relay_port}')
    destination.bind((local_ip, relay_port))
    
    while reset_loop and process_loop_event.is_set():    
        try:
            logger.info(f'WU P{peer} >>> Starting Wookie Unicaster child processes...')
            #reset all shared process events
            link_event.clear()
            remote_peer_event.clear()
            exit_event.clear()
            
            #only clients must spawn a peer count of -source-receive processes, since servers will only need one receive process
            if wookiee_mode != 'server':
                wookiee_thread_source_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                                args=(peer, ''.join((wookiee_mode, '-source-receive')), intf, source,
                                                                      source_ip, source_port, socket_timeout, link_event, remote_peer_event, 
                                                                      exit_event, source_queue, destination_queue, 
                                                                      max_packet_size, source_packet_count), 
                                                                daemon=True)
            wookiee_thread_source_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                               args=(peer, ''.join((wookiee_mode, '-source-relay')), intf, destination, 
                                                                     ((destination_ip, destination_port)), link_event, remote_peer_event, 
                                                                     exit_event, source_queue, destination_queue, None,
                                                                     destination_packet_count), 
                                                               daemon=True)
            wookiee_thread_destination_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                             args=(peer, ''.join((wookiee_mode, '-destination-receive')), intf, destination,
                                                                   None, None, socket_timeout, link_event, remote_peer_event, 
                                                                   exit_event, source_queue, destination_queue,
                                                                   max_packet_size, source_packet_count), 
                                                             daemon=True)
            wookiee_thread_destination_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                             args=(peer, ''.join((wookiee_mode, '-destination-relay')), intf, source, 
                                                                   ((source_ip, source_port)), link_event, remote_peer_event, exit_event,
                                                                   source_queue, destination_queue, remote_peer_addr_reverse_dict,
                                                                   destination_packet_count), 
                                                             daemon=True)
            if wookiee_mode != 'server':
                wookiee_thread_source_receive.start()
            wookiee_thread_source_relay.start()
            wookiee_thread_destination_receive.start()
            wookiee_thread_destination_relay.start()
        
            if wookiee_mode != 'server':
                wookiee_thread_source_receive.join()
            wookiee_thread_source_relay.join()
            wookiee_thread_destination_receive.join()
            wookiee_thread_destination_relay.join()
            
            logger.info(f'WU P{peer} >>> Stopped all Wookie Unicaster child processes.')
            
        except:
            reset_loop = False
            logger.info(f'WU P{peer} >>> Stopping Wookie Unicaster...')
                      
    try:
        logger.info(f'WU P{peer} >>> Closing source socket...')
        source.close()
        logger.info(f'WU P{peer} >>> Source socket closed...')
    except:
        pass
    
    try:
        logger.info(f'WU P{peer} >>> Closing destination socket...')
        destination.close()
        logger.info(f'WU P{peer} >>> Destination socket closed...')
    except:
        pass

if __name__=="__main__":
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    
    parser = argparse.ArgumentParser(description=('*** The Wookiee Unicaster *** Replicates UDP packets between multiple private hosts using a public IP(v4) as relay. '
                                                  'Useful for UDP based multiplayer/LAN games enjoyed using Direct IP connections over the internet.'), add_help=False)
    
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')
    
    required.add_argument('-m', '--mode', help='Can be either server or client, depending on the run location.', required=True)
    required.add_argument('-e', '--interface', help='Local ethernet interface name.', required=True)
    
    optional.add_argument('-h', '--help', action='help', help='show this help message and exit')
    optional.add_argument('-p', '--peers', help='Number of remote peers. Is only useful for client-server UDP implementations.')
    optional.add_argument('-s', '--sourceip', help='Source IP address. Only needed in client mode.')
    optional.add_argument('-d', '--destip', help='Destination IP address. Only needed in client mode.')
    optional.add_argument('-i', '--iport', help='Port on which the server will listen for incoming UDP packets from remote peers.')
    optional.add_argument('-o', '--oport', help='End relay port. Only needed in client mode.')
          
    args = parser.parse_args()
    
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
    intf = args.interface
    logger.debug(f'WU >>> intf: {intf}')
    #determine the local_ip based on the network interface name
    local_ip_query_subprocess = subprocess.Popen(''.join(('ifconfig ', intf, ' | grep -w inet | awk \'{print $2;}\'')), 
                                                 shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    local_ip = local_ip_query_subprocess.communicate()[0].decode('utf-8').strip()
    logger.debug(f'WU >>> Local IP address is: {local_ip}')
    #the number of remote peers defaults to 1 if unspecified otherwise
    peers = 1 if args.peers is None else int(args.peers)
    #the actual source_ip will be determined dynamically by the server
    source_ip = None if wookiee_mode == 'server' else args.sourceip
    logger.debug(f'WU >>> source_ip: {source_ip}')
    #the destination ip will be determined dynamically by the server
    destination_ip = None if wookiee_mode == 'server' else args.destip
    logger.debug(f'WU >>> destination_ip: {destination_ip}')
    #the client will use the SERVER_RELAY_PORT as source
    source_port = int(args.iport) if wookiee_mode == 'server' else SERVER_RELAY_BASE_PORT
    logger.debug(f'WU >>> source_port: {source_port}')
    #the server will not need a destination port (its "destination" will be the relay port)
    destination_port = CLIENT_RELAY_BASE_PORT if wookiee_mode == 'server' else int(args.oport)
    logger.debug(f'WU >>> destination_port: {destination_port}')
    #the relay port will be used internally for UDP packet forwarding
    relay_port = SERVER_RELAY_BASE_PORT if wookiee_mode == 'server' else CLIENT_RELAY_BASE_PORT
    logger.debug(f'WU >>> relay_port: {relay_port}')
    
    if wookiee_mode == 'server':
        logger.info(f'Starting Wookie Unicaster in SERVER mode, listening on {local_ip}:{source_port}.')
    else:
        logger.info((f'Starting Wookie Unicaster in CLIENT mode, connecting to the server on {source_ip} ' 
                     f'and forwarding to {destination_ip}:{destination_port}.'))
    
    #shared events and queues
    link_event_list = [multiprocessing.Event() for i in range(peers)]
    exit_event_list = [multiprocessing.Event() for i in range(peers)]
    remote_peer_event_list = [multiprocessing.Event() for i in range(peers)]
    process_loop_event = threading.Event()
    process_loop_event.set()
    #set an arbitrary small buffer size for queues, since technically packets
    #shouldn't stack up too much between processes (and large queues will increase latency)
    source_queue_list = [multiprocessing.Queue(8) for i in range(peers)]
    destination_queue_list = [multiprocessing.Queue(8) for i in range(peers)]
    wookiee_peer_handler_threads = [None] * peers
        
    manager = multiprocessing.Manager()
    remote_peer_addr_reverse_dict = manager.dict()
    max_packet_size = multiprocessing.Value('i', 0)
    source_packet_count = multiprocessing.Value('i',0)
    destination_packet_count = multiprocessing.Value('i', 0)
    main_proc_socket = None
    
    if wookiee_mode == 'server':
        main_proc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        main_proc_socket.setsockopt(socket.SOL_SOCKET, INTF_SOCKOPT_REF, bytes(intf, 'utf-8'))
        main_proc_socket.bind((local_ip, source_port))
        
        main_proc = multiprocessing.Process(target=wookiee_remote_peer_worker, 
                                       args=(peers, intf, main_proc_socket, remote_peer_event_list,
                                             source_queue_list, remote_peer_addr_reverse_dict,
                                             max_packet_size, source_packet_count), 
                                       daemon=True)
        main_proc.start()
        
        sleep(THREAD_SPAWN_WAIT_INTERVAL)
    
    for peer in range(peers):
        if wookiee_mode == 'server':
            relay_port += 1
            destination_port += 1
        else:
            source_port += 1
            relay_port += 1
            
        source_queue = source_queue_list[peer]
        destination_queue = destination_queue_list[peer]
        link_event = link_event_list[peer]
        exit_event = exit_event_list[peer]
        remote_peer_event = remote_peer_event_list[peer]
        
        wookiee_peer_handler_threads[peer] = threading.Thread(target=wookie_peer_handler, 
                                                           args=(peer + 1, wookiee_mode, intf, local_ip, source_ip, 
                                                                 destination_ip, source_port, destination_port, relay_port,
                                                                 source_queue, destination_queue, link_event, exit_event,
                                                                 remote_peer_event, process_loop_event,
                                                                 remote_peer_addr_reverse_dict, main_proc_socket,
                                                                 max_packet_size, source_packet_count, destination_packet_count), 
                                                           daemon=True)
        wookiee_peer_handler_threads[peer].start()
        sleep(THREAD_SPAWN_WAIT_INTERVAL)
        
    try:
        for i in range(peers): 
            wookiee_peer_handler_threads[i].join()
        if wookiee_mode == 'server':
            main_proc.join()
            
    except KeyboardInterrupt:
        #not sure why a second KeyboardInterrupt gets thrown here on shutdown at times
        try:
            process_loop_event.clear()
            logger.info(f'WU >>> Stopping Wookie Unicaster...')
        except KeyboardInterrupt:
            process_loop_event.clear()
            
    except:
        process_loop_event.clear()
        logger.info(f'WU >>> Stopping Wookie Unicaster...')
            
    finally:
        logger.info('WU >>> *********************** STATS ***********************')
        logger.info(f'WU >>> max_packet_size (inbound): {max_packet_size.value}')
        logger.info(f'WU >>> source_packet_count (inbound): {source_packet_count.value}')
        logger.info(f'WU >>> destination_packet_count (outbound): {destination_packet_count.value}')   
        logger.info('WU >>> *********************** STATS ***********************')
        
        manager.shutdown()
        
        try:
            logger.info(f'WU P{peer} >>> Closing main source socket...')
            main_proc.close()
            logger.info(f'WU P{peer} >>> Main source socket closed...')
        except:
            pass
    
    logger.info('WU >>> Ruow! (Goodbye)')
    