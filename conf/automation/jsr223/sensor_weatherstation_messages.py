from custom.helper import rule, getNow, getItemState, getStableItemState, getHistoricItemState, getMaxItemState, postUpdate, postUpdateIfChanged, getItemLastUpdate, getItem, startTimer, createTimer
from core.triggers import CronTrigger, ItemStateChangeTrigger, ItemStateUpdateTrigger
from core.actions import Mqtt
from custom.model.sun import SunRadiation

from org.joda.time import DateTime
import math

# base offset measured at 25°C
OFFSET_TEMPERATURE  = 1.1
# compensate heating from direct sunlight
# 1.1 °C negative temperature offset for each 20 °C diff between ntc and raw temperature
LAZY_OFFSET_TEMPERATURE  = 1.2
LAZY_OFFSET_REF_TEMPERATURE_DIFF = 10.0

OFFSET_WIND_DIRECTION = -135

OFFSET_NTC = -0.1

#http://www.conversion-website.com/power/Celsius-heat-unit-IT-per-minute-to-watt.html
#CELSIUS_HEAT_UNIT = 31.6516756
CELSIUS_HEAT_UNIT = 22

#https://cdn.sparkfun.com/assets/3/9/d/4/1/designingveml6075.pdf
#UVA_RESPONSE_FACTOR = 0.001461
#UVB_RESPONSE_FACTOR = 0.002591
UVA_RESPONSE_FACTOR = 0.001461
UVB_RESPONSE_FACTOR = 0.002591

UVA_CORRECTION_FACTOR = 0.5 # behind glass
UVB_CORRECTION_FACTOR = 0.5 # behind glass

DELAYED_UPDATE_TIMEOUT = 3

fuelLevel =[
  [ 3270, 0 ],
  [ 3610, 5 ],
  [ 3690, 10 ],
  [ 3710, 15 ],
  [ 3730, 20 ],
  [ 3750, 25 ],
  [ 3770, 30 ],
  [ 3790, 35 ],
  [ 3800, 40 ],
  [ 3820, 45 ],
  [ 3840, 50 ],
  [ 3850, 55 ],
  [ 3870, 60 ],
  [ 3910, 65 ],
  [ 3950, 70 ],
  [ 3980, 75 ],
  [ 4020, 80 ],
  [ 4080, 85 ],
  [ 4110, 90 ],
  [ 4150, 95 ],
  [ 4200, 100 ]
];

@rule("sensor_weatherstation.py")
class WeatherstationLastUpdateRule:
    def __init__(self):
        self.triggers = [
            CronTrigger("0 * * * * ?")
        ]

    def execute(self, module, input):
        now = getNow().getMillis()
        
        newestUpdate = 0
        oldestUpdate = now
        items = getItem("Weatherstation").getAllMembers()
        for item in items:
            _update = getItemLastUpdate(item).getMillis()
            if _update > newestUpdate:
                newestUpdate = _update
            if _update < oldestUpdate:
                oldestUpdate = _update
                #self.log.info("{} {}".format(item.getName(),getItemLastUpdate(item)))
        
        # Special handling for heating updates
        # Either the WeatherStation_Rain_Heater_Request is updated every 15 minutes (heating inactive) or every minute (heating is active)
        # Or the WeatherStation_Rain_Heater is updated every 5 minutes
        #_heaterValueUpdate = getItemLastUpdate("WeatherStation_Rain_Heater").getMillis()
        #_heaterRequestUpdate = getItemLastUpdate("WeatherStation_Rain_Heater_Request").getMillis()
        #_update = _heaterValueUpdate if _heaterValueUpdate > _heaterRequestUpdate else _heaterRequestUpdate
        #if _update > newestUpdate:
        #    newestUpdate = _update
        #if _update < oldestUpdate:
        #    oldestUpdate = _update
                
        newestUpdateInMinutes = (now - newestUpdate) / 1000.0 / 60.0
        newestUpdateInMinutes = round(newestUpdateInMinutes)
        newestUpdateInMinutesMsg = u"{:.0f}".format(newestUpdateInMinutes) if newestUpdateInMinutes >= 1 else u"<1"
        
        oldestUpdateInMinutes = (now - oldestUpdate) / 1000.0 / 60.0
        oldestUpdateInMinutes = round(oldestUpdateInMinutes)
        oldestUpdateInMinutesMsg = u"{:.0f}".format(oldestUpdateInMinutes) if oldestUpdateInMinutes >= 1 else u"<1"
        
        if newestUpdateInMinutesMsg != oldestUpdateInMinutesMsg:
            msg = u"{} bis {} min.".format(newestUpdateInMinutesMsg,oldestUpdateInMinutesMsg)
        else:
            msg = u"{} min.".format(newestUpdateInMinutesMsg)
            
        postUpdateIfChanged("WeatherStation_Update_Message", msg)
        postUpdateIfChanged("WeatherStation_Is_Working", ON if oldestUpdateInMinutes <= 12 else OFF)
        
