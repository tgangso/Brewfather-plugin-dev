# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
from eventlet import Queue
from modules import cbpi, app, ActorBase

#gs
from modules.core.hardware import SensorActive, ActorBase
from modules.core.props import Property
from modules.steps import StepView
from modules.kettle import Kettle2View
import json
import os, re, threading, time
import requests

q = Queue()

def on_connect(client, userdata, flags, rc):
    print("BF MQTT Connected" + str(rc))

class BF_MQTT_Thread (threading.Thread):

    def __init__(self,server,port,username,password,tls,deviceid):
        threading.Thread.__init__(self)
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.tls = tls
        self.deviceid = deviceid

    client = None
    def run(self):
        self.client = mqtt.Client(self.deviceid)
        self.client.on_connect = on_connect

        if self.username != "username" and self.password != "password":
            self.client.username_pw_set(self.username, self.password)
        
        if self.tls.lower() == 'true':
            self.client.tls_set_context(context=None)

        self.client.connect(str(self.server), int(self.port), 60)
        self.client.loop_forever()

@cbpi.actor
class BF_MQTT_ControlObject(ActorBase):
    topic = Property.Text("Topic", configurable=True, default_value="cbpi/homebrewing/uuid/commands", description="MQTT TOPIC")
    object = Property.Text("Object", configurable=True, default_value="", description="Data Object, e.g. pump")
    def on(self, power=100):
        self.api.cache["mqtt"].client.publish(self.topic, payload=json.dumps({self.object: "on"}), qos=2, retain=True)

    def off(self):
        self.api.cache["mqtt"].client.publish(self.topic, payload=json.dumps({self.object: "off"}), qos=2, retain=True)

@cbpi.actor
class BF_MQTT_ActorInt(ActorBase):
    topic = Property.Text("Topic", configurable=True, default_value="", description="MQTT TOPIC")
    def on(self, power=100):
        self.api.cache["mqtt"].client.publish(self.topic, payload=1, qos=2, retain=True)

    def off(self):
        self.api.cache["mqtt"].client.publish(self.topic, payload=0, qos=2, retain=True)

