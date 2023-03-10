#!/usr/bin/env python3
import argparse
import json
import re
import signal
import socket
import socketserver
import threading

from http.server import BaseHTTPRequestHandler,HTTPServer
import hashlib # For consistent hashing with SHA1
import datetime ## To get the current time for logging purposes
import http.client
from math import log
import time
import os

# Logger
import logging
import pickle
import subprocess

# Assignment 1 node properties
object_store = {}
neighbors = [] 

# Assignment 2 node properties
node_name = None
node_key = None
successor = None
other_neighbors = []
sim_crash = False
predecessor = None ##
neighbors_set = set() ## 

my_index = None ##
node_range_start = None ##
node_range_end = None ##

stop_requested = False ##
key_size = 2**16
            
class NodeHttpHandler(BaseHTTPRequestHandler):
    def send_whole_response(self, code, content, content_type="text/plain"):
        if isinstance(content, str):
            content = content.encode("utf-8")
            if not content_type:
                content_type = "text/plain"
            if content_type.startswith("text/"):
                content_type += "; charset=utf-8"
        elif isinstance(content, bytes):
            if not content_type:
                content_type = "application/octet-stream"
        elif isinstance(content, object):
            content = json.dumps(content, indent=2)
            content += "\n"
            content = content.encode("utf-8")
            content_type = "application/json"

        self.send_response(code)
        self.send_header('Content-type', content_type)
        self.send_header('Content-length',len(content))
        self.end_headers()
        self.wfile.write(content)

    def extract_key_from_path(self, path):
        return re.sub(r'/storage/?(\w+)', r'\1', path)

    def is_responsible_for_key(self, key):
        global node_key
        global successor
        hashed_key = hash_fn(key, key_size)
        successor_key = hash_fn(successor, key_size)
        if node_key > successor_key:
            if hashed_key not in range(successor_key, node_key):
                return True
            else:
                return False
        elif node_key < successor_key:
            if hashed_key in range(node_key, successor_key):
                return True
            else:
                return False
        elif node_key == successor_key:
            return True

    def do_PUT(self):
        global node_key
        global node_name
        global successor
        global predecessor
        global other_neighbors
        global sim_crash
        global neighbors_set
        
        if sim_crash == True: ## ?????? sim_crash??? True??? ###
            self.send_whole_response(500, "I have sim-crashed") ## sim_crashed ???????????? ?????? ###
            return #####
                
        ##### PUT
        #  ???????????? ????????? ???????????? ?????? ??????
        logging.info("Received PUT request from {}:\n{}".format(self.client_address[0], self.requestline)) ##
        content_length = int(self.headers.get('content-length', 0))

        key = self.extract_key_from_path(self.path) ### extract_key_from_path()??? /storage/ ????????? ?????????.
        value = self.rfile.read(content_length)

        logging.debug("node_key is {}".format(node_key)) ##
        logging.debug("successor_key is {}".format(hash_fn(successor, key_size))) ##

        # Hash the given key
        hashed_key = hash_fn(key, key_size)
        logging.debug("hashed_key is {}".format(hashed_key)) ## ?????? ?????? ??????

        if self.is_responsible_for_key(key):
            logging.info("PUT: I have responsibility for the key {} in my range {} from {}!".format(hashed_key, node_key, hash_fn(successor, key_size)-1)) ##
            object_store[key] = value  ## ??????????????? store??? ??????
        else:
            logging.info("PUT: I'm redirecting the key {} to my neighbor {}!".format(hashed_key, successor)) ##
            self.put_value(successor, key, value)
            
        # Send OK response
        self.send_whole_response(200, "Value stored for " + key) ## ??? ??????????????? ??????


    def do_GET(self):
        global node_key
        global node_name
        global successor
        global predecessor
        global other_neighbors
        global sim_crash
        global stop_requested ##
        global neighbors_set
        
        ##### GET ???????????? ????????? ???????????? ?????? ??????
        logging.info("Received GET request from client_address[0]:{}:\n{}".format(self.client_address[0], self.requestline)) ##
        
        ## ?????? ????????? /node-info??? ???????????? ???????????? ????????? ????????? ?????? ????????? json?????? ??????
        if self.path == "/node-info":
            node_info = { ## node_info??? ?????? ?????? ????????? ???????????? ????????? ??????
                    "node_key": node_key,
                    "successor": successor,
                    "predecessor": predecessor,
                    "others": other_neighbors,
                    "neighbors" : neighbors,
                    "sim_crash": sim_crash
                    }
            node_info_json = json.dumps(node_info, indent=2) # json ????????? ??????
            self.send_whole_response(200, node_info_json, content_type="application/json") ## json ??? ??????

        elif sim_crash == True: ## ?????? sim_crash??? True???
            self.send_whole_response(500, "I have sim-crashed") ## sim_crashed ???????????? ??????
            return #####

        elif self.path.startswith("/storage/"): ## ?????? ????????? /storage??? ????????????
            key = self.extract_key_from_path(self.path) ## ??? ???????????? ?????? ?????? ??????
            hashed_key = hash_fn(key, key_size)
            logging.debug("GET: hashed_key is {}".format(hashed_key)) ## ?????? ?????? ??????

            if key in object_store:
                logging.info("GET: I have responsibility for the key {}:{} in my range {} from {}!".format(key, hashed_key, node_key, hash_fn(successor, key_size)-1)) ##
                self.send_whole_response(200, object_store[key])

            elif self.is_responsible_for_key(key):
                logging.info("GET: I have responsibility for the key {}. but no object with key {} on this node".format(key, hashed_key)) ##
                self.send_whole_response(404, "No object with key '%s' on this node" % key)

            else:
                logging.info("GET: I'm redirecting the key {}:{} to my successor {}!".format(key, hashed_key, successor)) ##
                returned = self.get_value(successor, key)
                if returned == None: #if returned is None (if the key is not found on neighbor I requested)
                    self.send_whole_response(404, "No object with key '%s' on this node" % key)
                else:
                    if type(returned)!=bytes:
                        returned=returned.encode()
                    self.send_whole_response(200, returned)

        ## ?????? ????????? /neighbors??? ???????????? ?????? ????????? ??????
        elif self.path.startswith("/neighbors"):
            logging.debug("neighbors is {}".format(neighbors))
            self.send_whole_response(200, neighbors)

        ## ?????? ????????? /node_name??? ???????????? node_name ??????
        elif self.path.startswith("/node_name"):
            self.send_whole_response(200, node_name)

        ## ?????? ????????? /node_key??? ???????????? node_key ??????
        elif self.path.startswith("/node_key"):
            self.send_whole_response(200, node_key)

        ## ?????? ????????? /successor??? ???????????? successor ??????
        elif self.path.startswith("/successor"):
            self.send_whole_response(200, successor)

        ## ?????? ????????? /predecessor??? ???????????? predecessor ??????
        elif self.path.startswith("/predecessor"):
            self.send_whole_response(200, predecessor)

        ## ?????? ????????? /other_neighbors??? ???????????? other_neighbors ??????
        elif self.path.startswith("/other_neighbors"):
            self.send_whole_response(200, other_neighbors)

        ## ?????? ????????? /ask_join??? ???????????? ????????? ????????? ???????????? ????????? ??????
        elif self.path.startswith("/ask_join/"):
            logging.debug("in /ask_join/")
            asked_node = re.sub(r'/ask_join/?(\w+)', r'\1', self.path)
            hashed_key = hash_fn(asked_node, key_size) ## ??? ???????????? ?????? ?????? ??????
            logging.debug("asked_node is {}, it's hashed_key is {}".format(asked_node, hashed_key))
            if self.is_responsible_for_key(asked_node):
                logging.debug("1, my responsibility")

                b_response = json.dumps([successor, node_name]) ### string to bytes (1)
                
                returned = b_response # bytes of [successor, predecessor]
                logging.debug("responsible node(me):{}, returned  is {}".format(node_name, returned))

                if returned == None: #if returned is None
                    self.send_whole_response(404, "Error '%s'" % asked_node) # send error msg
                    logging.debug("returned Error with 404")

                else:
                    self.send_whole_response(200, returned) # send returned (bytes of [successor, predecessor])
                    logging.debug("returned {} with 200".format(returned))

                ## ??????????????? ??? ????????? ????????? ????????? ????????? ??????, ?????? ?????? ??????
                self.notify_predecessor(asked_node, successor) ### (3) (go down)
                logging.debug("Successor Updated!!!: from {} to {}".format(successor, asked_node))
                successor = asked_node ### (4)
                other_neighbors = self.get_successor(successor) ## ????????? ?????? ??????
            else:
                logging.debug("2, redirecting")
                returned = self.ask_join(asked_node, successor) # bytes of [successor, predecessor] (1)
                logging.debug("responsible node:{}, returned is {}".format(successor, returned))
                
                if returned == None: #if returned is None
                    self.send_whole_response(404, "Error '%s'" % asked_node) # send error msg
                    logging.debug("returned Error with 404")

                else:
                    self.send_whole_response(200, returned) # send returned (bytes of [successor, predecessor])
                    logging.debug("returned {} with 200".format(returned))
            
                                
        ## ?????? ????????? /notify_predecessor??? ???????????? ?????? ???????????? ???????????? ??????????????? ??????
        elif self.path.startswith("/notify_predecessor/"):
            logging.debug("in /notify_predecessor/")
            new_joined_node = re.sub(r'/notify_predecessor/?(\w+)', r'\1', self.path)
            logging.debug("Predecessor Updated!!: from {} to {}".format(predecessor, new_joined_node))
            predecessor = new_joined_node ### (3) ?????????
            
        ## ?????? ????????? /notify_successor??? ???????????? ?????? ???????????? ???????????? ??????????????? ??????
        elif self.path.startswith("/notify_successor/"):
            logging.debug("in /notify_successor/")
            new_node = re.sub(r'/notify_successor/?(\w+)', r'\1', self.path)
            logging.debug("Successor Updated!!: from {} to {}".format(successor, new_node))
            successor = new_node ### (3) ?????????
            other_neighbors = self.get_successor(successor) ## ????????? ?????? ??????
            
        ## ?????? ????????? /stop_requested??? ???????????? stop_requested ?????? ###
        elif self.path.startswith("/stop_requested"):
            if stop_requested==True:
                stop_requested=False
            else:
                stop_requested=True
            self.send_whole_response(200, stop_requested)

        else:
            self.send_whole_response(404, "Unknown path: " + self.path)

    def do_POST(self):
        global node_key
        global node_name
        global successor
        global predecessor
        global other_neighbors
        global sim_crash
        global neighbors_set

        if self.path == "/sim-recover":
            sim_crash = False
            self.send_whole_response(200, "")

        elif self.path == "/sim-crash":
            sim_crash = True
            self.send_whole_response(200, "")

        elif sim_crash == True:
            self.send_whole_response(500, "I have sim-crashed")
            return #####

        elif self.path == "/leave":
            self.notify_successor(successor, predecessor) # ???????????? ?????? ????????? ???????????? ??? ?????? ?????????
            self.notify_predecessor(predecessor, successor) # ???????????? ?????? ????????? ???????????? ??? ?????? ?????????

            successor = node_name # ????????? ?????? ?????????
            other_neighbors = node_name ## ????????? ?????? ??????
            predecessor = node_name # ????????? ?????? ?????????
            self.send_whole_response(200, "")

        elif self.path.startswith("/join"):
            nprime = re.sub(r'^/join\?nprime=([\w:-]+)$', r'\1', self.path)
            logging.debug("in /join\?nprime= nprime:{}".format(nprime))
            b_response = self.ask_join(node_name, nprime)
            response = json.loads(b_response) 
            logging.debug("Successor updated! from {} to {}".format(successor, response[0]))
            successor = response[0] ### (2)
            other_neighbors = self.get_successor(successor) ## ????????? ?????? ??????
            logging.debug("Predecessor updated! from {} to {}".format(predecessor, response[1]))
            predecessor = response[1] ### (2)
            
            self.send_whole_response(200, response)

        else:
            self.send_whole_response(404, "Unknown path: " + self.path)


    def ask_join(self, new_node_to_join, node_in_network):
        logging.debug("in self.ask_join()") ##
        conn = http.client.HTTPConnection(node_in_network)
        conn.request("GET", "/ask_join/"+new_node_to_join) # path: "/ask_join/"+new_node_to_join
        logging.debug("HTTPConnection to {}: /ask_join/{}".format(node_in_network, new_node_to_join)) ##
                
        resp = conn.getresponse()
        headers = resp.getheaders()
        if resp.status != 200:
            value = None
        else:
            value = resp.read()
            value = value.decode("utf-8")
        conn.close()
        return value

    def get_successor(self, node):
        conn = http.client.HTTPConnection(node) ## ?????? ????????? ????????? instance ??????
        conn.request("GET", "/successor")
        resp = conn.getresponse()
        headers = resp.getheaders() ## ?????? ?????????
        if resp.status == 500:  ## 500?????? ??????????????? ???????????? ???
            
            value = None
        else:
            value = resp.read() ## 200?????? value??? ?????? ??? ??????
        contenttype = "text/plain"
        for h, hv in headers:
            if h=="Content-type":
                contenttype = hv
        if contenttype == "text/plain":
            if value != None:
                value = value.decode("utf-8")
        conn.close()
        return value

    def notify_predecessor(self, new_node_joined, my_successor): # ???????????? ?????? ????????? ?????? ?????????
        global node_name
        global successor
        global predecessor
        global neighbors
        global neighbors_set
        logging.debug("in self.notify_predecessor()") ##
        if my_successor == node_name:
            logging.debug("my_successor: {} == node_name: {}".format(my_successor, node_name)) ##
            logging.debug("Predecessor updated!: from {} to {}".format(predecessor, new_node_joined)) ##
            predecessor = new_node_joined
        else:
            logging.debug("my_successor: {}, node_name: {}".format(my_successor, node_name)) ##
            conn = http.client.HTTPConnection(my_successor)
            conn.request("GET", "/notify_predecessor/"+new_node_joined)
            logging.debug("HTTPConnection to {}: /notify_predecessor/{}".format(my_successor, new_node_joined)) ##

    def notify_successor(self, new_node, my_predecessor): # ???????????? ?????? ????????? ?????? ?????????
        global node_name
        global successor
        global predecessor
        global neighbors
        global neighbors_set
        logging.debug("in self.notify_successor()") ##
        if my_predecessor == node_name:
            logging.debug("my_predecessor: {} == node_name: {}".format(my_predecessor, node_name)) ##
            logging.debug("Successor updated!: from {} to {}".format(successor, new_node)) ##
            successor = new_node
            other_neighbors = self.get_successor(successor) ## ????????? ?????? ??????
        else:
            logging.debug("my_predecessor: {}, node_name: {}".format(my_predecessor, node_name)) ##
            conn = http.client.HTTPConnection(my_predecessor)
            conn.request("GET", "/notify_successor/"+new_node)
            logging.debug("HTTPConnection to {}: /notify_successor/{}".format(my_predecessor, new_node)) ##
            
    def get_value(self, node, key):
        conn = http.client.HTTPConnection(node)
        conn.request("GET", "/storage/"+key)
        resp = conn.getresponse()
        headers = resp.getheaders()
        if resp.status != 200:
            value = None
        else:
            value = resp.read()
        contenttype = "text/plain"
        for h, hv in headers:
            if h=="Content-type":
                contenttype = hv
        if contenttype == "text/plain":
            if value != None:
                value = value.decode("utf-8")
        conn.close()
        return value

    def put_value(self, node, key, value):
        conn = http.client.HTTPConnection(node) ## ?????? ????????? ????????? instance ??????
        conn.request("PUT", "/storage/"+key, value) ## instance??? ???/?????? ?????? ?????? ("PUT"??? 'do_PUT'???)
        conn.getresponse() ## ?????? ??????
        conn.close() ## ??????