@rule("sensor_weatherstation.py")
class WeatherstationBatteryRule:
    def __init__(self):
        self.triggers = [
            #CronTrigger("0/5 * * * * ?"),
            ItemStateChangeTrigger("WeatherStation_Battery_Voltage"),
            ItemStateChangeTrigger("WeatherStation_Battery_Current")
        ]
        self.updateTimer = None

    def delayUpdate(self):
        level = getItemState("WeatherStation_Battery_Level").intValue()
        current = getItemState("WeatherStation_Battery_Current").doubleValue()
            
        msg = u"";
        msg = u"{}{:.0f} %, ".format(msg,level)
        msg = u"{}{} mA".format(msg,getItemState("WeatherStation_Battery_Current").intValue())

        postUpdateIfChanged("WeatherStation_Battery_Message", msg)
        
        self.updateTimer = None

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Battery_Voltage":
            level = 0.0
            voltage = input['event'].getItemState().doubleValue()
            if voltage > fuelLevel[0][0]:
                if voltage > fuelLevel[-1][0]:
                    level = 100.0
                else:
                    for i in range(1,len(fuelLevel)):
                        toVoltageLevel = fuelLevel[i][0]

                        if voltage < toVoltageLevel:
                            fromVoltageLevel = fuelLevel[i-1][0]

                            toPercentageLevel = fuelLevel[i][1]
                            fromPercentageLevel = fuelLevel[i-1][1]
                            
                            # toVoltageLevel - fromVoltageLevel => 100%
                            # voltage - fromVoltageLevel => X
                            x = ( (voltage - fromVoltageLevel) * 100 ) / (toVoltageLevel - fromVoltageLevel)
                            
                            # toPercentageLevel - fromPercentageLevel => 100%
                            # ?? => x
                            level = int(round( ( ( x * (toPercentageLevel - fromPercentageLevel) ) / 100 ) + fromPercentageLevel ))
                            break
            postUpdateIfChanged("WeatherStation_Battery_Level", level)
         
        self.updateTimer = startTimer(DELAYED_UPDATE_TIMEOUT, self.delayUpdate, oldTimer = self.updateTimer, groupCount = len(self.triggers))
        
@rule("sensor_weatherstation.py")
class WeatherstationRainHeaterRule:
    def __init__(self):
        self.triggers = [
            ItemStateUpdateTrigger("WeatherStation_Rain_Heater_Request"),
            ItemStateChangeTrigger("WeatherStation_Rain_Heater")
        ]
        self.timer = None

    def disable(self):
        self.log.warn(u"Disable rain heater to avoid overheating")
        postUpdateIfChanged("WeatherStation_Rain_Heater",OFF)
        self.timer = None
        
    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Rain_Heater":
            if input['event'].getItemState() == OFF:
                if self.timer != None:
                    self.timer.cancel()
                    self.timer = None
        else:
            if getItemState("WeatherStation_Rain_Heater") == ON and self.timer == None:
                self.timer = createTimer(300,self.disable) # max 5 min
                self.timer.start()

            Mqtt.publish("mosquitto","mysensors-sub-1/1/4/1/0/2", u"{}".format(1 if getItemState("WeatherStation_Rain_Heater") == ON else 0));

