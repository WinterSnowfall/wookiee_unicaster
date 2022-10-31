#!/usr/bin/env python3
'''
@author: Winter Snowfall
@version: 1.00
@date: 30/10/2022
'''

import socket
import logging
import multiprocessing
import argparse
import subprocess
import signal
#uncomment for debugging purposes only
#import traceback

##logging configuration block
logger_format = '%(asctime)s %(levelname)s >>> %(message)s'
#logging level for other modules
logging.basicConfig(format=logger_format, level=logging.ERROR) #DEBUG, INFO, WARNING, ERROR, CRITICAL
logger = logging.getLogger(__name__)
#logging level for current logger
logger.setLevel(logging.INFO) #DEBUG, INFO, WARNING, ERROR, CRITICAL

#constants
SERVER_RELAY_PORT = 23000
CLIENT_RELAY_PORT = 23001
#might need to be bumped in case applications use very large packet sizes,
#but 1024/2048 seems like a resonable amount in most cases (i.e. gaming)
RECV_BUFFER_SIZE = 2048
INTF_SOCKOPT_REF = 25

#global variables
init_event = multiprocessing.Event()
init_event.clear()
remote_peer_event = multiprocessing.Event()
remote_peer_event.clear()
#set an arbitrary small buffer size for queues, since technically packets
#shouldn't stack up too much between processes (and large queues will increase latency)
source_queue = multiprocessing.Queue(8)
destination_queue = multiprocessing.Queue(8)

def sigterm_handler(signum, frame):
    logger.info('WU >>> Stopping wookiee_broadcaster due to SIGTERM...')
    raise SystemExit(0)

def sigint_handler(signum, frame):
    logger.info('WU >>> Stopping wookiee_broadcaster process due to SIGINT...')
    raise SystemExit(0)
    
def wookiee_receive_worker(intf, isocket, wookiee_mode, max_packet_size, remote_peer_ip, remote_peer_port,
                           source_packet_count, destination_packet_count):
    #catch SIGINT and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU {wookiee_mode} --- Worker thread started.')
    
    if wookiee_mode == 'client-source-receive':
        logger.info(f'WU {wookiee_mode} >>> Initiating remote connection..')
        isocket.sendto(bytes('Hello there!', 'utf-8'), (source_ip, source_port))
        logger.info(f'WU {wookiee_mode} >>> Remote connection established.')
        
    if wookiee_mode == 'server-destination-receive':
        logger.debug(f'WU {wookiee_mode} >>> Waiting for connection to be established...')
        init_event.wait()
        logger.debug(f'WU {wookiee_mode} >>> Cleared by init event.')
    
    while True:
        idata, iaddr = isocket.recvfrom(RECV_BUFFER_SIZE)
        packet_size = len(idata)
        
        if wookiee_mode == 'server-source-receive':
            logger.debug(f'WU {wookiee_mode} --- Detected remote peer: {iaddr}')
            remote_peer_ip.value = bytes(iaddr[0], 'utf-8')
            remote_peer_port.value = iaddr[1]
            remote_peer_event.set()
            
        logger.debug(f'WU {wookiee_mode} --- Received a packet from {intf}/{iaddr[0]}:{iaddr[1]}...')
        logger.debug(f'WU {wookiee_mode} >>> {iaddr[0]}:{iaddr[1]} sent: {idata}')
        logger.debug(f'WU {wookiee_mode} --- Packet size: {packet_size}')
        #unlikely, but this is an indicator that the buffer size should be bumped,
        #otherwise UDP packets will get truncated (which can be bad up to very bad)
        if packet_size >= RECV_BUFFER_SIZE:
            logger.warning(f'WU {wookiee_mode} --- Packet size is equal to receive buffer size!')
        if packet_size > max_packet_size.value:
            max_packet_size.value = packet_size
            logger.debug(f'WU {wookiee_mode} --- New max_packet_size is: {max_packet_size.value}')
        
        #count the total number of received UDP packets
        if wookiee_mode.endswith('-source-receive'):
            source_queue.put(idata)
            source_packet_count.value += 1
        else:
            destination_queue.put(idata)
            destination_packet_count.value += 1
            
        logger.debug(f'WU {wookiee_mode} --- Packet queued for replication...')
        
def wookiee_relay_worker(intf, osocket, oaddr, wookiee_mode, remote_peer_ip, remote_peer_port):
    #catch SIGING and exit gracefully
    signal.signal(signal.SIGINT, sigint_handler)
    
    logger.info(f'WU {wookiee_mode} +++ Worker thread started.')
    
    if wookiee_mode == 'server-source-relay':
        logger.info(f'WU {wookiee_mode} >>> Listening for incomming connections...')
        odata, oaddr = osocket.recvfrom(RECV_BUFFER_SIZE)
        logger.info(f'WU {wookiee_mode} >>> Incoming connection received.')
        logger.debug(f'WU {wookiee_mode} >>> {oaddr[0]}:{oaddr[1]} sent: {odata}')
        
        logger.debug(f'WU {wookiee_mode} >>> Clearing init event...')
        init_event.set()
        logger.debug(f'WU {wookiee_mode} >>> Init event cleared.')
    
    while True:
        if wookiee_mode == 'server-destination-relay':
            remote_peer_event.wait()
            oaddr = ((remote_peer_ip.value.decode('utf-8'), remote_peer_port.value))
            logger.debug(f'WU {wookiee_mode} +++ Using remote peer: {oaddr}')

        odata = source_queue.get() if wookiee_mode.endswith('-source-relay') else destination_queue.get() 
        osocket.sendto(odata, oaddr)
        logger.debug(f'WU {wookiee_mode} +++ Replicated a packet on {intf}/{oaddr[0]}:{oaddr[1]}...')

