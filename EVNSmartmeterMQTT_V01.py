import serial
import time
from binascii import unhexlify
import sys
import string
from gurux_dlms.GXDLMSTranslator import GXDLMSTranslator
from bs4 import BeautifulSoup
from Cryptodome.Cipher import AES
from time import sleep
from gurux_dlms.TranslatorOutputType import TranslatorOutputType
import xml.etree.ElementTree as ET
import json
import os
import getopt

from datetime import datetime

try:
	configFile = open(os.path.dirname(os.path.realpath(__file__)) + '/config.json')
	config = json.load(configFile)
except:
	print("config.json file not found!")
	sys.exit(1)

verbose = 0
try:
    opts, args = getopt.getopt(sys.argv[1:],"v")
except getopt.GetoptError:
    print('test.py [-v]')
    sys.exit(2)
for opt, arg in opts:
    if opt == '-v':
        verbose = 1

# config Kontrolle
neededConfig = ['port', 'baudrate', 'printValue', 'useREST', 'evn_schluessel']
for conf in neededConfig:
    if conf not in config:
        print(conf + ' missing in config file!')
        sys.exit(3)

RESTneededConfig = ['RESTurl', 'RESTtoken']
if config['useREST']:
    for conf in RESTneededConfig:
        if conf not in config:
            print(conf + ' missing in config file!')
            sys.exit(4)


# Holt Daten von serieller Schnittstelle
def recv(serialIncoming):
    while True:
        data = serialIncoming.read_all()
        if data == '':
            continue
        else:
            break
        sleep(0.5)
    return data

# Konvertiert Signed Ints
def s16(value):
    val = int(value, 16)
    return -(val & 0x8000) | (val & 0x7fff)

def s8(value):
    val = int(value, 16)
    return -(val & 0x80) | (val & 0x7f)

# DLMS Blue Book Page 52
# https://www.dlms.com/files/Blue_Book_Edition_13-Excerpt.pdf
units = {
            27: "W", # 0x1b
            30: "Wh", # 0x1e
            33: "A", #0x21
            35: "V", #0x23
            255: "" # 0xff: no unit, unitless
}


# REST API
if config['useREST']:
    import requests

    
tr = GXDLMSTranslator()
ser = serial.Serial( port=config['port'],
         baudrate=config['baudrate'],
         bytesize=serial.EIGHTBITS,
         parity=serial.PARITY_NONE,
         stopbits=serial.STOPBITS_ONE
)

# Werte im XML File
octet_string_values = {}
octet_string_values['0100010800FF'] = 'WirkenergieP'
octet_string_values['0100020800FF'] = 'WirkenergieN'
octet_string_values['0100010700FF'] = 'MomentanleistungP'
octet_string_values['0100020700FF'] = 'MomentanleistungN'
octet_string_values['0100200700FF'] = 'SpannungL1'
octet_string_values['0100340700FF'] = 'SpannungL2'
octet_string_values['0100480700FF'] = 'SpannungL3'
octet_string_values['01001F0700FF'] = 'StromL1'
octet_string_values['0100330700FF'] = 'StromL2'
octet_string_values['0100470700FF'] = 'StromL3'
octet_string_values['01000D0700FF'] = 'Leistungsfaktor'

def evn_decrypt(frame, key, systemTitel, frameCounter):
    frame = unhexlify(frame)
    encryption_key = unhexlify(key)
    init_vector = unhexlify(systemTitel + frameCounter)
    cipher = AES.new(encryption_key, AES.MODE_GCM, nonce=init_vector)
    return cipher.decrypt(frame).hex()

count=0;