@cbpi.sensor
class BF_MQTT_ListenerCommands(SensorActive):
    base_pump = Property.Actor(label="Pump Actor", description="Select the Pump actor you would like to control from Brewfather.")
    base_kettle = Property.Kettle(label="Kettle to control", description="Select the Kettle you would like to control from Brewfather.")
    base_heater = Property.Actor(label="Heater Actor", description="Select the heater actor whose power you would like to control from Brewfather.")
    
    last_value = None

    def init(self):
        self.commands_topic = self.get_config_parameter("BF_MQTT_COMMANDS_TOPIC", None) 
        self.events_topic = self.get_config_parameter("BF_MQTT_EVENTS_TOPIC", None)
        SensorActive.init(self)
        
        def on_message(client, userdata, msg):

            try:
                msg_decode=str(msg.payload.decode("utf-8","ignore"))
                msg_in=json.loads(msg_decode)

                print "=================================" 
                print("BF MQTT Data Received",msg_decode)
                print "=================================" 

                if "pump" in msg_in:
                    if msg_in["pump"] == "on":
                        requests.post("http://localhost:5000/api/actor/" + self.base_pump + "/switch/on")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "pump on"}), qos=1, retain=True)
                        print("Starting Pump")
                        #self.api.switch_actor_on(2)
                    if msg_in["pump"] == "off":
                        requests.post("http://localhost:5000/api/actor/" + self.base_pump + "/switch/off")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "pump auto"}), qos=1, retain=True)
                        print("Stopping Pump")
                        #self.api.switch_actor_off(2)

                if "start" in msg_in:
                    if msg_in["start"] == "auto":
                        self.kettle_auto = requests.get("http://localhost:5000/api/kettle/" + self.base_kettle)
                        if self.kettle_auto.json()["state"] == False:
                            requests.post("http://localhost:5000/api/kettle/" + self.base_kettle + "/automatic") 
                        print("Set kettle to automatic start") 
                
                if "recipe" in msg_in:
                    if msg_in["recipe"] == 1:
                        requests.post("http://localhost:5000/api/step/start")
                        requests.post("http://localhost:5000/api/step/action/start")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"time":0, "event": "recipe 1"}), qos=1, retain=True)
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"time":0, "event": "start"}), qos=1, retain=True) 
                        print("Step start")

                if "stop" in msg_in:
                    if msg_in["stop"] == True:
                        requests.post("http://localhost:5000/api/step/reset")
                        self.kettle_auto = requests.get("http://localhost:5000/api/kettle/" + self.base_kettle)
                        if self.kettle_auto.json()["state"] == True:
                            requests.post("http://localhost:5000/api/kettle/" + self.base_kettle + "/automatic")
                        requests.post("http://localhost:5000/api/actor/" + self.base_pump + "/switch/off")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "stop"}), qos=1, retain=True)
                        print("Stopping step")

                if "pause" in msg_in:
                    if msg_in["pause"] == True:
                        self.kettle_auto = requests.get("http://localhost:5000/api/kettle/" + self.base_kettle)
                        if self.kettle_auto.json()["state"] == True:
                            requests.post("http://localhost:5000/api/kettle/" + self.base_kettle + "/automatic")
                        requests.post("http://localhost:5000/api/actor/" + self.base_pump + "/switch/off")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "pause"}), qos=1, retain=True)
                    if msg_in["pause"] == False:
                        self.kettle_auto = requests.get("http://localhost:5000/api/kettle/" + self.base_kettle)
                        if self.kettle_auto.json()["state"] == False:
                            requests.post("http://localhost:5000/api/kettle/" + self.base_kettle + "/automatic")
                        requests.post("http://localhost:5000/api/actor/" + self.base_pump + "/switch/on")
                        self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "resume"}), qos=1, retain=True)

                if "mash SP" in msg_in:
                    self.settemp = str(msg_in["mash SP"])
                    requests.post("http://localhost:5000/api/kettle/" + self.base_kettle + "/targettemp/"  + self.settemp)
                    self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "_SP_"}), qos=1, retain=True)

                if "PWM" in msg_in:
                    self.pwm = str(msg_in["PWM"])
                    requests.post("http://localhost:5000/api/actor/"  + self.base_heater + "/power/" + self.pwm)
                    self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "_PWM_"}), qos=1, retain=True)

  #             if "countdown" in msg_in:
  #                 requests.post("http://localhost:5000/api/actor/"  + self.base_heater + "/power/" + msg_in["PWM"] )
  #                 self.api.cache["mqtt"].client.publish(self.events_topic, payload=json.dumps({"event": "_PWM_"}), qos=1, retain=True)

                #elif "stop" in msg_in:
                #    if msg_in["stop]" == "auto":
                #        print("St Brew, start = ",msg_in["start"])
                #    if msg_in["stop"] == "true":
                #        print("Stopping Brew, start = ",msg_in["start"])

            except Exception as e:
                print e
        
        #on_message.sensorid = self.id
        self.api.cache["mqtt"].client.subscribe(self.commands_topic)
        self.api.cache["mqtt"].client.message_callback_add(self.commands_topic, on_message)


#    def get_value(self):
#        # Control base actor from MQTT.
#        print "=== get_value ==="
#        print "self.last_value = "
#        print self.last_value 
#        print "msg_in ="
#        #print msg_in
        
#        if (self.last_value == "off") :
#                self.api.switch_actor_off(int(self.base_pump))
#                print "Pump2 OFF"
#        elif (self.last_value == "on") :
#                self.api.switch_actor_on(int(self.base_pump))
#                print "Pump2 ON"
#        return {"value": self.last_value}

 #   def get_unit(self):
 #       return self.unit

    def stop(self):
        self.api.cache["mqtt"].client.unsubscribe(self.commands_topic)
        SensorActive.stop(self)

    def execute(self):

        #deviceid = self.get_config_parameter("BF_MQTT_DEVICEID", None)
        #a_topic = self.get_config_parameter("BF_MQTT_DEVICEID", None)
        '''
        Active sensor has to handle his own loop
        :return:
        '''

        self.sleep(5)

