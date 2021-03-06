#!/usr/bin/python
# coding=utf-8
import serial
import SocketServer
import threading
import json

from prometheus_client import Gauge, Counter, start_http_server
s = Gauge('ini_door_state', 'Ini door open-1, closed-0')
c = Counter('ini_door_requests', 'Ini door requests')

class TCPRequestHandler(SocketServer.BaseRequestHandler):
    def __init__(self, callback, *args, **keys):
        self.callback = callback
        SocketServer.BaseRequestHandler.__init__(self, *args, **keys)

    def handle(self):
        c.inc()
        data = self.callback()
        print "request: " + data
        self.request.send(data)

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass


class TuerSensor(object):
    """Benutzt CTS und RTS Pin am Serielanschluss"""

    def __init__(self,port):
        self._s = serial.Serial( port=port)
        self._s.setRTS()

    def ist_offen(self):
        d_open = not self._s.getCTS()
        s.set( 1 if d_open else 0 )
        return d_open




class CafeServer(object):
    def __init__(self):
        port_tuer    = '/dev/ttyS0'

        self._tuer = TuerSensor(port=port_tuer)

        ## TCP Server starten
        # port CAFE, 51966
        HOST, PORT = "0.0.0.0", 0xCAFE
        self.server = ThreadedTCPServer((HOST, PORT), 
                lambda *args, **keys: TCPRequestHandler(
                cafeserver.getJson, *args, **keys))
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True

    def run(self):
        self.server_thread.start()
        self.server_thread.join()

    def getData(self):
        return {'tuer_offen':self._tuer.ist_offen()}

    def getJson(self):
        return json.dumps(self.getData())

    def shutdown(self):
        self.server.shutdown()
        self.server_thread.join()



#######################################################################
## Start
if __name__ == "__main__":
    start_http_server(0xCAFF)
    try:
        cafeserver = CafeServer()
        cafeserver.run()
    except KeyboardInterrupt:
        print "beenden..."
        cafeserver.shutdown()

