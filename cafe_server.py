#!/usr/bin/python
# coding=utf-8
import serial
import sched
import re
import time
import SocketServer
import threading
import json
from serial.serialutil import SerialTimeoutException, SerialException
import os
from optparse import OptionParser
import termios


####################################################################### ## TCP Kommunikation
class TCPRequestHandler(SocketServer.BaseRequestHandler):
    def __init__(self, callback, *args, **keys):
        self.callback = callback
        SocketServer.BaseRequestHandler.__init__(self, *args, **keys)

    def handle(self):
        data = self.callback()
        print "request: " + data
        self.request.send(data)

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass

#######################################################################
## Serial

class Serial(object):
    def __init__(self,port):
        self._port = port
        self._ser = None


    def _startSer(self):
        if not self._ser or not self._ser.isOpen():
            try:
                print "versuche Ser zu initialisieren..."
                self._ser = serial.Serial(
                        port=self._port,timeout=0.2,writeTimeout=0.2)
                #self._ser.open()
                return True
            except SerialException:
                print "Fehler beim initialisieren der Ser Schnittstelle"
                self._clean()
            return False

    def _clean(self):
        if self._ser:
            self._ser.close()
        self._ser = None


    def get(self):
        if not self._ser:
            if not self._startSer():
                return ""
        try:
            self._ser.flushInput()
            self._ser.flushOutput()
            self._ser.write("GET\n")
            line = self._ser.readline()
            print "GET returned:", line
            return line
        except SerialException:
            self._clean()
            return ""
        except termios.error:
            self._clean()
            return ""


#######################################################################
## Sensoren

class Sensor(object):
    """Sensor mit Zwischenspeicher für letzten Wert"""
    _name = "Unbenannt"

    def __init__(self,name):
        self._name = name

    def getData(self):
        """gibt aktuelle Daten strukturiert zurück"""
        return None

    def update(self):
        """Aktualisiert Wert"""
        pass

    def save(self):
        """Speichert Wert in der DB"""
        pass

class TuerSensor(Sensor):
    """Benutzt CTS und RTS Pin am Serielanschluss"""

    def __init__(self,port):
        self._s = serial.Serial( port=port)
        self._s.setRTS()

    def ist_offen(self):
        return not self._s.getCTS()

class PotSensor(Sensor):
    """Benutzt Arduino Objekt"""
    def __init__(self,parser,index,minval,maxval):
        self._parser = parser
        self._index = index
        self._min = minval
        self._max = maxval


    def _get_pot_level(self,val):
        val_min = self._min
        val_max = self._max
        return round( 100* (val-val_min) / (val_max-val_min) )

    def getData(self):
        pots = self._parser.getCoffepots()
        if len(pots)-1 < self._index:
            return {'status':"Keine Info"}
        else:
            d = pots[self._index]['level']

        # mehr als Vollgewicht
        if d > self._max:
            d = self._max

        # weniger als Leergewicht
        if d < self._min:
            return {'status':"Kanne fehlt"}


        l=self._get_pot_level(d)

        # leer
        if l <1.0:
            return {'status':"Leer","level": 0}

        return {'status':"Vorhanden", 'level':l}


#######################################################################
## Datenaufbereitung

class ArduinoParser(object):
    """
    Parser für Werte, die vom Arduino empfangen werden

    die Methode parse(line) wird mit der empfangen Zeile aufgerufen,
    Die Werte können anschließend über die getX Methoden gelesen werden
    """

    def __init__(self):
        self._re = re.compile(
                r".*ACK pots:(?P<pots>(\[\d+,\d+\],?)+)"
                +" tueroffen:(?P<tueroffen>1|0) stat:(?P<status>\d+)")
        self._repot = re.compile (
                r"\[(?P<level>\d+),(?P<sd>\d+)\]")
        self.parse("")

    def _parsePots(self,pots):
        self._cofepots = []
        for match in self._repot.finditer(pots):
            # convert to int
            #only python >=2.7
            #res = {k:int(v) for k, v in match.groupdict().iteritems()}
            res =  dict((k,int(v)) for k,v in match.groupdict().iteritems())
            self._cofepots.append(res)


    def parse(self,line):
        """
        Parst *line* und Stellt Werte zur Verfügung

        return: bei Erfolg True, sonst False
        """
        match = self._re.match(line)
        print "parse '" , line, "'"
        if not match:
            self._cofepots = []
            self._tueroffen = False
            self._status = False
            print "parsen fehlgeschlagen"
            return False

        results = match.groupdict()
        self._parsePots(results['pots'])
        self._tueroffen = (results['tueroffen'] == "1")
        self._status = int(results['status'])
        print "parsen erfolgreich"
        return True

    def getCoffepots(self):
        return self._cofepots

    def getTueroffen(self):
        return self._tueroffen

    def getStatus(self):
        return self._status


#######################################################################
## Server

class CafeServer(object):
    """Hauptklasse"""
    

    def _startTCP(self):
        ## TCP Server starten
        # port CAFE, 51966
        HOST, PORT = "0.0.0.0", 0xCAFE
        self.server = ThreadedTCPServer((HOST, PORT), 
                lambda *args, **keys: TCPRequestHandler(
                cafeserver.getJson, *args, **keys))
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

    def __init__(self):
        """Erzeugt Sensoren und Quellen"""

        # TODO min,max für kannen aus datenbank lesen
        # TODO: minmax auf arduino prüfen, ggf ändern

        # ports aus settings lesen
        port_arduino = '/dev/ttyUSB0'
        port_tuer    = '/dev/ttyS0'

        self._port_arduino = port_arduino

        self._parser = ArduinoParser()
        self._coffepots = [
               PotSensor(parser=self._parser,index=0,minval=500,maxval=757),
               PotSensor(parser=self._parser,index=1,minval=2000,maxval=3200)]
        self._tuer = TuerSensor(port=port_tuer)

        self._startTCP()
        self._ser = Serial(port_arduino)

    def run(self):
        """ Startet Scheduler """
        self._schedluler = sched.scheduler(time.time, time.sleep)
        self._schedluler.enter(360, 2, self.record,())
        self._schedluler.enter(1,   1, self.update,())
        self._schedluler.run()

    def update(self):
        """Aktualisiert Werte und loggt ggf Fehler"""
        # sheduler aktualisieren
        self._schedluler.enter(1,   1, self.update,())

        print "werte erfassen"
        line = self._ser.get()
        if not self._parser.parse(line):
            print "Fehler"
            # TODO fehler loggen


    def record(self):
        """Loggen der Sensorwerte in der Datenbank"""
        self._schedluler.enter(360, 2, self.record,())
        # TODO
        print "record"

    def getPots(self):
        return [p.getData() for p in self._coffepots]

    def getData(self):
        return {'tuer_offen':self._tuer.ist_offen(), 'cafepots':self.getPots()}

    def getJson(self):
        return json.dumps(self.getData())

    def shutdown(self):
        self.server.shutdown()
        self.server_thread.join()



#######################################################################
## Start
if __name__ == "__main__":



    cafeserver = CafeServer()

    try:
        cafeserver.run()
    except KeyboardInterrupt:
        print "beenden..."
        cafeserver.shutdown()
