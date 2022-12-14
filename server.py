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

_SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3])
_NTP_EPOCH = datetime.date(1900, 1, 1)
NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600


def system_to_ntp_time(timestamp):
# Combierte la hora a sistema NTP 
# y devuelve el tiempo correspondiente
    return timestamp + NTP_DELTA

def _to_int(timestamp):
# se le entrega el tiempo en formato NTP y devuelve la parte entera
    return int(timestamp)

def _to_frac(timestamp, n=32):
# se le entrega el tiempo en formato NTP y devuelve la parte fraccional
    return int(abs(timestamp - _to_int(timestamp)) * 2**n)

def _to_time(integ, frac, n=32):
# toma la parte entera y la parte fraccional 
# y devuelve la suma
    return integ + float(frac)/2**n	

class NTPException(Exception):
    pass

# Empaquetado y desempaquetado NTP    
class NTPPacket:
    _PACKET_FORMAT = "!B B B b 11I" # B = 1 byte = 8 bits, b = 1 byte = 8 bits 
    #                                 I = 4 bytes = 32 bits --> 11I = 352 bits 
    #                |||||||||||||
    #                vvvvvvvvvvvvv
    #           8 + 8 + 8 + 8 + 352 = 284 bits
    #Formato del paquete para hacer empaquetar y desempaquetar

    def __init__(self, version=2, mode=3, tx_timestamp=0):
# Constructor NTP, se predefine los valores, dejando
# leap 0, version 2, modo 3 y los demas todos 0
        self.leap = 0 # Leap
        self.version = version # Version
        self.mode = mode # Modo
        self.stratum = 0 # Stratum
        self.poll = 0 # Poll interval
        self.precision = 0 # Precision
        self.root_delay = 0 # Root delay
        self.root_dispersion = 0 # Root dispersion

        self.ref_id = 0 # Reference clock identifier
        self.ref_timestamp = 0 # Reference Timestamp
        
        self.orig_timestamp = 0 # Originate Timestamp
        self.orig_timestamp_high = 0 # Parte entera
        self.orig_timestamp_low = 0 # Parte fraccionaria
        
        self.recv_timestamp = 0 # Receive Timestamp

        self.tx_timestamp = tx_timestamp # Transmit Timestamp:
        self.tx_timestamp_high = 0 # Parte entera
        self.tx_timestamp_low = 0 # Parte Fraccionaria
        

    def to_data(self):
    # Tansforma el paquete a un archivo que se pueda enviar
    # y usa el NTPExeption cuando se usa un archivo que no corresponde al formato NTP
        try:
            packed = struct.pack(NTPPacket._PACKET_FORMAT,
                (self.leap << 6 | self.version << 3 | self.mode),
                # 00                 010               011   <----- (00010011)
                self.stratum,
                self.poll,
                self.precision,
                _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                _to_int(self.root_dispersion) << 16 |
                _to_frac(self.root_dispersion, 16),
                self.ref_id,
                _to_int(self.ref_timestamp),
                _to_frac(self.ref_timestamp),
                self.orig_timestamp_high,
                self.orig_timestamp_low,
                _to_int(self.recv_timestamp),
                _to_frac(self.recv_timestamp),
                _to_int(self.tx_timestamp),
                _to_frac(self.tx_timestamp))
        except struct.error:
            raise NTPException("Paquete invalido.")
        return packed

    def from_data(self, data):
    # Carga el paquete y lo "decodifica" para poder transformar la informacion
    # a datos con los que se puedan trabajar

        try:
            unpacked = struct.unpack(NTPPacket._PACKET_FORMAT,
                    data[0:struct.calcsize(NTPPacket._PACKET_FORMAT)])
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


# hilo de trabajo para la recepcion del paquete
class RecvThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print ("RecvThread Terminado")
                break
            rlist,wlist,elist = select.select([self.socket],[],[],1);
            if len(rlist) != 0:
                print ("Paquete %d Recivido" % len(rlist))
                for tempSocket in rlist:
                    try:
                        data,addr = tempSocket.recvfrom(1024)
                        #print (data)
                        recvTimestamp = recvTimestamp = system_to_ntp_time(time.time())
                        taskQueue.put((data,addr,recvTimestamp))
                    except socket.error:
                        print ("Error")

# hilo de trabajo para enviar el paquete devuelta al cliente
class WorkThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print ("WorkThread terminado")
                break
            try:
                data,addr,recvTimestamp = taskQueue.get(timeout=1)
                recvPacket = NTPPacket()
                recvPacket.from_data(data)
                timeStamp_high,timeStamp_low = recvPacket.GetTxTimeStamp()
                sendPacket = NTPPacket(version=3,mode=4)
                sendPacket.stratum = 2
                sendPacket.poll = 10
                sendPacket.ref_timestamp = recvTimestamp-5
                sendPacket.SetOriginTimeStamp(timeStamp_high,timeStamp_low)
                sendPacket.recv_timestamp = recvTimestamp
                sendPacket.tx_timestamp = system_to_ntp_time(time.time())
                socket.sendto(sendPacket.to_data(),addr)
                print ("enviado a %s:%d" % (addr[0],addr[1]))
            except queue.Empty:
                continue
                
        
localIP     = "192.168.1.108"
localPort   = 123
socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
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
        print ("Terminando proceso...")
        stopFlag = True
        recvThread.join()
        workThread.join()
        #socket.close()
        print ("Terminado")
        break
        