if __name__=="__main__":
    #catch SIGTERM and exit gracefully
    signal.signal(signal.SIGTERM, sigterm_handler)
    
    parser = argparse.ArgumentParser(description=('*** The Wookiee Unicaster *** Replicates UDP packets between two private hosts using a public (v4) IP as relay. '
                                                  'Useful for UDP based multiplayer/LAN games enjoyed using direct IP connections over the internet.'), add_help=False)
    
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')
    
    required.add_argument('-m', '--mode', help='Can be either server or client, depending on the run location.', required=True)
    required.add_argument('-e', '--interface', help='Local ethernet interface name.', required=True)
    
    optional.add_argument('-h', '--help', action='help', help='show this help message and exit')
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
    local_ip_query_subprocess = subprocess.Popen(f'ifconfig {intf}' + ' | grep -w inet | awk \'{print $2;}\'', 
                                                 shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    local_ip = local_ip_query_subprocess.communicate()[0].decode('utf-8').strip()
    logger.debug(f'WU >>> Local IP address is: {local_ip}')
    #the actual source_ip will be determined dynamically by the server
    source_ip = None if wookiee_mode == 'server' else args.sourceip
    logger.debug(f'WU >>> source_ip: {source_ip}')
    #the destination ip will be determined dynamically by the server
    destination_ip = None if wookiee_mode == 'server' else args.destip
    logger.debug(f'WU >>> destination_ip: {destination_ip}')
    #the client will use the SERVER_RELAY_PORT as source
    source_port = int(args.iport) if wookiee_mode == 'server' else SERVER_RELAY_PORT
    logger.debug(f'WU >>> source_port: {source_port}')
    #the server will not need a destination port (its "destination" will be the relay port)
    destination_port = SERVER_RELAY_PORT if wookiee_mode == 'server' else int(args.oport)
    logger.debug(f'WU >>> destination_port: {destination_port}')
    #the relay port will be used internally for UDP packet forwarding
    relay_port = SERVER_RELAY_PORT if wookiee_mode == 'server' else CLIENT_RELAY_PORT
    logger.debug(f'WU >>> relay_port: {relay_port}')
    
    source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    source.setsockopt(socket.SOL_SOCKET, INTF_SOCKOPT_REF, bytes(intf, 'utf-8'))
    source.bind((local_ip, source_port))
    
    destination = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    destination.setsockopt(socket.SOL_SOCKET, INTF_SOCKOPT_REF, bytes(intf, 'utf-8'))
    destination.bind((local_ip, relay_port))
    
    #shared data between all processes
    source_packet_count = multiprocessing.Value('i', 0)
    destination_packet_count = multiprocessing.Value('i', 0)
    max_packet_size = multiprocessing.Value('i', 0)
    remote_peer_ip = multiprocessing.Array('c', 15)
    remote_peer_port = multiprocessing.Value('i', 0)
        
    wookiee_thread_source_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                    args=(intf, source, wookiee_mode + '-source-receive',
                                                          max_packet_size, remote_peer_ip, remote_peer_port,
                                                          source_packet_count, destination_packet_count), 
                                                    daemon=True)
    wookiee_thread_source_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                       args=(intf, destination, ((destination_ip, destination_port)), 
                                                             wookiee_mode + '-source-relay', remote_peer_ip, remote_peer_port), 
                                                       daemon=True)
    wookiee_thread_destination_receive = multiprocessing.Process(target=wookiee_receive_worker, 
                                                     args=(intf, destination, wookiee_mode + '-destination-receive',
                                                           max_packet_size, remote_peer_ip, remote_peer_port,
                                                           source_packet_count, destination_packet_count), 
                                                     daemon=True)
    wookiee_thread_destination_relay = multiprocessing.Process(target=wookiee_relay_worker, 
                                                     args=(intf, source, ((source_ip, source_port)), 
                                                           wookiee_mode + '-destination-relay', remote_peer_ip, remote_peer_port), 
                                                     daemon=True)
    
    wookiee_thread_source_receive.start()
    wookiee_thread_source_relay.start()
    wookiee_thread_destination_receive.start()
    wookiee_thread_destination_relay.start()
        
    try:
        wookiee_thread_source_receive.join()
        wookiee_thread_source_relay.join()
        wookiee_thread_destination_receive.join()
        wookiee_thread_destination_relay.join()
    
    except:
        pass
        #uncomment for debugging purposes only
        #logger.error(traceback.format_exc())
        
    finally:
        
        try:
            source.close()
        except:
            pass
        
        try:
            destination.close()
        except:
            pass
        
        logger.info(f'WU >>> *********************** STATS ***********************')
        logger.info(f'WU >>> max_packet_size: {max_packet_size.value}')
        logger.info(f'WU >>> source_packet_count: {source_packet_count.value}')
        logger.info(f'WU >>> destination_packet_count: {destination_packet_count.value}')   
        logger.info(f'WU >>> *********************** STATS ***********************')
        
        logger.info('WU >>> Quitting Wookiee Unicaster.')
    