def arg_parser():
    PORT_DEFAULT = 8000
    DIE_AFTER_SECONDS_DEFAULT = 20 * 60

    LOGGER_DEFAULT = logging.DEBUG ##
    LOGGER_PATH_DEFAULT = "{}/log".format(os.path.dirname(os.path.abspath(__file__))) ##

    parser = argparse.ArgumentParser(prog="node", description="DHT Node")

    parser.add_argument("-p", "--port", type=int, default=PORT_DEFAULT,
            help="port number to listen on, default %d" % PORT_DEFAULT)

    parser.add_argument("--die-after-seconds", type=float,
            default=DIE_AFTER_SECONDS_DEFAULT,
            help="kill server after so many seconds have elapsed, " +
                "in case we forget or fail to kill it, " +
                "default %d (%d minutes)" % (DIE_AFTER_SECONDS_DEFAULT, DIE_AFTER_SECONDS_DEFAULT/60))

    parser.add_argument("neighbors", type=str, nargs="*",
            help="addresses (host:port) of neighbour nodes")

    parser.add_argument("-d", "--debug", type=int, ##
            default=LOGGER_DEFAULT,
            help="what level of logging to be enabled. Valid options are " +
                "0 (None), 10 (DEBUG), 20 (INFO), 30 (WARNING), 40 (ERROR) " +
                "and 50 (CRITICAL). Default is 0 (None).")

    parser.add_argument("-dp", "--debug-path", type=str, ##
            default=LOGGER_PATH_DEFAULT,
            help="the path to the folder where log files will end up." +
                "Default is a log folder in the same directory as the script.")

    return parser