@rule("sensor_weatherstation.py")
class WeatherstationRainRule:
    def __init__(self):
        self.triggers = [
            CronTrigger("0 0 0 * * ?"), # to reset daily counter at midnight
            ItemStateUpdateTrigger("WeatherStation_Rain_Impulse"), # each count update must be used
            ItemStateChangeTrigger("WeatherStation_Rain_Rate"),
            ItemStateChangeTrigger("WeatherStation_Rain_Heater")
        ]
        self.updateTimer = None

    def delayUpdate(self):
        todayRain = getItemState("WeatherStation_Rain_Daily").intValue()
        rainLevel = getItemState("WeatherStation_Rain_State").intValue()

        if rainLevel < 0:
            temperature = getItemState("WeatherStation_Temperature").doubleValue()
            rainState = "Tau" if temperature >= 0 else "Raureif"
        elif rainLevel == 0:
            rainState = "Trocken"
        elif rainLevel < 3:
            rainState = "Leicht"
        elif rainLevel < 6:
            rainState = "Mittel"
        elif rainLevel < 9:
            rainState = "Stark"
        else:
            rainState = "Extrem"
      
        msg = u"";
        msg = u"{}{}".format(msg,"{} mm, ".format(todayRain) if todayRain > 0 else "" )
        msg = u"{}{} ({}), ".format(msg,rainState,rainLevel)
        msg = u"{}{}".format(msg,"An" if getItemState("WeatherStation_Rain_Heater") == ON else "Aus" )

        postUpdateIfChanged("WeatherStation_Rain_Message", msg)
        
    def execute(self, module, input):
        if 'event' not in input:
            postUpdateIfChanged("WeatherStation_Rain_Daily", 0)
            self.delayUpdate()
        elif input['event'].getItemName() == "WeatherStation_Rain_Heater":
            self.delayUpdate()
        else:
            if input['event'].getItemName() == "WeatherStation_Rain_Impulse":
                impulseCount = input['event'].getItemState().intValue()
                
                if impulseCount == 0:
                    return
                  
                zaehlerNeu = getItemState("WeatherStation_Rain_Counter").intValue()
                zaehlerNeu += impulseCount
                postUpdateIfChanged("WeatherStation_Rain_Counter", zaehlerNeu)
                
                todayRain = 0
                zaehlerAlt = getHistoricItemState("WeatherStation_Rain_Counter", getNow().withTimeAtStartOfDay()).intValue()
                if zaehlerAlt != zaehlerNeu:
                    differenz = zaehlerNeu - zaehlerAlt
                    if differenz < 0:
                        differenz = zaehlerNeu

                    todayRain = float(differenz) * 295.0 / 1000.0
                    todayRain = round(todayRain,1)
                postUpdateIfChanged("WeatherStation_Rain_Daily", todayRain)
            elif input['event'].getItemName() == "WeatherStation_Rain_Rate":
                rateUpdate = input['event'].getItemState().intValue()
                
                if rateUpdate   <= 524:
                    rainLevel = 10
                elif rateUpdate   <= 1310:
                    rainLevel = 9
                elif rateUpdate   <= 3276:
                    rainLevel = 8
                elif rateUpdate   <= 8192:
                    rainLevel = 7
                elif rateUpdate   <= 20480:
                    rainLevel = 6
                elif rateUpdate   <= 51200:
                    rainLevel = 5
                elif rateUpdate   <= 128000:
                    rainLevel = 4
                elif rateUpdate   <= 320000:
                    rainLevel = 3
                elif rateUpdate   <= 800000:
                    rainLevel = 2
                elif rateUpdate   <= 2000000:
                    rainLevel = 1
                else:
                    rainLevel = 0                      
 
                if rainLevel > 0:
                    temperature = getItemState("WeatherStation_Temperature").doubleValue()
                    dewpoint = getItemState("WeatherStation_Dewpoint").doubleValue()
                    if temperature - dewpoint <= 3:
                        rainLevel = rainLevel * -1

                postUpdateIfChanged("WeatherStation_Rain_State", rainLevel)
                
            self.updateTimer = startTimer(DELAYED_UPDATE_TIMEOUT, self.delayUpdate, oldTimer = self.updateTimer, groupCount = len(self.triggers) - 1)

