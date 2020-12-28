#!/usr/bin/python3
import logging
import math
import threading
import time
import RPi.GPIO as IO
import soco
import sys
from time import sleep

log = logging.getLogger("sonos")
log.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
#handler = logging.FileHandler('sonos.log')
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

ENCODER_PIN_A = 17
ENCODER_PIN_B = 27
ENCODER_PIN_SW = 22

ENCODER2_PIN_A = 14
ENCODER2_PIN_B = 15
ENCODER2_PIN_SW = 18

LED_KITCHEN = 21
LED_DINING = 16
LED_MOVE = 7

SWITCH1 = 10
OFFSWITCH = 20

kitchen = None
diningroom = None
move = None



STATUS = 12
IO.setmode(IO.BCM)

class BasicEncoder:
    # Just the encoder, no switch, no LEDs

    def __init__(self, a_pin, b_pin):
        self.a_pin = a_pin
        self.b_pin = b_pin

        IO.setmode(IO.BCM)
        IO.setup(self.a_pin, IO.IN, pull_up_down=IO.PUD_UP)
        IO.setup(self.b_pin, IO.IN, pull_up_down=IO.PUD_UP)

        self.last_delta = 0
        self.r_seq = self.rotation_sequence()

        self.steps_per_cycle = 4    # 4 steps between detents
        self.remainder = 0

    def rotation_sequence(self):
        a_state = IO.input(self.a_pin)
        b_state = IO.input(self.b_pin)
        r_seq = (a_state ^ b_state) | b_state << 1
        return r_seq

    # Returns offset values of -2,-1,0,1,2
    def get_delta(self):
        delta = 0
        r_seq = self.rotation_sequence()
        if r_seq != self.r_seq:
            delta = (r_seq - self.r_seq) % 4
            if delta==3:
                delta = -1
            elif delta==2:
                delta = int(math.copysign(delta, self.last_delta))  # same direction as previous, 2 steps

            self.last_delta = delta
            self.r_seq = r_seq

        return delta

    def get_cycles(self):
        self.remainder += self.get_delta()
        cycles = self.remainder // self.steps_per_cycle
        self.remainder %= self.steps_per_cycle # remainder always remains positive
        return cycles

    def get_switchstate(self):
        # BasicEncoder doesn't have a switch
        return 0

class SwitchEncoder(BasicEncoder):
    # Encoder with a switch

    def __init__(self, a_pin, b_pin, sw_pin):
        BasicEncoder.__init__(self, a_pin, b_pin)

        self.sw_pin = sw_pin
        IO.setup(self.sw_pin, IO.IN, pull_up_down=IO.PUD_DOWN)

    def get_switchstate(self):
        return IO.input(self.sw_pin)

class EncoderWorker(threading.Thread):
    def __init__(self, encoder):
        threading.Thread.__init__(self)
        self.lock = threading.Lock()
        self.stopping = False
        self.encoder = encoder
        self.daemon = True
        self.delta = 0
        self.delay = 0.001
        self.lastSwitchState = False
        self.upEvent = False
        self.downEvent = False

    def run(self):
        self.lastSwitchState = self.encoder.get_switchstate()
        while not self.stopping:
            delta = self.encoder.get_cycles()
            with self.lock:
                self.delta += delta

                self.switchstate = self.encoder.get_switchstate()
                if (not self.lastSwitchState) and (self.switchstate):
                    self.upEvent = True
                if (self.lastSwitchState) and (not self.switchstate):
                    self.downEvent = True
                self.lastSwitchState = self.switchstate
            time.sleep(self.delay)

    # get_delta, get_upEvent, and get_downEvent return events that occurred on
    # the encoder. As a side effect, the corresponding event will be reset.

    def get_delta(self):
        with self.lock:
            delta = self.delta
            self.delta = 0
        return delta

    def get_upEvent(self):
        with self.lock:
            delta = self.upEvent
            self.upEvent = False
        return delta

    def get_downEvent(self):
        with self.lock:
            delta = self.downEvent
            self.downEvent = False
        return delta


def get_player_statuses(kitchen, diningroom, move):    
        if kitchen != None:
            #IO.output(LED_KITCHEN, IO.LOW)
            kitchen_info = kitchen.get_current_transport_info()
            if kitchen_info['current_transport_state'] == "PLAYING":
                IO.output(LED_KITCHEN, IO.HIGH)
             
            else:
                IO.output(LED_KITCHEN, IO.LOW)
        else:
            IO.output(LED_KITCHEN, IO.LOW)
        
        if diningroom != None:
            #IO.output(LED_DINING, IO.LOW)
            dining_info = diningroom.get_current_transport_info()
            if dining_info['current_transport_state'] == "PLAYING":
                IO.output(LED_DINING, IO.HIGH)
            else:
                IO.output(LED_DINING, IO.LOW)
        else:
            IO.output(LED_DINING, IO.LOW)

        if move != None:
            #IO.output(LED_MOVE, IO.LOW)
            move_info = move.get_current_transport_info()
            if move_info['current_transport_state'] == "PLAYING":
                IO.output(LED_MOVE, IO.HIGH)
            else:
                IO.output(LED_MOVE, IO.LOW)
        else:
            IO.output(LED_MOVE, IO.LOW)

