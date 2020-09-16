from custom.helper import rule, getNow, getItemState, getHistoricItemState, getMaxItemState, postUpdate, postUpdateIfChanged, getItemLastUpdate, getItem
from core.triggers import CronTrigger, ItemStateChangeTrigger, ItemStateUpdateTrigger
from core.actions import Mqtt

from custom.model.sun import SunRadiation

import math

OFFSET_TEMPERATURE  = 1.1
OFFSET_HUMIDITY     = 0 #7.5  > 2020-09-16 10:29:23.698
OFFSET_WIND_DIRECTION = -135

OFFSET_NTC = -0.1

#http://www.conversion-website.com/power/Celsius-heat-unit-IT-per-minute-to-watt.html
CELSIUS_HEAT_UNIT = 31.6516756

#https://cdn.sparkfun.com/assets/3/9/d/4/1/designingveml6075.pdf
#UVA_RESPONSE_FACTOR = 0.001461
#UVB_RESPONSE_FACTOR = 0.002591
UVA_RESPONSE_FACTOR = 0.001461
UVB_RESPONSE_FACTOR = 0.002591

UVA_CORRECTION_FACTOR = 0.5 # behind glass
UVB_CORRECTION_FACTOR = 0.5 # behind glass

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
        else:
            level = getItemState("WeatherStation_Battery_Level").intValue()
      
        msg = u"";
        msg = u"{}{:.0f} %, ".format(msg,level)
        msg = u"{}{} mA".format(msg,getItemState("WeatherStation_Battery_Current").format("%.1f"))

        postUpdateIfChanged("WeatherStation_Battery_Message", msg)

@rule("sensor_weatherstation.py")
class WeatherstationRainHeaterRule:
    def __init__(self):
        self.triggers = [
            ItemStateUpdateTrigger("WeatherStation_Rain_Heater_Request")
        ]

    def execute(self, module, input):
        Mqtt.publish("mosquitto","mysensors-sub-1/1/4/1/0/2", u"{}".format(1 if getItemState("WeatherStation_Rain_Heater") == ON else 0));

@rule("sensor_weatherstation.py")
class WeatherstationRainRule:
    def __init__(self):
        self.triggers = [
            #CronTrigger("0/5 * * * * ?"),
            ItemStateUpdateTrigger("WeatherStation_Rain_Impulse"), # each count update must be used
            ItemStateChangeTrigger("WeatherStation_Rain_Rate"),
            ItemStateChangeTrigger("WeatherStation_Rain_Heater")
        ]

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Rain_Rate":
            rainRate = input['event'].getItemState().intValue()
            
            if rainRate <= 524:
                rainLevel = 10
            elif rainRate <= 1310:
                rainLevel = 9
            elif rainRate <= 3276:
                rainLevel = 8
            elif rainRate <= 8192:
                rainLevel = 7
            elif rainRate <= 20480:
                rainLevel = 6
            elif rainRate <= 51200:
                rainLevel = 5
            elif rainRate <= 128000:
                rainLevel = 4
            elif rainRate <= 320000:
                rainLevel = 3
            elif rainRate <= 800000:
                rainLevel = 2
            elif rainRate <= 2000000:
                rainLevel = 1
            else:
                rainLevel = 0

            postUpdateIfChanged("WeatherStation_Rain_State", rainLevel)
        else:
            rainLevel = getItemState("WeatherStation_Rain_State").intValue()
            
        if input['event'].getItemName() == "WeatherStation_Rain_Impulse" and input['event'].getItemState().intValue() > 0:
            zaehlerNeu = getItemState("WeatherStation_Rain_Counter").intValue()
            zaehlerNeu += input['event'].getItemState().intValue()
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
        else:
            todayRain = getItemState("WeatherStation_Rain_Daily").intValue()

        if rainLevel == 0:
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

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Wind_Direction_Raw":
            direction = input['event'].getItemState().intValue() + OFFSET_WIND_DIRECTION
            if direction > 360:
                direction -= 360
            elif direction < 0:
                direction += 360
            postUpdate("WeatherStation_Wind_Direction",direction)            
        else:
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

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_Temperature_Raw":
            temperature = round(input['event'].getItemState().doubleValue() + OFFSET_TEMPERATURE, 1)
            postUpdate("WeatherStation_Temperature",temperature)
            humidity = getItemState("WeatherStation_Humidity").intValue()
        else:
            temperature = getItemState("WeatherStation_Temperature").format("%.1f")
            humidity = int(round(input['event'].getItemState().doubleValue() + OFFSET_HUMIDITY))
            postUpdate("WeatherStation_Humidity",humidity)
      
        msg = u"";
        msg = u"{}{} °C, ".format(msg,temperature)
        msg = u"{}{}.0 %".format(msg,humidity)

        postUpdateIfChanged("WeatherStation_Air_Message", msg)

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

    def execute(self, module, input):
        if input['event'].getItemName() == "WeatherStation_UV_A_Raw":
            uva = input['event'].getItemState().doubleValue() * UVA_CORRECTION_FACTOR
            postUpdateIfChanged("WeatherStation_UV_A", uva)
            uvb = getItemState("WeatherStation_UV_B").doubleValue()
        else:
            uva = getItemState("WeatherStation_UV_A").doubleValue()
            uvb = input['event'].getItemState().doubleValue() * UVB_CORRECTION_FACTOR
            postUpdateIfChanged("WeatherStation_UV_B", uvb)
          
        uva_weighted = uva * UVA_RESPONSE_FACTOR;
        uvb_weighted = uvb * UVB_RESPONSE_FACTOR;
        uv_index = round( (uva_weighted + uvb_weighted) / 2.0, 1 );
        postUpdateIfChanged("WeatherStation_UV_Index", uv_index)
      
        msg = u"";
        msg = u"{}{} (".format(msg,uv_index)
        msg = u"{}{:.0f} • ".format(msg,round(uva))
        msg = u"{}{:.0f})".format(msg,round(uvb))

        postUpdateIfChanged("WeatherStation_UV_Message", msg)