@rule("sensor_weatherstation.py")
class WeatherstationRainLastHourRule:
    def __init__(self):
        self.triggers = [CronTrigger("0 0 * * * ?")]

    def execute(self, module, input):
        zaehlerNeu = getItemState("WeatherStation_Rain_Counter").intValue()
        zaehlerAlt = getHistoricItemState("WeatherStation_Rain_Counter", getNow().minusHours(1)).intValue()
        lastHourRain = 0

        if zaehlerAlt != zaehlerNeu:
            differenz = zaehlerNeu - zaehlerAlt
            if differenz < 0:
                differenz = zaehlerNeu

            lastHourRain = float(differenz) * 295.0 / 1000.0
            #0.2794 mm

        postUpdateIfChanged("WeatherStation_Rain_Current", lastHourRain)
        
@rule("sensor_weatherstation.py")
class WeatherstationWindRule:
    def __init__(self):
        self.triggers = [
            #CronTrigger("0/5 * * * * ?"),
            ItemStateChangeTrigger("WeatherStation_Wind_Speed"),
            ItemStateChangeTrigger("WeatherStation_Wind_Direction_Raw")
        ]

        self.updateTimer = None

    def delayUpdate(self):
        direction = getItemState("WeatherStation_Wind_Direction").intValue()

        if direction >= 338 or direction < 23: 
             direction = u"Nord"
        elif direction < 68: 
            direction = u"Nordost"
        elif direction < 113: 
            direction = u"Ost"
        elif direction < 158: 
            direction = u"Südost"
        elif direction < 203: 
            direction = u"Süd"
        elif direction < 248: 
            direction = u"Südwest"
        elif direction < 293: 
            direction = u"West"
        elif direction < 338: 
            direction = u"Nordwest"
        
        msg = u""
        if getItemState("WeatherStation_Wind_Speed").doubleValue() == 0:
            msg = u"Ruhig"
        else:
            msg = u"{} km/h, {}".format(getItemState("WeatherStation_Wind_Speed").format("%.1f"),direction)

        postUpdateIfChanged("WeatherStation_Wind_Message", msg)

        self.updateTimer = None
        
    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Wind_Direction":
            direction = input['event'].getItemState().intValue() + OFFSET_WIND_DIRECTION
            if direction > 360:
                direction -= 360
            elif direction < 0:
                direction += 360
            postUpdate("WeatherStation_Wind_Direction",direction)            
          
        self.updateTimer = startTimer(DELAYED_UPDATE_TIMEOUT, self.delayUpdate, oldTimer = self.updateTimer, groupCount = len(self.triggers))
  
@rule("sensor_weatherstation.py")
class UpdateWindLast15MinutesRule:
    def __init__(self):
        self.triggers = [CronTrigger("0 */15 * * * ?")]

    def execute(self, module, input):
        value = getMaxItemState("WeatherStation_Wind_Speed", getNow().minusMinutes(15)).doubleValue()

        postUpdateIfChanged("WeatherStation_Wind_Current", value)
        