@cbpi.backgroundtask(key='BFMQTT_DynamicMash', interval=1)                     # create bg job with an interval of 2.5 seconds 
def BFMQTT_DynamicMash_background_task(self):
    
    self.events_topic = cbpi.get_config_parameter("BF_MQTT_EVENTS_TOPIC", None)
    self.dynamicmash_topic = cbpi.get_config_parameter("BF_MQTT_DYNAMICMASH_TOPIC", None)
    #step = cbpi.cache.get("active_step")
   
    for idx, value in cbpi.cache["kettle"].iteritems():
        current_sensor_value = cbpi.get_sensor_value(value.sensor)
        self.kettlename = value.name
        self.target_temp = value.target_temp
        self.current_temp = current_sensor_value
        if value.state == True:
            self.mode = "auto"
        if value.state == False:
            self.mode = "manual"

    for idx, value in cbpi.cache["actors"].iteritems():
        if "pump" in value.name.lower():
            if value.state == 1:
                self.pump_state = "on"
            if value.state == 0:
                self.pump_state = "off"
        if "gheater" in value.name.lower():
            if value.state == 1:
                self.heater = value.power
            if value.state == 0:
                self.heater = "0"

    data = {                                                          # define the playload
    'time': 0,
    'countdown': 0,
    'countup': 0,
    'pump': self.pump_state,
    'SP': self.target_temp,
    'heater': self.heater,
    'mode': self.mode,
    'temp': self.current_temp,
    'unit': cbpi.get_config_parameter("unit", None) 
    } 
        
    self.cache["mqtt"].client.publish(self.dynamicmash_topic, payload=json.dumps(data), qos=1, retain=True)

@cbpi.initalizer(order=0)
def initBFMQTT(app):

    server = app.get_config_parameter("BF_MQTT_SERVER",None)
    if server is None:
        server = "localhost"
        cbpi.add_config_parameter("BF_MQTT_SERVER", "localhost", "text", "Brewfather MQTT Server")

    port = app.get_config_parameter("BF_MQTT_PORT", None)
    if port is None:
        port = "1883"
        cbpi.add_config_parameter("BF_MQTT_PORT", "1883", "text", "Brewfather MQTT Sever Port")

    username = app.get_config_parameter("BF_MQTT_USERNAME", None)
    if username is None:
        username = "username"
        cbpi.add_config_parameter("BF_MQTT_USERNAME", "username", "text", "Brewfather MQTT username")

    password = app.get_config_parameter("BF_MQTT_PASSWORD", None)
    if password is None:
        password = "password"
        cbpi.add_config_parameter("BF_MQTT_PASSWORD", "password", "text", "Brewfather MQTT password")

    tls = app.get_config_parameter("BF_MQTT_TLS", None)
    if tls is None:
        tls = "false"
        cbpi.add_config_parameter("BF_MQTT_TLS", "false", "text", "Brewfather MQTT TLS")

    deviceid = app.get_config_parameter("BF_MQTT_DEVICEID", None)
    if deviceid is None:
        deviceid = "deviceid"
        cbpi.add_config_parameter("BF_MQTT_DEVICEID", "***Enter Device ID***", "text", "Brewfather MQTT DeviceID")

    commands_topic = app.get_config_parameter("BF_MQTT_COMMANDS_TOPIC", None)
    if commands_topic is None:
        commands_topic = "cbpi/homebrewing/" + deviceid + "/commands"
        cbpi.add_config_parameter("BF_MQTT_COMMANDS_TOPIC", "cbpi/homebrewing/" + deviceid + "commands", "text", "Brewfather MQTT Commands Topic")

    events_topic = app.get_config_parameter("BF_MQTT_EVENTS_TOPIC", None)
    if events_topic is None:
        events_topic = "cbpi/homebrewing/" + deviceid + "/events/auto"
        cbpi.add_config_parameter("BF_MQTT_EVENTS_TOPIC", "cbpi/homebrewing/" + deviceid + "/events/auto", "text", "Brewfather MQTT Events Topic")

    dynamicmash_topic = app.get_config_parameter("BF_MQTT_DYNAMICMASH_TOPIC", None)
    if dynamicmash_topic is None:
        dynamicmash_topic = "cbpi/homebrewing/" + deviceid + "/dynamic/mash"
        cbpi.add_config_parameter("BF_MQTT_DYNAMICMASH_TOPIC", "cbpi/homebrewing/" + deviceid + "/dynamic/mash", "text", "Brewfather MQTT Dynamic Mash Topic")


    app.cache["mqtt"] = BF_MQTT_Thread(server,port,username, password, tls, deviceid)
    app.cache["mqtt"].daemon = True
    app.cache["mqtt"].start()
    
    def bfmqtt_reader(api):
        while True:
            try:
                m = q.get(timeout=0.1)
                #api.cache.get("sensors")[m.get("id")].instance.last_value = m.get("value")
                #api.receive_sensor_value(m.get("id"), m.get("value"))
            except:
                pass

    cbpi.socketio.start_background_task(target=bfmqtt_reader, api=app)
