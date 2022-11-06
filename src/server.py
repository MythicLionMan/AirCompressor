import uasyncio as asyncio
import machine
import network
import socket
import ujson
import sys
    
# Loosly based on https://gist.github.com/aallan/3d45a062f26bc425b22a17ec9c81e3b6
class Server:
    def __init__(self, settings, asynchronous):
        self.settings = settings
        self.asynchronous = asynchronous
        self.have_configured_wlan = False        
        
    def parse_request(self, request_line):
        (request_type, request, protocol) = request_line.decode('ascii').split()

        tokens = request.split('?')

        if len(tokens) == 0:
            endpoint = ''
            parameter_strings = None
        elif len(tokens) == 1:
            endpoint = str(tokens[0])
            parameter_strings = None
        elif len(tokens) == 2:
            endpoint = str(tokens[0])
            parameter_strings = str(tokens[1])
        
        parameters = {}
        if not parameter_strings == None:
            kv = parameter_strings.split('&')
            for pair in kv:
                (key, value) = pair.split('=')
                
                parameters[key] = value

        print("Request: ", request_line)
        #print("Request Type: '{}'".format(request_type))
        #print("Endpoint: '{}'".format(endpoint))
        #print("Parameters: '{}' found: {}".format(parameter_strings, len(parameters)))
        
        return (request_type, endpoint, parameters)

    async def read_headers(self, reader):
        # We are not interested in HTTP request headers, skip them
        headers = {}
        while True:
            header_line = await reader.readline()
            if header_line == b"\r\n":
                break
            
            (key, value) = header_line.split(b': ')
            headers[key.decode()] = value[:-2].decode()
            
        return headers
        
    def response_header(self, writer, status = 200, content_type = 'application/json'):
        writer.write('HTTP/1.0 {} OK\r\nContent-type: {}\r\n\r\n'.format(status, content_type))
    
    def return_json(self, writer, obj, status = 200):
        self.response_header(writer, status)
        # TODO I'd rather do this 'inline' without having to serialize to a string first, but
        #      ujson.dump() doesn't support uasyncio (which seems strange to me).
        writer.write(ujson.dumps(obj))

    # Returns a file stored in the local file system
    async def return_http_document(self, writer, path, substitutions = None, status = 200):
        await writer.drain()

        try:
            if path.endswith('.html'):
                content_type = 'text/html'
            elif path.endswith('.js'):
                content_type = 'script/javascript'
            elif path.endswith('.json'):
                content_type = 'application/json'
            elif path.endswith('.css'):
                content_type = 'text/css'
            else:
                content_type = 'text/plain'

            self.response_header(writer, content_type = content_type)

            f = open(path)
            # Transimit the document one line at a time to save memory
            while True:
                line = f.readline()

                if line == '':
                    break
                if substitutions:
                    line = line.format(**substitutions)
                    
                writer.write(line)
                await writer.drain()
                
            f.close()    
        except OSError:
            self.response_header(writer, status = 404, content_type = 'text/html')
            writer.write('<html><head></head><body><h1>Error 404: Document {} not found.</h1></body></html>'.format(path))

    # adapted from https://github.com/micropython/micropython/blob/d9d67adef1113ab18f1bb3c0c6204ccb210a27be/docs/wipy/tutorial/wlan.rst
    # TODO Settings doesn't have the required properties for static IP setup yet
    async def _configure_and_connect_to_network(self, max_retries):
        settings = self.settings
        # TODO This should be machine.SOFT_RESET instead of '5' but I can't get the import to work
        if machine.reset_cause() != 5 and not self.have_configured_wlan:
            self.wlan = wlan = network.WLAN(network.STA_IF)
            wlan.active(True)
            wlan.config(pm = 0xa11140)  # Disable power-save mode
            
            # If a static config has been provided use that instead of letting the stack auto configure
            #if settings.ip != '' and settings.net_mask != '' and settings.gateway != '' and settings.nameserver != '':
            #    wlan.ifconfig(config=(settings.ip, settings.net_mask, settings.gateway, settings.nameserver))
            self.have_configured_wlan = True
        else:
            wlan = self.wlan

        if not wlan.isconnected():
            wlan.connect(settings.ssid, settings.wlan_password)
            
            retries = max_retries
            while retries > 0 or max_retries == 0:
                if wlan.status() < 0 or wlan.status() >= 3:
                    break
                retries -= 1
                print('waiting for connection to SSID {}...'.format(settings.ssid))
                await asyncio.sleep(1)

        if not wlan.isconnected():
            raise RuntimeError('network connection failed')
        else:
            print('connected')
            status = wlan.ifconfig()
            print('ip = ' + status[0])

    def _run_blocking(self):
        addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]

        s = socket.socket()
        s.bind(addr)
        s.listen(1)

        print('listening on', addr)

        # Listen for connections
        while True:
            try:
                print('Waiting for connection.')
                cl, addr = s.accept()
                print('client connected from', addr)
                
                self.handle_request(cl)
                print('request completed successfully')
            finally:
                cl.close()
                print('connection closed')
                            
    async def _run(self):
        while True:
            try:
                print('Connecting to Network...')
                await self._configure_and_connect_to_network(0)
                
                print('Starting webserver...')
                if self.asynchronous:
                    self.server = await asyncio.start_server(self.serve_client, "0.0.0.0", 80)
                    print('Server has started and is waiting for requests.')
                else:
                    self._run_blocking()
                    print('Webserver is done. Bye bye.')
            # TODO I sometimes get ENOMEM here. It looks like I'm not releasing sockets properly
            #      https://forum.micropython.org/viewtopic.php?t=4025
            except Exception as e:
                print('Error in main runloop')
                sys.print_exception(e)

            # Sleep for a while, then try to connect again
            # TODO Won't this cause the server to try to reconnect even when it is already connected?
            #      That fails when a new sever is started, because the port is already bound.
            await asyncio.sleep(self.settings.network_retry_timeout)

    def run(self):
        self.run_task = asyncio.create_task(self._run())

# A utility that takes a nested dictinary and returns a copy with
# all nested keys stored as key paths on the root
def flatten_dict(input_dict, output_dict = None, prefix = None):
    if output_dict is None:
        output_dict = {}
        
    for key, value in input_dict.items():
        if prefix is not None:
            key = prefix + '>' + key

        if type(value) is dict:
            flatten_dict(value, output_dict, key);
        else:
            output_dict[key] = value
            
    return output_dict