while 1:
    daten = ser.read(size=282).hex()    
    mbusstart = daten[0:8]
    frameLen=int("0x" + mbusstart[2:4],16)
    systemTitel = daten[22:38]
    frameCounter = daten[44:52]
    frame = daten[52:12+frameLen*2]
    if mbusstart[0:2] == "68" and mbusstart[2:4] == mbusstart[4:6] and mbusstart[6:8] == "68" :
        print("Daten ok")
    else:
        print("wrong M-Bus Start, restarting")
        sleep(2.5)
        ser.flushOutput()
        ser.close()
        ser.open()
        continue


    apdu = evn_decrypt(frame,config['evn_schluessel'],systemTitel,frameCounter)

    try:
        xml = tr.pduToXml(apdu,)
        #print("xml: ",xml)

        root = ET.fromstring(xml)
        found_lines = []
        momentan = []

        items = list(root.iter())
        for i, child in enumerate(items):
            if child.tag == 'OctetString' and 'Value' in child.attrib:
                value = child.attrib['Value']
                if value in octet_string_values.keys():
                    if ('Value' in items[i+1].attrib):
                        if value in ['0100010700FF', '0100020700FF']:
                            # special handling for momentanleistung
                            momentan.append(int(items[i+1].attrib['Value'], 16))
                        found_lines.append({'key': octet_string_values[value], 'value': int(items[i+1].attrib['Value'], 16)});

        #print(found_lines)

    except BaseException as err:
        print("Zeit: ", datetime.now())
        print("Fehler: ", format(err))
        continue
    
    count=count+1;
    if count>=5000:
        count=0;

    try:
        if len(momentan) == 2:
            found_lines.append({'key': 'Momentanleistung', 'value': momentan[0]-momentan[1]})

        for element in found_lines:
            if element['key'] == "WirkenergieP":
               WirkenergieP = element['value']/1000
            if element['key'] == "WirkenergieN":
               WirkenergieN = element['value']/1000

            if element['key'] == "MomentanleistungP":
               MomentanleistungP = element['value']
            if element['key'] == "MomentanleistungN":
               MomentanleistungN = element['value']

            if element['key'] == "SpannungL1":
               SpannungL1 = element['value']*0.1
            if element['key'] == "SpannungL2":
               SpannungL2 = element['value']*0.1
            if element['key'] == "SpannungL3":
               SpannungL3 = element['value']*0.1

            if element['key'] == "StromL1":
               StromL1 = element['value']*0.01
            if element['key'] == "StromL2":
               StromL2 = element['value']*0.01
            if element['key'] == "StromL3":
               StromL3 = element['value']*0.01

            if element['key'] == "Leistungsfaktor":
               Leistungsfaktor = element['value']*0.001
                        
        if config['printValue'] or verbose:
            print('Wirkenergie+: ' + str(WirkenergieP))
            print('Wirkenergie-: ' + str(WirkenergieN))
            print('Momentanleistung+: ' + str(MomentanleistungP))
            print('Momentanleistung-: ' + str(MomentanleistungN))
            print('Spannung L1: ' + str(SpannungL1))
            print('Spannung L2: ' + str(SpannungL2))
            print('Spannung L3: ' + str(SpannungL3))
            print('Strom L1: ' + str(StromL1))
            print('Strom L2: ' + str(StromL2))
            print('Strom L3: ' + str(StromL3))
            print('Leistungsfaktor: ' + str(Leistungsfaktor))
            print('Momentanleistung: ' + str(MomentanleistungP-MomentanleistungN))
            print()
            print()
        
        # REST API
        if config['useREST'] and count%3==0:
            dataStr='smartmeter,host=PIone '
            dataStr+='WirkenergieP='+str(WirkenergieP)
            dataStr+=',WirkenergieN='+str(WirkenergieN)
            dataStr+=',MomentanleistungP='+str(MomentanleistungP)
            dataStr+=',MomentanleistungN='+str(MomentanleistungN)
            dataStr+=',SpannungL1='+str(SpannungL1)
            dataStr+=',SpannungL2='+str(SpannungL2)
            dataStr+=',SpannungL3='+str(SpannungL3)
            dataStr+=',StromL1='+str(StromL1)
            dataStr+=',StromL2='+str(StromL2)
            dataStr+=',StromL3='+str(StromL3)
            dataStr+=',Leistungsfaktor='+str(Leistungsfaktor)

            if verbose:
                print(dataStr+"\n")

            url = config['RESTurl']

            Headers={'Authorization': 'Token ' + config['RESTtoken']}

            resp = requests.post(url, headers=Headers, data = dataStr)
            if resp.status_code != 200 and resp.status_code != 204:
                print('Error while sending to REST API:')
                print(dataStr)
                print('Status Code: ' + str(resp.status_code))
                print(resp.text)

            if verbose:
                print("HTTP Resp Code: " + str(resp.status_code) + "\n")
                print(resp.text)

    except BaseException as err:
        print("Zeit: ", datetime.now())
        print("Fehler: ", format(err))
        continue
    
