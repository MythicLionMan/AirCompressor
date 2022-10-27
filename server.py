import uasyncio as asyncio
import machine
import network
import socket
import ujson
    
# Loosly based on https://gist.github.com/aallan/3d45a062f26bc425b22a17ec9c81e3b6
class Server:
    def __init__(self, settings, asynchronous):
        self.settings = settings
        self.asynchronous = asynchronous
        self.have_configured_wlan = False        
        
    def response_header(self, writer, status = 200, content_type = 'application/json'):
        writer.write('HTTP/1.0 {} OK\r\nContent-type: {}\r\n\r\n'.format(status, content_type))
    
    def return_json(self, writer, obj, status = 200):
        self.response_header(writer, status)
        # TODO I'd rather do this 'inline' without having to serialize to a string first, but
        #      ujson.dump() doesn't support uasyncio (which seems strange to me).
        writer.write(ujson.dumps(obj))
                
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

        if not wlan.isconnected():
            wlan = self.wlan
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
            # TODO Shouldn't this be finally
            except OSError as e:
                cl.close()
                print('connection closed')
                            
    async def _run(self):
        while True:
            try:
                print('Connecting to Network...')
                await self._configure_and_connect_to_network(0)
                
                print('Setting up webserver...')
                if self.asynchronous:
                    self.server = await asyncio.start_server(self.serve_client, "0.0.0.0", 80)
                else:
                    self._run_blocking()
                    print('Webserver is done. Bye bye.')
            except Exception as e:
                print(e)

            # Sleep for a while, then try to connect again
            await asyncio.sleep(self.settings.network_retry_timeout)

    def run(self):
        self.run_task = asyncio.create_task(self._run())