class ThreadingHttpServer(socketserver.ThreadingMixIn, HTTPServer):
    pass

def hash_fn(key, modulo):
    hasher = hashlib.sha1()
    hasher.update(bytes(key.encode("utf-8")))
    return int(hasher.hexdigest(), 16) % modulo

def run_server(args):
    global server
    global neighbors
    
    global node_name
    global node_key
    global successor
    global other_neighbors
    global sim_crash
    global predecessor ###
    global neighbors_set

    global myIndex ##

    server = ThreadingHttpServer(('', args.port), NodeHttpHandler)

    if ((os.path.lexists(args.debug_path) == False) and (args.debug != logging.NOTSET)): ##
        os.mkdir(args.debug_path) ##
    now = datetime.datetime.now() ##
    log_time=("%02d:%02d:%02d"%(now.hour, now.minute, now.second)) ##

    node_name = server.server_name.split(".", 1)[0]
    node_name = f"{node_name}:{args.port}" #####
    node_key = hash_fn(node_name, key_size)

    logging.basicConfig(filename="{}/{}_{}.log".format(args.debug_path, node_name, log_time), ###
        format="%(relativeCreated)6d %(levelname)s: %(message)s", level=args.debug) ###
    global logger
    logger = logging.getLogger() ###

    logger.info("Logging set to level {}".format(args.debug))
    logger.info("Server name is {}".format(node_name))
    logger.info("Timeout set to {} seconds".format(args.die_after_seconds))

    logger = logging.getLogger(node_name)
    logger.setLevel(logging.INFO)

    ## ?????????????????? ????????????
    unsorted_hosts_list = open(
        (os.path.dirname(os.path.abspath(__file__)) + "/hosts"), "r"
    ).read().split("\n")
    unsorted_hosts_list.pop()

    hosts_list = list()
    for host in unsorted_hosts_list:
        sortval = hash_fn(host, 2**16)
        hosts_list.append((sortval, host))
    hosts_list.sort()

    ##### ????????? ?????????????????? ??????
    logging.info("Sorted node list is:") ##
    for sorted_node in hosts_list: ##
        logging.info(sorted_node) ##

    hosts_num = len(hosts_list)
    my_index = 0
    for node in hosts_list:
         if node[1] != node_name: # node[0] = node_key
            my_index += 1
        else:
            break

    logging.info("my index: {}".format(my_index)) ##
    logging.info("my successor: {}".format(successor)) ##

    if len(args.neighbors) == 0:
        successor = node_name
        predecessor = node_name ###
        other_neighbors = node_name

    if len(args.neighbors) >= 1:
        successor = hosts_list[(my_index+1) % hosts_num][1] ##
        predecessor = args.neighbors[-1] ###
        
        other_neighbors = args.neighbors[1:] ## 

    logging.info("my successor: {}".format(successor)) ##
    logging.info("my predecessor: {}".format(predecessor)) ##

    neighbors = args.neighbors


    def server_main():
        logger.info("Starting server on port %d" , args.port)
        server.serve_forever()
        logger.info("Server has shut down")

    def shutdown_server_on_signal(signum, frame):
        logger.info("We get signal (%s). Asking server to shut down", signum)
        server.shutdown()

    def stabilization(): 
        global stop_requested
        global successor
        global predecessor
        global other_neighbors

        stop_requested = False #####
        while not stop_requested:
            conn = http.client.HTTPConnection(successor) # ????????? ????????????
            conn.request("GET", "/successor") # ????????? ????????????
            resp = conn.getresponse()
            if resp.status != 200: # ????????? ?????? ???????????? ?????????
                logging.info("Unresponded!! successor: {}, status: {}".format(successor, resp.status)) ##
                conn = http.client.HTTPConnection(other_neighbors) # ????????? ????????? ??????
                conn.request("GET", "/notify_predecessor/"+node_name)
                logging.debug("HTTPConnection to {}: /notify_predecessor/{}".format(other_neighbors, node_name)) ##
                conn.close() ## ??????

                successor = other_neighbors # ?????? ????????? ???????????? ????????? ????????? ??????
                conn = http.client.HTTPConnection(successor) # ??? ????????? ??????
                conn.request("GET", "/successor") # ????????? ????????????
                resp = conn.getresponse()
                if resp.status != 200:
                    successor_successor = None
                else:
                    body = resp.read()
                    successor_successor = body.decode("utf-8") # ????????? ??????(????????? ??????)??? ????????? ????????? ??????
                conn.close()
                other_neighbors = successor_successor
                logging.info("successor: {}, successor's successor: {}".format(successor, other_neighbors)) ##
                
            else: # ????????? ?????? ????????????
                logging.info("Responded!! successor: {}, successor's successor: {}".format(successor, other_neighbors)) ##
                body = resp.read()
                successor_successor = body.decode("utf-8") # ????????? ??????(????????? ??????)??? ????????? ????????? ??????
                other_neighbors = successor_successor
                logging.info("successor's successor: {}".format(other_neighbors)) ##

            time.sleep(0.1) # 0.1 second sleep try to change it

    ### ?????? ??????????????????, ??????????????? ????????????????????? ???????????? ?????? (Network tolerance) 
    ### ????????? ?????? ?????? ?????? ????????? ?????? ?????? ????????? ?????? ????????? ?????? ????????? ????????? ?????? ??????
    ### ??? ????????? ?????? ???????????? ?????? ????????? ?????? ??????
    
    # Start server in a new thread, because server HTTPServer.serve_forever()
    # and HTTPServer.shutdown() must be called from separate threads
    thread = threading.Thread(target=server_main)
    thread.daemon = True
    thread.start()

    #Start stabilizer
    stabilization_thread = threading.Thread(target=stabilization) #####
    stabilization_thread.daemon = True #####
    stabilization_thread.start() #####

    # Shut down on kill (SIGTERM) and Ctrl-C (SIGINT)
    signal.signal(signal.SIGTERM, shutdown_server_on_signal)
    signal.signal(signal.SIGINT, shutdown_server_on_signal)

    #Start stabilizer
    # Stabilizer_thread = threading.Thread(target=Stabilizer, args=(args.port+1,)) #####
    # Stabilizer_thread.daemon = True #####
    # Stabilizer_thread.start() #####

    # Wait on server thread, until timeout has elapsed
    #
    # Note: The timeout parameter here is also important for catching OS
    # signals, so do not remove it.
    #
    # Having a timeout to check for keeps the waiting thread active enough to
    # check for signals too. Without it, the waiting thread will block so
    # completely that it won't respond to Ctrl-C or SIGTERM. You'll only be
    # able to kill it with kill -9.
    thread.join(args.die_after_seconds)
    stabilization_thread.join(args.die_after_seconds)
    #Stabilizer_thread.join(args.die_after_seconds) #####

    if thread.is_alive():
        logger.info("Reached %.3f second timeout. Asking server to shut down", args.die_after_seconds)
        server.shutdown()

    if stabilization_thread.is_alive(): #####
        stabilization_thread.join() #####
    #if Stabilizer_thread.is_alive(): #####
    #    Stabilizer_thread.join() #####
    

    logger.info("Exited cleanly")

if __name__ == "__main__":

    parser = arg_parser()
    args = parser.parse_args()
    run_server(args)