@rule("sensor_weatherstation.py")
class WeatherstationAirRule:
    def __init__(self):
        self.triggers = [
            ItemStateChangeTrigger("WeatherStation_Temperature_Raw"),
            ItemStateChangeTrigger("WeatherStation_Humidity_Raw")
        ]
        self.updateTimer = None
        self.temperatureUpdate = None
        
    def delayUpdate(self):
        #self.log.info(u">>> delayed: {} {}".format(self.temperatureUpdate != None,self.humidityUpdate != None))
      
        if self.temperatureUpdate != None:
            if self.temperatureUpdate > -100 and self.temperatureUpdate < 100:
                #temperature = round(input['event'].getItemState().doubleValue() + OFFSET_TEMPERATURE, 1)
                temperature = self.temperatureUpdate
                #self.log.info(u"Temp: {}".format(temperature))
                # +30000 because we want to give the last value more priority (30sec of 120sec total)
                diff = getStableItemState(DateTime(getNow().getMillis()+30000),"WeatherStation_Solar_Power",2) / CELSIUS_HEAT_UNIT
                if diff > 0:
                    offset = diff * LAZY_OFFSET_TEMPERATURE / LAZY_OFFSET_REF_TEMPERATURE_DIFF
                    temperature = temperature - offset
                    #self.log.info(u"New Temp: {} (diff: {}, offset: -{})".format(temperature, diff, offset))
                
                temperature = round(temperature + OFFSET_TEMPERATURE, 1)
                #self.log.info(u"New Temp: {} (offset: +{})".format(temperature, OFFSET_TEMPERATURE))
                
                postUpdate("WeatherStation_Temperature",temperature)
            else:
                self.log.warn(u"Fallback. Got wrong temperature value: {}".format(self.temperatureUpdate))
                temperature = round(getItemState("WeatherStation_Temperature").doubleValue(),1)
            self.temperatureUpdate = None
        else:
            temperature = round(getItemState("WeatherStation_Temperature").doubleValue(),1)

        humidity = getItemState("WeatherStation_Humidity").intValue()
      
        # https://rechneronline.de/barometer/taupunkt.php
        if temperature>0:
            k2=17.62
            k3=243.12
        else:
            k2=22.46
            k3=272.62
            
        #var erg=k3*((k2*t)/(k3+t)+Math.log(l/100))/((k2*k3)/(k3+t)-Math.log(l/100));
        dewpoint=k3*((k2*temperature)/(k3+temperature)+math.log(humidity/100.0))/((k2*k3)/(k3+temperature)-math.log(humidity/100.0))

        # https://www.corak.ch/service/taupunkt-rechner.html
        #ai=7.45;
        #bi=235;
        #z1=(ai*temperature)/(bi+temperature)
        #es=6.1*math.exp(z1*2.3025851)
        #e=es*humidity/100
        #z2=e/6.1
        #z3=0.434292289*math.log(z2)
        #dewpoint=(235*z3)/(7.45-z3)*100
        #dewpoint=math.floor(dewpoint)/100

        postUpdateIfChanged("WeatherStation_Dewpoint", round(dewpoint,1))
        
        msg = u"";
        msg = u"{}{} °C, ".format(msg,temperature)
        msg = u"{}{}.0 %".format(msg,humidity)

        postUpdateIfChanged("WeatherStation_Air_Message", msg)
        
        self.updateTimer = None

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Humidity_Raw":
            humidity = int(round(input['event'].getItemState().doubleValue()))
            if humidity >= 0 and humidity <= 100:
                postUpdate("WeatherStation_Humidity",humidity)
            else:
                self.log.warn(u"Fallback. Got wrong humidity value: {}".format(humidity))
        else:
            self.temperatureUpdate = input['event'].getItemState().doubleValue()
          
        # delay to take care of the latest WeatherStation_Solar_Power_Raw update
        self.updateTimer = startTimer(DELAYED_UPDATE_TIMEOUT, self.delayUpdate, oldTimer = self.updateTimer, groupCount = len(self.triggers))

