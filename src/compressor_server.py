import network
from server import ServerController
from server import flatten_dict
from compressor_controller import CompressorController
import debug

import ujson
import time
import sys

import uasyncio as asyncio

class CompressorServer(ServerController):
    def __init__(self, compressor, settings):
        ServerController.__init__(self, settings)
        self.compressor = compressor
        self.root_document = 'status.html'
        self.log_requests = settings.debug_mode & debug.DEBUG_WEB_REQUEST
    
    # Overloads the base class method to supply state and settings values
    # as substitutions for html documents. Other documents do not get
    # substitutions
    async def return_http_document(self, writer, path):
        if path.endswith('.html'):
            values = {}
            values.update(self.compressor.state_dictionary)
            values.update(self.settings.public_values_dictionary)

            values = flatten_dict(values);
        else:
            values = None
        
        await super().return_http_document(writer, path = path, substitutions = values)

    def return_ok(self, writer):
        self.return_json(writer, {'result':'ok'})
    
    async def serve_client(self, reader, writer):
        try:
            request_line = await reader.readline()

            # TODO Don't log every endpoint, only log serving pages (every endpoint gets chatty)
            headers = await self.read_headers(reader)
            (request_type, endpoint, parameters) = self.parse_request(request_line, log_request = self.log_requests)

            compressor = self.compressor
                
            if request_type == 'GET':
                if endpoint == '/settings':
                    if len(parameters) > 0:
                        try:
                            # settings are only updated from the main thread, so it is sufficient
                            # to rely on the individual locks in these two methods
                            self.settings.update(parameters)
                            self.settings.write_delta()
                            
                            self.return_json(writer, self.settings.public_values_dictionary)
                        except KeyError as e:
                            self.return_json(writer, {'result':'unknown key error', 'missing key': e}, 400)                    
                    else:
                        self.return_json(writer, self.settings.public_values_dictionary)
                
                # The rest of the commands only accept 0 - 2 parameters
                elif len(parameters) > 2:                
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                        
                elif endpoint == '/purge':
                    drain_duration = parameters.get("drain_duration", None)
                    if drain_duration:
                        drain_duration = int(drain_duration)

                    drain_delay = parameters.get("drain_delay", None)
                    if drain_delay:
                        drain_delay = int(drain_delay)

                    compressor.purge(drain_duration, drain_delay)
                    self.return_ok(writer)
                
                # The rest of the commands only accept 0 or 1 parameters
                elif len(parameters) > 1:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                        
                elif endpoint == '/activity_logs':
                    # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                    self.response_header(writer)
                    writer.write('{"time":' + str(time.time()) + ',"activity":[')
                    # The logs need to be locked so that they can be accessed. To prevent holding the lock
                    # for too long (which could block the compressor thread), the dump commands set blocking
                    # to False. But this will require the buffer to hold all of the data that is being sent,
                    # so it is a memory consumption risk.
                    
                    # Return all activity logs that end after since
                    await compressor.activity_log.dump(writer, int(parameters.get('since', 0)), 1, blocking = not compressor.thread_safe)
                    writer.write('],"commands":[')
                    # Return all command logs that fired after since
                    await compressor.command_log.dump(writer, int(parameters.get('since', 0)), blocking = not compressor.thread_safe)
                    writer.write(']}')
                elif endpoint == '/state_logs':
                    # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                    self.response_header(writer)
                    # The logs need to be locked so that they can be accessed. To prevent holding the lock
                    # for too long (which could block the compressor thread), the dump commands set blocking
                    # to False. But this will require the buffer to hold all of the data that is being sent,
                    # so it is a memory consumption risk.
                    writer.write('{"time":' + str(time.time()) + ',"maxDuration":' + str(compressor.state_log.max_duration) + ',"state":[')
                    await compressor.state_log.dump(writer, int(parameters.get('since', 0)), blocking = not compressor.thread_safe)
                    writer.write(']}')
                elif endpoint == '/on':
                    shutdown_time = parameters.get("shutdown_in", None)
                    if shutdown_time:
                        shutdown_time = int(shutdown_time)
                        
                    compressor.compressor_on(shutdown_time)
                    self.return_ok(writer)

                # The rest of the commands do not accept parameters
                elif len(parameters) > 0:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)
                elif endpoint == '/':
                    await self.return_http_document(writer, self.root_document)
                elif endpoint == '/status':
                    self.return_json(writer, compressor.state_dictionary)
                elif endpoint == '/run':
                    compressor.request_run()
                    self.return_ok(writer)
                elif endpoint == '/off':
                    compressor.compressor_off()
                    self.return_ok(writer)
                elif endpoint == '/pause':
                    compressor.pause()
                    self.return_ok(writer)
                else:
                    # Not an API endpoint, try to serve the requested document
                    # TODO Need to strip the leading '/' off of the endpoint to get the path
                    await self.return_http_document(writer, endpoint)
            elif request_type == 'POST':
                if len(parameters) > 0:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                
                elif endpoint == '/settings' and headers['Content-Type'] == 'application/json':
                    content_length = int(headers['Content-Length'])                    
                    raw_data = await reader.read(content_length)
                    parameters = ujson.loads(raw_data)

                    try:
                        # settings are only updated from the main thread, so it is sufficient
                        # to rely on the individual locks in these two methods
                        self.settings.update(parameters)
                        self.settings.write_delta()
                        
                        self.return_ok(writer)
                    except KeyError as e:
                        self.return_json(writer, {'result':'unknown key error', 'missing key': e}, 400)                        
                else:
                    self.return_json(writer, {'result':'unknown endpoint'}, 404)
            else:
                self.return_json(writer, {'result':'unknown method'}, 404)
        except Exception as e:
            print("Error handling request.")
            sys.print_exception(e)
        finally:
            await writer.drain()
            await writer.wait_closed()

