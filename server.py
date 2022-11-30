import datetime
import socket
import struct
import time
import queue
#import mutex
import threading
import select

taskQueue = queue.Queue()
stopFlag = False

#Para poder calcular la hora actual
_SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3])
#Sistema EPOCH
_NTP_EPOCH = datetime.date(1900, 1, 1)
#NTP Epoch
NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600
#Data entre sistema y tiempo NTP

def system_to_ntp_time(timestamp):
    #Convierte un tiempo de sistema a un tiempo NTP, parametros: Timestamp
    #Retorna: Correspondiente tiempo NTP
    return timestamp + NTP_DELTA

def _to_int(timestamp):
    #Retorna la parte entera de un Timestamp.
    #Parametros: Timestamp en formato NTP
    #Retorna Parte entera
    return int(timestamp)

def _to_frac(timestamp, n=32):
    #Retorna la parte fraccionaria de un Timestamp.
    #Parametros: Timestamp en formato NTP, n: numero de bits de la parte fraccionaria.
    #Retorna: Parte fraccionaria
    return int(abs(timestamp - _to_int(timestamp)) * 2**n)

def _to_time(integ, frac, n=32):
    #Retorna un Timestamp de la parte integral y fraccionaria.
    #Parametros: Parte ingregral, parte fraccionaria, n: numero de bits de la parte fraccionaria.
    return integ + float(frac)/2**n	
		


class NTPException(Exception):
    #Excepcion levantada por este modulo.
    pass


class NTPPacket:
    #Paquete de la clase NTP
    #Esto representa un paquete NTP
    _PACKET_FORMAT = "!B B B b 11I" # 32 bits I(Entero sin signo), 11I = I(32) * 11 = 352
    #Formato del paquete para hacer pack y unpack

    def __init__(self, version=2, mode=3, tx_timestamp=0):
        #Constructor
        #Parametros: version (NTP), mode, tx_timestamp(paquete de transmision timestamp)
        self.leap = 0
        #Segundo indicador del leap
        self.version = version
        #Version
        self.mode = mode
        #Modo
        self.stratum = 0
        #Stratum
        self.poll = 0
        #Invervalo del poll
        self.precision = 0
        #Precision
        self.root_delay = 0
        #Retraso de la raiz
        self.root_dispersion = 0
        #Dispersion de la raiz
        self.ref_id = 0
        #Identificador de referencia para el reloj
        self.ref_timestamp = 0
        #Timestamp de referencia
        self.orig_timestamp = 0
        self.orig_timestamp_high = 0
        self.orig_timestamp_low = 0
        #Originar timestamp
        self.recv_timestamp = 0
        #Recibe timestamp
        self.tx_timestamp = tx_timestamp
        self.tx_timestamp_high = 0
        self.tx_timestamp_low = 0
       
        
    def to_data(self):
        #Convierte este paquete NTP a un buffer que puede ser enviado a traves de un socket.
        #Retorna: Buffer representando este paquete.
        #Contiene una excepcion en caso de un campo invalido
        try:
            packed = struct.pack(NTPPacket._PACKET_FORMAT,
                (self.leap << 6 | self.version << 3 | self.mode),
                self.stratum,
                self.poll,
                self.precision,
#RFC define Timestamp define valores en 64 bits, tiene una parte entera y una parte fraccionaria, dividen los 64 bits en 2, 32 y 32, por eso son 11 eleme    ntos de 32 bits. 
                #Aca parten los 11 elementos de 32 bits

                _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                _to_int(self.root_dispersion) << 16 |
                _to_frac(self.root_dispersion, 16),
                self.ref_id,
                _to_int(self.ref_timestamp),
                _to_frac(self.ref_timestamp),
                #Change by lichen, avoid loss of precision
                self.orig_timestamp_high,
                self.orig_timestamp_low,
                _to_int(self.recv_timestamp),
                _to_frac(self.recv_timestamp),
                _to_int(self.tx_timestamp),
                _to_frac(self.tx_timestamp))
              #Terminan los 11 elementos de 32 bits

        except struct.error:
            raise NTPException("Invalid NTP packet fields.")
        return packed

    def from_data(self, data):
        
	#Rellena esta instancia de una carga util del paquete NTP recibido por la red.
        #Parametros: Data (buffer con carga util)
        #Contiene una excepcion en caso que el formato del paquete sea invalido.
        try:
            unpacked = struct.unpack(NTPPacket._PACKET_FORMAT,
                    data[0:struct.calcsize(NTPPacket._PACKET_FORMAT)]) #Arreglo de bytes que deberia recibir
        except struct.error:
            raise NTPException("Invalid NTP packet.")

        self.leap = unpacked[0] >> 6 & 0x3
        self.version = unpacked[0] >> 3 & 0x7
        self.mode = unpacked[0] & 0x7
        self.stratum = unpacked[1]
        self.poll = unpacked[2]
        self.precision = unpacked[3]
        self.root_delay = float(unpacked[4])/2**16
        self.root_dispersion = float(unpacked[5])/2**16
        self.ref_id = unpacked[6]
        self.ref_timestamp = _to_time(unpacked[7], unpacked[8])
        self.orig_timestamp = _to_time(unpacked[9], unpacked[10])
        self.orig_timestamp_high = unpacked[9]
        self.orig_timestamp_low = unpacked[10]
        self.recv_timestamp = _to_time(unpacked[11], unpacked[12])
        self.tx_timestamp = _to_time(unpacked[13], unpacked[14])
        self.tx_timestamp_high = unpacked[13]
        self.tx_timestamp_low = unpacked[14]

    def GetTxTimeStamp(self):
        return (self.tx_timestamp_high,self.tx_timestamp_low)

    def SetOriginTimeStamp(self,high,low):
        self.orig_timestamp_high = high
        self.orig_timestamp_low = low
        

class RecvThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print ("RecvThread Ended")
                break
            rlist,wlist,elist = select.select([self.socket],[],[],1);
            if len(rlist) != 0:
                print ("Received %d packets" % len(rlist))
                for tempSocket in rlist:
                    try:
                        data,addr = tempSocket.recvfrom(1024) #Recibe el socket, se cuelga el thread hasta que llegue el mensaje
                        recvTimestamp = recvTimestamp = system_to_ntp_time(time.time())
                        taskQueue.put((data,addr,recvTimestamp)) #Se usa una cola
                    except socket.error:
                        print ("Error")

class WorkThread(threading.Thread): #Prepara el mensaje de respuesta
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True: #Los threads de trabajo van a estar en un bucle infinito
            if stopFlag == True:
                print ("WorkThread Ended")
                break
            try:
                data,addr,recvTimestamp = taskQueue.get(timeout=1) #Se saca informacion de la cola
                recvPacket = NTPPacket() #Prepara el paquete de respuesta, el primer elemento de la cola va ser una tupla, de (datos,direccion,hora)
                recvPacket.from_data(data)
                timeStamp_high,timeStamp_low = recvPacket.GetTxTimeStamp()
                sendPacket = NTPPacket(version=3,mode=4)
                sendPacket.stratum = 2
                sendPacket.poll = 10 
                #Stratum = distancia entre el servidor a un reloj real en una jerarquia de computadores.
                '''
                sendPacket.precision = 0xfa
                sendPacket.root_delay = 0x0bfa
                sendPacket.root_dispersion = 0x0aa7
                sendPacket.ref_id = 0x808a8c2c
                '''
                sendPacket.ref_timestamp = recvTimestamp-5
                sendPacket.SetOriginTimeStamp(timeStamp_high,timeStamp_low)
                sendPacket.recv_timestamp = recvTimestamp
                sendPacket.tx_timestamp = system_to_ntp_time(time.time())
                socket.sendto(sendPacket.to_data(),addr)
                print ("Sended to %s:%d" % (addr[0],addr[1]))
            except queue.Empty:
                continue
                
        
localIP     = "127.0.0.1" #Se prepara el socket
localPort   = 20001
socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM) #Se usa protocolo UDP
socket.bind((localIP,localPort))
print ("local socket: ", socket.getsockname())
recvThread = RecvThread(socket)
recvThread.start()
workThread = WorkThread(socket)
workThread.start()

while True:
    try:
        time.sleep(0.5)
    except KeyboardInterrupt:
        print ("Exiting...")
        stopFlag = True
        recvThread.join()
        workThread.join()
        #socket.close()
        print ("Exited")
        break
        