@rule("sensor_weatherstation.py")
class SunPowerRule:
    def __init__(self):
        self.triggers = [
            ItemStateChangeTrigger("WeatherStation_Solar_Power_Raw")
        ]

    def execute(self, module, input):
        if getItemState("WeatherStation_Light_Level").intValue() > 500:
            solar_temperature = input['event'].getItemState().doubleValue() + OFFSET_NTC
            outdoor_temperature = getItemState("WeatherStation_Temperature").doubleValue()
            if solar_temperature < outdoor_temperature:
                postUpdateIfChanged("WeatherStation_Solar_Power", 0)
            else:
                diff = solar_temperature - outdoor_temperature
                power = diff * CELSIUS_HEAT_UNIT
                postUpdateIfChanged("WeatherStation_Solar_Power", round(power,1))
        else:
            postUpdateIfChanged("WeatherStation_Solar_Power", 0)
            
            
            
            
            
        azimut = getItemState("Sun_Azimuth").doubleValue()
        elevation = getItemState("Sun_Elevation").doubleValue()
        _usedRadians = math.radians(elevation)
        if _usedRadians < 0.0: _usedRadians = 0.0
        
        # http://www.shodor.org/os411/courses/_master/tools/calculators/solarrad/
        # http://scool.larc.nasa.gov/lesson_plans/CloudCoverSolarRadiation.pdf
        _maxRadiation = 990.0 * math.sin( _usedRadians ) - 30.0
        if _maxRadiation < 0.0: _maxRadiation = 0.0
        
        postUpdateIfChanged("WeatherStation_Solar_Power_Test2", _maxRadiation)

        # apply cloud cover
        _cloudCover = getItemState("Cloud_Cover_Current").doubleValue()
        if _cloudCover > 8.0: _cloudCover = 8.0
        _cloudCoverFactor = _cloudCover / 8.0
        _currentRadiation = _maxRadiation * ( 1.0 - 0.75 * math.pow( _cloudCoverFactor, 3.4 ) )
        
        postUpdateIfChanged("WeatherStation_Solar_Power_Test1", _currentRadiation)

        _messuredRadiation = getItemState("WeatherStation_Solar_Power").doubleValue()
        
        #self.log.info(u"SolarPower messured: {}, calculated: {}".format(_messuredRadiation,_currentRadiation))
            
#@rule("sensor_weatherstation.py")
#class SunPowerDebugRule:
#    def __init__(self):
#        self.triggers = [CronTrigger("*/5 * * * * ?")]
#
#    def execute(self, module, input):
#      
#        _currentRadiation = getItemState("WeatherStation_Solar_Power").doubleValue()
#
#        sunSouthRadiation, sunWestRadiation, sunDebugInfo = SunRadiation.getSunPowerPerHour(getNow(),getItemState("Cloud_Cover_Current").doubleValue())
#        self.log.info(u"Berechnet: {} {}".format(sunSouthRadiation, sunWestRadiation))
#        
#        sunSouthRadiation, sunWestRadiation, sunDebugInfo = SunRadiation.getSunPowerPerHour(getNow(),getItemState("Cloud_Cover_Current").doubleValue(),_currentRadiation)
#        self.log.info(u"Gemessen: {} {}".format(sunSouthRadiation, sunWestRadiation))
 
@rule("sensor_weatherstation.py")
class UVIndexRule:
    def __init__(self):
        self.triggers = [
            ItemStateChangeTrigger("WeatherStation_UV_A_Raw"),
            ItemStateChangeTrigger("WeatherStation_UV_B_Raw")
        ]

        self.updateTimer = None

    def delayUpdate(self):
        uva = getItemState("WeatherStation_UV_A").doubleValue()
        uvb = getItemState("WeatherStation_UV_B").doubleValue()
        
        uva_weighted = uva * UVA_RESPONSE_FACTOR;
        uvb_weighted = uvb * UVB_RESPONSE_FACTOR;
        uv_index = round( (uva_weighted + uvb_weighted) / 2.0, 1 );
        postUpdateIfChanged("WeatherStation_UV_Index", uv_index)
      
        msg = u"";
        msg = u"{}{} (".format(msg,uv_index)
        msg = u"{}{:.0f} • ".format(msg,round(uva))
        msg = u"{}{:.0f})".format(msg,round(uvb))

        postUpdateIfChanged("WeatherStation_UV_Message", msg)
        
        self.updateTimer = None

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_UV_A_Raw":
            uva = input['event'].getItemState().doubleValue() * UVA_CORRECTION_FACTOR
            postUpdateIfChanged("WeatherStation_UV_A", uva)
        else:
            uvb = input['event'].getItemState().doubleValue() * UVB_CORRECTION_FACTOR
            postUpdateIfChanged("WeatherStation_UV_B", uvb)
          
        self.updateTimer = startTimer(DELAYED_UPDATE_TIMEOUT, self.delayUpdate, oldTimer = self.updateTimer, groupCount = len(self.triggers))