def volume_up(device):
    info = device.get_current_transport_info()
    if info['current_transport_state'] == "PLAYING":
        current_volume = device.volume
        device.volume = current_volume+2
        log.info("VOLUME UP - " + device.player_name + ": " + str(current_volume) + " -> " + str(current_volume +1))

def volume_down(device):
    info = device.get_current_transport_info()
    if info['current_transport_state'] == "PLAYING":
        current_volume = device.volume
        device.volume = current_volume-2
        log.info("VOLUME DOWN - " + device.player_name + ": " + str(current_volume) + " -> " + str(current_volume -1))

def stop(*devices):
    log.info("STOP all")
    for device in devices:
        try:
            device.volume = 8
        except:
            log.error("Can't set volume. ")

    coord = (x for x in devices if x.is_coordinator)
    for device in coord:
        device.stop()

def next_song(device):
    try:
        track = device.get_current_track_info()
        info = device.get_current_transport_info()
        if info['current_transport_state'] == "PLAYING":
            if "x-sonos-spotify" in track['metadata']:
                device.group.coordinator.next()
    except:
        print("uhoh")

def main_loop():
    
    
    IO.setup(STATUS, IO.OUT)
    IO.setup(LED_DINING, IO.OUT)
    IO.setup(LED_KITCHEN, IO.OUT)
    IO.setup(LED_MOVE, IO.OUT)
    IO.output(LED_KITCHEN, IO.LOW)
    IO.output(LED_DINING, IO.LOW)
    IO.output(LED_MOVE, IO.LOW)
    IO.output(STATUS, IO.HIGH)


    IO.output(LED_KITCHEN, IO.HIGH)
    sleep(0.5)
    IO.output(LED_KITCHEN, IO.LOW)
   
    IO.output(LED_DINING, IO.HIGH)
    sleep(0.5)
    IO.output(LED_DINING, IO.LOW)
   
    IO.output(LED_MOVE, IO.HIGH)
    sleep(0.5)
    IO.output(LED_MOVE, IO.LOW)
   
    IO.setup(SWITCH1, IO.IN, pull_up_down=IO.PUD_DOWN)
    IO.setup(OFFSWITCH, IO.IN, pull_up_down=IO.PUD_DOWN)

    soco.discovery.discover(timeout=1)
    kitchen = soco.discovery.by_name("Kitchen")
    diningroom = soco.discovery.by_name("Dining Room")
    move = soco.discovery.by_name("Sonos Move")
    log.info("Got sonos instances.")
    get_player_statuses(kitchen, diningroom, move)
    last_command_sent = ""

    encoder = EncoderWorker(SwitchEncoder(ENCODER_PIN_A, ENCODER_PIN_B, ENCODER_PIN_SW))
    encoder.start()

    encoder2 = EncoderWorker(SwitchEncoder(ENCODER2_PIN_A, ENCODER2_PIN_B, ENCODER2_PIN_SW))
    encoder2.start()
    
    value = 0
    lagger = 0
    try:
        while 1:
            
            delta = encoder.get_delta()
            if delta!=0:
                value = value + delta
                #print ("value", value)
                if delta > 0:
                    volume_up(diningroom)
                else:
                    volume_down(diningroom)

            if encoder.get_upEvent():  #button pressed - only one needed to execute command
                #print ("up!")
                next_song(diningroom)
            
            delta2 = encoder2.get_delta()
            if delta2!=0:
                value = value + delta2
                #print ("value", value)
                if delta2 > 0:
                    volume_up(kitchen)
                else:
                    volume_down(kitchen)

            if encoder2.get_upEvent():  #button pressed - only one needed to execute command
                print ("up2!")
                next_song(kitchen)
                #diningroom.group.coordinator.next()

            #if encoder.get_downEvent():
             #   print ("down!")
            
            if IO.input(SWITCH1) == IO.HIGH:  # play something (eg. MNM)
                print("Button pressed")
                if  last_command_sent != "MNM":
                    log.info("Switched to MNM")
                    last_command_sent = "MNM"
            
            if IO.input(OFFSWITCH) == IO.HIGH:  # play something (eg. MNM)
                print("OFF pressed")
                if  last_command_sent != "OFF":
                    log.info("Switched OFF")
                    # put volume back to 10 and shut off all sonos players
                    stop(kitchen,diningroom,move)
                    last_command_sent = "OFF"

            lagger+=1
            if lagger > 50:
                soco.discovery.discover(timeout=1)
                kitchen = soco.discovery.by_name("Kitchen")
                diningroom = soco.discovery.by_name("Dining Room")
                move = soco.discovery.by_name("Sonos Move")
                log.info("Refreshed sonos devices.")
                get_player_statuses(kitchen, diningroom, move)
                lagger = 0
            sleep(0.1)
                 
            
    except KeyboardInterrupt:
        log.info("Stopping...")
    except NameError:
        log.info("Stopping...")
    except:
        log.error("Generic error in main loop - " + str(vars(sys.exc_info()[0])))
    finally:
        IO.cleanup() 

if __name__ == "__main__":
 
    main_loop()
