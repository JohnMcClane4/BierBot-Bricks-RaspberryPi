import requests
import logging
import sys
import time
import json
import yaml # reading the config
import os
import RPi.GPIO as GPIO 
from w1thermsensor import W1ThermSensor
from mcp9600 import MCP9600

from urllib.parse import urlencode
from urllib.request import Request, urlopen

from yaml.loader import SafeLoader

logging.basicConfig(filename='./bricks.log', filemode='w+', level=logging.INFO)
logging.getLogger().addHandler(logging.StreamHandler())

APIKEY = "tbd"
TYPE = "RaspberryPi"
CHIPID = "tbd"

# Open the file and load the file
config = {} # will hold the config from bricks.yaml and cache local relay states
with open('./bricks.yaml') as f:
    config = yaml.load(f, Loader=SafeLoader)
    logging.info("read config")
    
    APIKEY = config["apikey"]
    CHIPID = config["device_id"]
    TYPE = config["meta"]["platform"]
    
    logging.info(f"apikey={APIKEY}, device_id={CHIPID}, platform={TYPE}")
    

GPIO.setwarnings(False)
def initRelays():
    logging.info("setting GPIO to GPIO.BOARD")
    GPIO.setmode(GPIO.BOARD) 
    
    for i in range(0, len(config["relays"])):
        
        config["relays"][i]["state"] = 0
        gpio_number = config["relays"][i]["gpio"]
        logging.info(f"initializing relay {i+1} (GPIO {gpio_number})...")
        GPIO.setup(gpio_number, GPIO.OUT)
        GPIO.output(gpio_number, 0)
        
        
def setRelay(number=0, state=0):
    # number relay number in config
    # state: 0=off, 1=on
    config["relays"][number]["state"] = state
    gpio_number = config["relays"][number]["gpio"]
    logging.info(f"setting relay {number+1} (GPIO {gpio_number}) to {state}...")
    corrected_state = -1
    invert = config["relays"][number]["invert"]
    if invert:
        if state == 0:
            corrected_state = 1
        else:
            corrected_state = 0
        
        logging.info(f"inverted {state} to {corrected_state}")
    
    GPIO.output(gpio_number, corrected_state)
        
        
def getRelay(number=0):
    return config["relays"][number]["state"] # TODO: get from GPIO?

last_temps = {}

def getTemperature(sensor_type, sensor_id):
    if sensor_type == "w1":
        try:
            sensor = W1ThermSensor(sensor_id=sensor_id)
            temperature = sensor.get_temperature()
            last_temps[sensor_id] = temperature
        except:
            logging.error(f"Could not read temperature for w1 device {sensor_id}")
            if sensor_id in last_temps:
                temperature = last_temps[sensor_id]
            else:
                temperature = -42

    elif sensor_type =='mcp9600':
        
        try:
            device = MCP9600(i2c_addr=sensor_id)
        except RuntimeError:
            logging.error(f"Could not initialise mcp9600 device {sensor_id}")
        try:
            temperature = device.get_hot_junction_temperature()
        except:
            logging.error(f"Could not read temperature for mcp9600 device {sensor_id}")
            if sensor_id in last_temps:
                temperature = last_temps[sensor_id]
            else:
                temperature = -42
    return temperature


def request():

    logging.info("starting request");
    url = 'https://brewbricks.com/api/iot/v1'

    # craft request
    post_fields = {
        "type": TYPE,
        "brand": "oss",
        "version": "0.1",
        "chipid": CHIPID,
        "apikey": APIKEY
    } # baseline
    # add relay states to request
    for i in range(0, len(config["relays"])):
        key = f"a_bool_epower_{i}"
        value = getRelay(i)
        post_fields[key] = value
        logging.info(f"set relay {i} to {value}")
    
    # add temperatures to request
    temp_sensor_count = 0
    for sensor_type in ("w1", "mcp9600"):
        for i, sensor_id in enumerate(config[f"temperature_sensors_{sensor_type}"], start=temp_sensor_count):
            key = f"s_number_temp_{i}"
            temperature = getTemperature(sensor_type, sensor_id)
            value = str(temperature)
            post_fields[key] = value
            logging.info(f"set tempsensor {i} with id {sensor_id} to {temperature}")
            temp_sensor_count +=1

    response = requests.get(url, params=post_fields)
    
    try:
        if response.text == "internal.":
            logging.info("please activate RasberryPi under https://bricks.bierbot.com > Bricks")
            time.sleep(nextRequestMs / 1000)
        else:
            jsonResponse = json.loads(response.text)

            nextRequestMs = jsonResponse["next_request_ms"]

            # set relays based on response
            for i in range(0, len(config["relays"])):
                relay_key = f"epower_{i}_state"
                if (relay_key in jsonResponse):
                    # relay_key is e.g. "epower_0_state"
                    new_relay_state = int(jsonResponse[relay_key])
                    logging.info(f"received new target state {new_relay_state} for {relay_key}")
                    setRelay(i, new_relay_state)
                else:
                    logging.warning(f"relay key {relay_key} for relay idx={i} was expected but not in response. This is normal before activation.")
                    setRelay(i, 0)

            logging.info(f"sleeping for {nextRequestMs}ms")
            time.sleep(nextRequestMs / 1000)
    except:
        logging.warning("failed processing request: " + response.text)
        time.sleep(60)

def run():
    initRelays()

    while True:
        request()

if __name__ == '__main__':
    logging.info("BierBot Bricks RaspberryPi client started.")
    run()
