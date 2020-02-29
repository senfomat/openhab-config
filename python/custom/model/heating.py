# -*- coding: utf-8 -*-
import math

from custom.helper import getNow, getItemState, itemLastUpdateOlderThen, getItemLastUpdate, getStableItemState
from custom.model.sun import SunRadiation

from org.eclipse.smarthome.core.library.types import OnOffType
from org.eclipse.smarthome.core.library.types import OpenClosedType
from org.eclipse.smarthome.core.library.types import PercentType
from org.eclipse.smarthome.core.library.types import DecimalType

from custom.model.house import Window
from custom.model.state import RoomState, HouseState, RoomHeatingState, HouseHeatingState

class Heating(object):
    INFINITE_HEATING_TIME = 999.0 # const value for an invifinte heating time
    
    DEFAULT_NIGHT_REDUCTION = 2.0
    LAZY_OFFSET = 90 # Offset time until any heating has an effect
    MIN_HEATING_TIME = 15 # 'Heizen mit WW' should be active at least for 15 min.
    MIN_ONLY_WW_TIME = 15 # 'Nur WW' should be active at least for 15 min.
    MIN_REDUCED_TIME = 5
    MAX_REDUCTION_TIME = 60

    DENSITY_AIR = 1.2041
    C_AIR = 1.005

    # http://www.luftdicht.de/Paul-Luftvolumenstrom_durch_Undichtheiten.pdf
    LEAKING_N50 = 1.0
    LEAKING_E = 0.07
    LEAKING_F = 15.0
    
    # To warmup 1 liter of wather you need 4,182 Kilojoule
    # 1 Wh == 3,6 kJ
    # 1000 l * 4,182 kJ / 3,6kJ = 1161,66666667
    HEATING_REFERENCE_ENERGY = 1162 # per Watt je m³/K

    cloudCoverFC8Item = None
    cloudCoverFC4Item = None
    cloudCoverItem = None
    
    temperatureGardenFC8Item = None
    temperatureGardenFC4Item = None
    temperatureGardenItem = None
    
    ventilationFilterRuntimeItem = None
    ventilationLevelItem = None
    ventilationOutgoingTemperatureItem = None
    ventilationIncommingTemperatureItem = None
    
    heatingCircuitPumpSpeedItem = None
    heatingTemperaturePipeOutItem = None
    heatingTemperaturePipeInItem = None
    
    holidayStatusItem = None
    
    totalVolume = 0
    totalHeatingVolume = None
    
    temperatureSensorItemPlaceholder = u"Temperature_{}"
    temperatureTargetItemPlaceholder = u"Temperature_{}_Target"
    heatingBufferItemPlaceholder = u"Heating_{}_Charged"
    heatingCircuitItemPlaceholder = u"Heating_{}_Circuit"
    heatingTargetTemperatureItemPlaceholder = u"Heating_{}_Target_Temperature"
    heatingDemandItemPlaceholder = u"Heating_{}_Demand"

    lastRuntime = None
    
    rooms = []

    _roomsByName = {}
            
    _stableTemperatureReferences = {}

    # static status variables
    _forcedHeatings = {}
    
    @staticmethod
    def init(rooms):
        Heating.rooms = rooms

        for room in rooms:
            Heating._roomsByName[room.getName()] = room
    
        Heating.totalVolume = reduce( lambda x,y: x+y, map( lambda x: x.getVolume(), Heating.rooms ) )
        Heating.totalHeatingVolume = reduce( lambda x,y: x+y, map( lambda x: x.getHeatingVolume(), filter( lambda room: room.getHeatingVolume() != None, Heating.rooms) ) )
        
    @staticmethod
    def getRooms():
        return Heating.rooms
   
    @staticmethod
    def getRoom(roomName):
        return Heating._roomsByName[roomName]

    def __init__(self,log):
        self.log = log
        self.cache = {}
        self.now = getNow()
        
    def getTemperatureSensorItem(self,room):
        return self.temperatureSensorItemPlaceholder.format(room.getName())
      
    def getTemperatureTargetItem(self,room):
        return self.temperatureTargetItemPlaceholder.format(room.getName())
      
    def getHeatingBufferItem(self,room):
        return self.heatingBufferItemPlaceholder.format(room.getName())
      
    def getHeatingCircuitItem(self,room):
        return self.heatingCircuitItemPlaceholder.format(room.getName())
      
    def getHeatingTargetTemperatureItem(self,room):
        return self.heatingTargetTemperatureItemPlaceholder.format(room.getName())
      
    def getHeatingDemandItem(self,room):
        return self.heatingDemandItemPlaceholder.format(room.getName())

    def getCachedStableItemKey(self,itemName,stableSince=10):
        return u"stable-{}-{}".format(itemName,stableSince)
    
    def getCachedStableItemFloat(self,itemName,stableSince=10):
        return self.getCachedStableItemState(itemName,stableSince).floatValue()

    def getCachedStableItemState(self,itemName,stableSince=10):
        key = self.getCachedStableItemKey(itemName,stableSince)
        if key not in self.cache:
            self.cache[key] = DecimalType(getStableItemState(self.now,itemName, stableSince))
        return self.cache[key]

    def getCachedItemFloat(self,itemName):
        return self.getCachedItemState(itemName).floatValue()

    def getCachedItemState(self,itemName):
        if itemName not in self.cache:
            self.cache[itemName] = getItemState(itemName)
        return self.cache[itemName]
      
    def cachedItemLastUpdateOlderThen(self,itemName,minutes):
        key = u"update-{}-{}".format(itemName,minutes)
        if key not in self.cache:
            self.cache[key] = itemLastUpdateOlderThen( itemName, self.now.minusMinutes(minutes) )
        return self.cache[key]

    def getVentilationEnergy(self,tempDiffOffset):
        # *** Calculate power loss by ventilation ***
        _ventilationLevel = self.getCachedItemState(self.ventilationLevelItem).intValue()
        _ventilationTempDiff = self.getCachedItemFloat(self.ventilationOutgoingTemperatureItem) - self.getCachedItemFloat(self.ventilationIncommingTemperatureItem)
        
        # apply outdoor temperature changes to ventilation in / out difference
        if tempDiffOffset != 0:
            ventilationOffset = tempDiffOffset / 4
            if _ventilationTempDiff + ventilationOffset > 0:
                _ventilationTempDiff = _ventilationTempDiff + ventilationOffset
                    
        # Ventilation Energy
        # 15% => 40m/h		XX => ?
        # 100% => 350m/h		85 => 310
        _ventilationVolume = ( ( ( _ventilationLevel - 15.0 ) * 310.0 ) / 85.0 ) + 40.0
        _ventilationUValue = _ventilationVolume * self.DENSITY_AIR * self.C_AIR
        _ventilationEnergyInKJ = _ventilationUValue * _ventilationTempDiff
        return _ventilationEnergyInKJ * -1 if _ventilationEnergyInKJ != 0 else 0.0
    
    def getLeakingEnergy(self,volume, currentTemperature, outdoorTemperature):
        _leakingTemperatureDiff = currentTemperature - outdoorTemperature
        _leakingVolume = ( volume * self.LEAKING_N50 * self.LEAKING_E ) / ( 1 + ( self.LEAKING_F / self.LEAKING_E ) * ( ( ( 0.1 * 0.4 ) / self.LEAKING_N50 ) * ( ( 0.1 * 0.4 ) / self.LEAKING_N50 ) ) )
        _leakingUValue = _leakingVolume * self.DENSITY_AIR * self.C_AIR
        _leakingEnergyInKJ = _leakingUValue * _leakingTemperatureDiff
        return _leakingEnergyInKJ * -1 if _leakingEnergyInKJ != 0 else 0.0

    def getCoolingEnergy(self ,area, currentTemperature, type, bound):
        if type.getUValue() != None:
            referencedTemperaturItem = self.getTemperatureSensorItem(Heating.getRoom(bound)) if bound != None else Heating.temperatureGardenItem
            referenceTemperature = self.getCachedStableItemFloat(referencedTemperaturItem)
            temperatureDifference = currentTemperature - referenceTemperature
            coolingPerKelvin =( type.getUValue() + type.getUOffset() ) * area * type.getFactor()
            coolingTotal = coolingPerKelvin * temperatureDifference
            return coolingTotal * -1 if coolingTotal != 0 else 0.0
        else:
            return 0.0
        
    def calculateWallCoolingAndRadiations(self,currentTemperature,sunSouthRadiation,sunWestRadiation,walls):
        outdoorWallCooling = indoorWallCooling = outdoorWallRadiation = roomCapacity = 0
        for wall in walls:
            cooling = self.getCoolingEnergy(wall.getArea(),currentTemperature,wall.getType(),wall.getBound())
            if wall.getBound() == None:
                outdoorWallCooling = outdoorWallCooling + cooling
            else:
                indoorWallCooling = indoorWallCooling + cooling
            
            if wall.getBound() == None:
                if wall.getDirection() == 'south':
                    outdoorWallRadiation = outdoorWallRadiation + SunRadiation.getWallSunPowerPerMinute(wall.getArea(),sunSouthRadiation)
                elif wall.getDirection() == 'west':
                    outdoorWallRadiation = outdoorWallRadiation + SunRadiation.getWallSunPowerPerMinute(wall.getArea(),sunWestRadiation)

            capacity = ( wall.getArea() * wall.getType().getCapacity() ) / 3.6 # converting kj into watt

            roomCapacity = roomCapacity + capacity

        return indoorWallCooling, outdoorWallCooling, outdoorWallRadiation, roomCapacity
        
    def calculateWindowCoolingAndRadiations(self,currentTemperature,sunSouthRadiation,sunWestRadiation,transitions,wallCooling,isForecast):
        closedWindowEnergy = windowRadiation = openWindowCount = 0
        for transition in transitions:
            cooling = self.getCoolingEnergy(transition.getArea(),currentTemperature,transition.getType(),transition.getBound())
            closedWindowEnergy = closedWindowEnergy + cooling

            if transition.getContactItem() != None and self.getCachedItemState(transition.getContactItem()) == OpenClosedType.OPEN:
                if self.cachedItemLastUpdateOlderThen(transition.getContactItem(), 10 if isForecast else 2):
                    openWindowCount = openWindowCount + 1

            if isinstance(transition,Window) and transition.getRadiationArea() != None:
                _shutterOpen = (isForecast or transition.getShutterItem() == None or self.getCachedItemState(transition.getShutterItem()) == PercentType.ZERO)
                if _shutterOpen:
                    if transition.getDirection() == 'south':
                        windowRadiation = windowRadiation + SunRadiation.getWindowSunPowerPerMinute(transition.getRadiationArea(),sunSouthRadiation)
                    elif transition.getDirection() == 'west':
                        windowRadiation = windowRadiation + SunRadiation.getWindowSunPowerPerMinute(transition.getRadiationArea(),sunWestRadiation)
        
        openWindowEnergy = 0 if isForecast else wallCooling * openWindowCount
            
        return closedWindowEnergy, openWindowEnergy, windowRadiation, openWindowCount
          
    def calculatePossibleHeatingEnergy( self, isForecast ):
        temperatures = []
        for room in filter( lambda room: room.getHeatingVolume() != None,Heating.rooms):
            if isForecast or room.getHeatingVolume() == None or self.getCachedItemState( self.getHeatingCircuitItem(room) ) == OnOffType.ON:
                temperatures.append( self.getCachedStableItemFloat( self.getTemperatureSensorItem(room) ) )
        
        if len(temperatures) == 0:
            # Fallback is avg of all target temperatures
            for room in filter( lambda room: room.getHeatingVolume() != None,Heating.rooms):
                temperatures.append( self.getCachedItemFloat( self.getTemperatureTargetItem(room) ) )
            
        temperature_Pipe_In = reduce( lambda x,y: x+y, temperatures ) / len(temperatures) + 7.0
        
        # 0.3 steilheit
        # niveau 12k
        # 20° => 36°                => 0 => 0°
        # -20^ => 47°               => 40 => 11°
        
        currentOutdoorTemp = self.getCachedItemFloat( self.temperatureGardenItem )
        
        if currentOutdoorTemp > 20.0: 
            temperature_Pipe_Out = 36.0 * 0.95
        elif currentOutdoorTemp < -20.0:
            temperature_Pipe_Out = 47.0 * 0.95 
        else:
            temperature_Pipe_Out = ( ( ( ( currentOutdoorTemp - 20.0 ) * -1 ) * 11.0 / 40.0 ) + 36.0 ) * 0.95
            #test = ( ( ( ( currentOutdoorTemp - 20.0 ) * -1 ) * 11.0 / 40.0 ) + 36.0 ) * 0.9
            #self.log.info(u"-----> {}".format(test))
            #test = ( ( ( ( currentOutdoorTemp - 20.0 ) * -1 ) * 11.0 / 40.0 ) + 36.0 ) * 0.95
            #self.log.info(u"-----> {}".format(test))
                
        circulationDiff = temperature_Pipe_Out - temperature_Pipe_In
            
        pumpSpeed = 85.0
        
        return circulationDiff, pumpSpeed
    
    def calculateHeatingEnergy( self, isForecast ):
        power = self.getCachedItemState(self.heatingPower).intValue()
        pumpSpeed = self.getCachedItemState(self.heatingCircuitPumpSpeedItem).intValue()
        if power == 0 or pumpSpeed == 0 or isForecast: 
            circulationDiff = 0
            pumpSpeed = 0
            debugInfo = ""
            #Diff 9.1°C • VL 37.5°C • RL 28.4°C • 85.0% (FC)
            #self.log.info( u"Diff {}°C • VL {}°C • RL {}°C • {}% (FC)".format(round(circulationDiff,1),round(temperature_Pipe_Out,1),round(temperature_Pipe_In,1),pumpSpeed))
        else:
            temperature_Pipe_Out = self.getCachedItemFloat(self.heatingTemperaturePipeOutItem)
            temperature_Pipe_In = self.getCachedItemFloat(self.heatingTemperaturePipeInItem)
            circulationDiff = temperature_Pipe_Out - temperature_Pipe_In
            
            #Diff 9.6°C • VL 38.9°C • RL 29.3°C • 85% (0.42 m³)
            debugInfo = u"Diff {}°C • VL {}°C • RL {}°C • {}%".format(round(circulationDiff,1),round(temperature_Pipe_Out,1),round(temperature_Pipe_In,1),pumpSpeed)

        return circulationDiff, pumpSpeed, debugInfo

    def calculateHeatingRadiation( self, heatingVolumeFactor, roomHeatingVolume, circulationDiff, pumpSpeed ):

        if roomHeatingVolume != None:
            pumpVolume = ( roomHeatingVolume * heatingVolumeFactor * pumpSpeed ) / 100.0
            
            # pumpVolume / 1000.0 => convert liter => m³
            heatingEnergy = self.HEATING_REFERENCE_ENERGY * (pumpVolume / 1000.0) * circulationDiff
            
            return pumpVolume, heatingEnergy
        else:
            return 0.0, 0.0
          
    def calculateHeatingVolumeFactor(self,isForecast):
        activeHeatingVolume = 0
        
        for room in filter( lambda room: room.getHeatingVolume() != None,Heating.rooms):
            if isForecast or self.getCachedItemState( self.getHeatingCircuitItem(room) ) == OnOffType.ON:
                activeHeatingVolume = activeHeatingVolume + room.getHeatingVolume()
                
        # if all circuits are active => then 100% of Heating.totalHeatingVolume are possible
        # if 1% of the circuits area is active then 60.4% of self.totalHeatingVolume at 100%
        # if 10% of the circuits area is active then 64.0% of self.totalHeatingVolume at 100%
        # if 50% of the circuits area is active then 80.0% of self.totalHeatingVolume at 100%
        activeHeatingVolumeInPercent = ( activeHeatingVolume * 40.0 / Heating.totalHeatingVolume ) + 60.0
        
        return activeHeatingVolumeInPercent / 100.0
    
    def getOutdoorDependingReduction( self, coolingEnergy ):
        # more than zeor means cooling => no reduction
        if coolingEnergy <= 0: return 0.0

        # less than zero means - sun heating
        # 18000 Watt => 300 W/min => max reduction
        if coolingEnergy > 18000: return 2.0

        return ( coolingEnergy * 2.0 ) / 18000.0

    def calculateOutdoorReduction(self, coolingEnergy, coolingEnergyFC4, coolingEnergyFC8):
        # Current cooling should count full
        _outdoorReduction = self.getOutdoorDependingReduction(coolingEnergy)
        # Closed cooling forecast should count 90%
        _outdoorReductionFC4 = self.getOutdoorDependingReduction(coolingEnergyFC4) * 0.8
        # Cooling forecast in 8 hours should count 80%
        _outdoorReductionFC8 = self.getOutdoorDependingReduction(coolingEnergyFC8) * 0.6
        
        _outdoorReduction = _outdoorReduction + _outdoorReductionFC4 + _outdoorReductionFC8
        
        #self.log.info(u"{} {} {}".format(coolingEnergy,coolingEnergyFC4,coolingEnergyFC8))
        #self.log.info(u"{} {} {}".format(_outdoorReduction,_outdoorReductionFC4,_outdoorReductionFC8))
        
        #if _outdoorReduction > 0.0: _outdoorReduction = _outdoorReduction + 0.1
        
        return round( _outdoorReduction, 2 )
      
    def isNightModeTime(self,reference):
        day    = reference.getDayOfWeek()
        hour   = reference.getHourOfDay()
        minute = reference.getMinuteOfHour()

        _nightModeActive = False
        
        _holidaysActive = self.getCachedItemState(self.holidayStatusItem) == OnOffType.ON
        
        _isMorning = True if hour < 12 else False
        
        # Wakeup
        if _isMorning:
            # Monday - Friday
            if not _holidaysActive and day <= 5:
                if hour < 5:
                #if hour < 5 or ( hour == 5 and minute <= 30 ):
                    _nightModeActive = True
            # Saturday and Sunday
            else:
                if hour < 8:
                #if hour < 8 or ( hour == 8 and minute <= 30 ):
                    _nightModeActive = True
        # Evening
        else:
            # Monday - Thursday and Sunday
            if not _holidaysActive and day <= 4 or day == 7:
                if hour >= 22:
                #if hour >= 23 or ( hour == 22 and minute >= 30 ):
                    _nightModeActive = True
            # Friday and Saturday
            else:
                if hour >= 24:
                    _nightModeActive = True

        return _nightModeActive
      
    def isNightMode(self,isHeatingActive):
        if self.now.getHourOfDay() > 19:
            offset = self.LAZY_OFFSET
            if not isHeatingActive: 
                offset = offset + self.MIN_HEATING_TIME
            return self.isNightModeTime( self.now.plusMinutes( offset ) )
        
        if self.now.getHourOfDay() < 10:
            return self.isNightModeTime( self.now )
          
        return False
      
    def possibleColdFloorHeating(self,nightModeActive,lastHeatingChange):
      
        if self.now.minusMinutes(180).getMillis() < lastHeatingChange.getMillis():
            return False
          
        day = self.now.getDayOfWeek()
        hour = self.now.getHourOfDay()
        
        hadTodayHeating = lastHeatingChange.getDayOfWeek() == day

        isMorning = hour < 12 and nightModeActive
        hadMorningHeating = hadTodayHeating
        
        holidaysInactive = self.getCachedItemState(Heating.holidayStatusItem) == OnOffType.OFF
        minEveningHour = 17 if holidaysInactive and day <= 5 else 16
        isEvening = hour >= minEveningHour
        hadEveningHeating = hadTodayHeating and lastHeatingChange.getHourOfDay() >= minEveningHour
        
        #self.log.info(u"{} {} {} {}".format(isMorning,hadMorningHeating,isEvening,hadEveningHeating))
        
        return (isMorning and not hadMorningHeating) or (isEvening and not hadEveningHeating)
      
    '''def getColdFloorHeatingEnergy(self, lastUpdate, floorSlotHeatingEnergy ):
      
        # when was the last heating job
        lastUpdateBeforeInMinutes = ( self.now.getMillis() - lastUpdate.getMillis() ) / 1000.0 / 60.0
       
        booster = 70.0 if self.now.getHourOfDay() < 12 else 50.0
        
        # 0 => 0
        # 8 => 1
        factor = ( lastUpdateBeforeInMinutes / 60.0 ) / 8.0
        if factor > 1.0: factor = 1.0

        #https://rechneronline.de/funktionsgraphen/
        multiplier = ( math.pow( (factor-1), 2.0 ) * -1 ) + 1      #(x-1)^2*-1+1
        #multiplier = math.pow( (factor-1), 3.0 ) + 1              #(x-1)^3+1

        targetBufferChargeLevel = round( floorSlotHeatingEnergy * factor * booster, 1 )

        return round( targetBufferChargeLevel, 1 )'''

    def getColdFloorHeatingTime(self, lastUpdate ):
      
        # when was the last heating job
        lastUpdateBeforeInMinutes = ( self.now.getMillis() - lastUpdate.getMillis() ) / 1000.0 / 60.0
       
        maxMinutes = 90.0 if self.now.getHourOfDay() < 12 else 45.0
        
        # 0 => 0
        # 10 => 1
        factor = ( lastUpdateBeforeInMinutes / 60.0 ) / 10.0
        if factor > 1.0: factor = 1.0

        #https://rechneronline.de/funktionsgraphen/
        multiplier = ( math.pow( (factor-1), 2.0 ) * -1 ) + 1      #(x-1)^2*-1+1
        #multiplier = math.pow( (factor-1), 3.0 ) + 1              #(x-1)^3+1
    
        return ( maxMinutes * multiplier ) / 60.0

    def getCoolingAndRadiations(self,hours):
        isForecast = hours != 0
        
        time = self.now
        tempDiffOffset = 0
        
        if hours == 4:
            time = time.plusMinutes(240)
            # fill cache with forecast values
            self.cache[self.cloudCoverItem] = self.getCachedItemState(self.cloudCoverFC4Item)
            self.cache[self.temperatureGardenItem] = self.getCachedItemState(self.temperatureGardenFC4Item)
            tempDiffOffset = self.cache[u"org_{}".format(self.temperatureGardenItem)].floatValue() - self.getCachedItemFloat(self.temperatureGardenFC4Item)
        elif hours == 8:
            time = time.plusMinutes(480)
            # fill cache with forecast values
            self.cache[self.cloudCoverItem] = self.getCachedItemState(self.cloudCoverFC8Item)
            self.cache[self.temperatureGardenItem] = self.getCachedItemState(self.temperatureGardenFC8Item)
            tempDiffOffset = self.cache[u"org_{}".format(self.temperatureGardenItem)].floatValue() - self.getCachedItemFloat(self.temperatureGardenFC8Item)
        else:
            # fill cache with real values
            self.cache[self.cloudCoverItem] = self.cache[u"org_{}".format(self.cloudCoverItem)]
            self.cache[self.temperatureGardenItem] = self.cache[u"org_{}".format(self.temperatureGardenItem)]

        self.cache[self.getCachedStableItemKey(self.temperatureGardenItem)] = self.cache[self.temperatureGardenItem]
            
        possibleHeatingCirculationDiff, possibleHeatingPumpSpeed = self.calculatePossibleHeatingEnergy(isForecast)
        heatingCirculationDiff, heatingPumpSpeed, heatingDebugInfo = self.calculateHeatingEnergy(isForecast)
        heatingVolumeFactor = self.calculateHeatingVolumeFactor(isForecast)
        
        currentTotalVentilationEnergy = self.getVentilationEnergy(tempDiffOffset) / 3.6 # converting kj into watt
        sunSouthRadiation, sunWestRadiation, sunDebugInfo = SunRadiation.getSunPowerPerMinute(time,round(self.getCachedItemFloat(self.cloudCoverItem),1))
        
        totalOpenWindowCount = 0
        
        totalIndoorWallEnergy = 0
        totalOutdoorWallEnergy = 0
        totalOutdoorWallRadiation = 0
        totalVentilationEnergy = 0
        totalLeakEnergy = 0
        totalWindowEnergy = 0
        totalWindowRadiation = 0
        
        totalHeatingVolume = 0
        totalHeatingRadiation = 0
        totalPossibleHeatingVolume = 0
        totalPossibleHeatingRadiation = 0
        
        totalBufferCapacity = 0
        
        states = {}

        for room in Heating.rooms:            
            currentTemperature = self.getCachedStableItemFloat(self.getTemperatureSensorItem(room))
                          
            # *** WALL COOLING AND RADIATION ***
            indoorWallEnergy, outdoorWallEnergy, outdoorWallRadiation, roomCapacity = self.calculateWallCoolingAndRadiations(currentTemperature,sunSouthRadiation,sunWestRadiation,room.getWalls())

            # *** WINDOW COOLING AND RADIATION ***
            closedWindowEnergy, openWindowEnergy, windowRadiation, openWindowCount = self.calculateWindowCoolingAndRadiations(currentTemperature,sunSouthRadiation,sunWestRadiation,room.getTransitions(),outdoorWallEnergy,isForecast)
            outdoorWallEnergy = outdoorWallEnergy + closedWindowEnergy
            
            if room.getHeatingVolume() != None:
                # *** HEATING RADIATION ***
                if heatingPumpSpeed == 0 or self.getCachedItemState( self.getHeatingCircuitItem(room) ) != OnOffType.ON:
                    heatingVolume, heatingRadiation = 0.0, 0.0
                else:
                    heatingVolume, heatingRadiation = self.calculateHeatingRadiation(heatingVolumeFactor, room.getHeatingVolume(), heatingCirculationDiff, heatingPumpSpeed)
                
                possibleHeatingVolume, possibleHeatingRadiation = self.calculateHeatingRadiation(1.0, room.getHeatingVolume(), possibleHeatingCirculationDiff, possibleHeatingPumpSpeed)
            else:
                heatingVolume, heatingRadiation = 0.0, 0.0
                possibleHeatingVolume, possibleHeatingRadiation = 0.0, 0.0

            #self.log.info(u"{} {} {}".format(room.getName(),possibleHeatingRadiation))
            #self.log.info(u"{} {} {} {} {}".format(room.getName(),possibleHeatingVolume,possibleHeatingRadiation,heatingVolumeFactor,room.getHeatingVolume()))

            # *** VENTILATION COOLING ***
            ventilationEnergy = room.getVolume() * currentTotalVentilationEnergy / Heating.totalVolume
            leakEnergy = self.getLeakingEnergy(room.getVolume(),currentTemperature,self.getCachedItemFloat(self.temperatureGardenItem)) / 3.6 # converting kj into watt
            
            #self.log.info(u"{} {} {}".format(room.getName(),ventilationEnergy,leakEnergy))
                
            # summarize room values
            totalOpenWindowCount = totalOpenWindowCount + openWindowCount
            totalBufferCapacity = totalBufferCapacity + roomCapacity
            totalIndoorWallEnergy = totalIndoorWallEnergy + indoorWallEnergy
            totalOutdoorWallEnergy = totalOutdoorWallEnergy + outdoorWallEnergy
            totalOutdoorWallRadiation = totalOutdoorWallRadiation + outdoorWallRadiation
            totalVentilationEnergy = totalVentilationEnergy + ventilationEnergy
            totalLeakEnergy = totalLeakEnergy + leakEnergy
            totalWindowEnergy = totalWindowEnergy + openWindowEnergy
            totalWindowRadiation = totalWindowRadiation + windowRadiation
            totalHeatingVolume = totalHeatingVolume + heatingVolume
            totalHeatingRadiation = totalHeatingRadiation + heatingRadiation
            totalPossibleHeatingVolume = totalPossibleHeatingVolume + possibleHeatingVolume
            totalPossibleHeatingRadiation = totalPossibleHeatingRadiation + possibleHeatingRadiation

            # set room values
            roomState = RoomState()
            roomState.setName(room.getName())

            roomState.setOpenWindowCount(openWindowCount)

            roomState.setBufferCapacity(roomCapacity)

            roomState.setIndoorWallEnergy(indoorWallEnergy)
            roomState.setOutdoorWallEnergy(outdoorWallEnergy)
            roomState.setOutdoorWallRadiation(outdoorWallRadiation)
            roomState.setVentilationEnergy(ventilationEnergy)
            roomState.setLeakEnergy(leakEnergy)
            roomState.setWindowEnergy(openWindowEnergy)
            roomState.setWindowRadiation(windowRadiation)

            roomState.setHeatingVolume(heatingVolume)
            roomState.setHeatingRadiation(heatingRadiation)
            roomState.setPossibleHeatingVolume(possibleHeatingVolume)
            roomState.setPossibleHeatingRadiation(possibleHeatingRadiation)
            
            roomState.setCurrentTemperature(currentTemperature)

            states[room.getName()] = roomState

        # set house values
        houseState = HouseState()
        houseState.setRoomStates(states)
        houseState.setReferenceTemperature(self.getCachedItemFloat(self.temperatureGardenItem))

        houseState.setOpenWindowCount(totalOpenWindowCount)

        houseState.setBufferCapacity(totalBufferCapacity)

        houseState.setIndoorWallEnergy(totalIndoorWallEnergy)
        houseState.setOutdoorWallEnergy(totalOutdoorWallEnergy)
        houseState.setOutdoorWallRadiation(totalOutdoorWallRadiation)
        houseState.setVentilationEnergy(totalVentilationEnergy)
        houseState.setLeakEnergy(totalLeakEnergy)
        houseState.setWindowEnergy(totalWindowEnergy)
        houseState.setWindowRadiation(totalWindowRadiation)

        houseState.setHeatingPumpSpeed(heatingPumpSpeed)
        houseState.setHeatingVolume(totalHeatingVolume)
        houseState.setHeatingRadiation(totalHeatingRadiation)
        houseState.setPossibleHeatingVolume(totalPossibleHeatingVolume)
        houseState.setPossibleHeatingRadiation(totalPossibleHeatingRadiation)
        houseState.setHeatingVolumeFactor(heatingVolumeFactor)
        houseState.setHeatingDebugInfo(heatingDebugInfo)

        houseState.setSunSouthRadiation(sunSouthRadiation)
        houseState.setSunWestRadiation(sunWestRadiation)
        houseState.setSunDebugInfo(sunDebugInfo)

        return houseState
        
    def getHeatingDemand(self,room,rs,outdoorReduction,nightReduction,isHeatingActive):
      
        hs = RoomHeatingState()
        hs.setName(room.getName())

        for transition in room.getTransitions():
            if transition.getContactItem() != None and self.getCachedItemState(transition.getContactItem()) == OpenClosedType.OPEN:
                if self.cachedItemLastUpdateOlderThen(transition.getContactItem(), 10):
                    hs.setHeatingDemandEnergy(-1)
                    break
        
        hs.setNightReduction(nightReduction)
        hs.setOutdoorReduction(outdoorReduction)
        
        currentTemperature = round(self.getCachedStableItemFloat(self.getTemperatureSensorItem(room)),1)

        # set active target temperature to room state
        targetTemperature = self.getCachedItemFloat(self.getTemperatureTargetItem(room)) - nightReduction - outdoorReduction
        hs.setHeatingTargetTemperature(round(targetTemperature,1))
        
        charged = rs.getChargedEnergy()
        
        # check for upcoming charge level changes => see "charge level changes" for the final one
        if room.getName() in Heating._stableTemperatureReferences:
            _lastTemp = Heating._stableTemperatureReferences[room.getName()]
            if currentTemperature > _lastTemp and charged > 0:
                charged = self.adjustChargeLevel(rs,currentTemperature,_lastTemp,charged)
                if charged < 0.0: charged = 0.0
                hs.setAdjustedHeatingBuffer(charged)
            
        if hs.getHeatingDemandEnergy() == -1:
            hs.setInfo("WINDOW")
        else:
            missingDegrees = targetTemperature - currentTemperature
            
            #self.log.info("{} {} {} {}".format(room.getName(),currentTemperature,outdoorReduction,missingDegrees))

            if missingDegrees < 0:
                hs.setInfo("WARM")
            else:                
                # 75% of 0.1°C
                maxBuffer = rs.getBufferSlotCapacity() * 0.75

                if missingDegrees > 0:
                    hs.setInfo("COLD")
                    
                    possibleDegrees = charged / rs.getBufferCapacity()
                    # We have more energy then needed. Means we already fill the buffer
                    if possibleDegrees - missingDegrees > 0:
                        lazyReduction = missingDegrees
                        charged = charged - ( missingDegrees * rs.getBufferCapacity() )
                        missingDegrees = 0
                    # We need more energy
                    else:
                        lazyReduction = possibleDegrees
                        charged = 0
                        # Needed energy for the missing lazy energy + the upcoming charging of the buffer 
                        neededEnergy = ( ( missingDegrees - possibleDegrees ) * rs.getBufferCapacity() ) + maxBuffer
                        neededTime = self.calculateHeatingDemandTime(neededEnergy,rs.getActivePossibleSaldo())
                        hs.setHeatingDemandEnergy(neededEnergy)
                        hs.setHeatingDemandTime(neededTime)
                        
                    hs.setLazyReduction(round(lazyReduction,2))

                if missingDegrees == 0:
                    #self.log.info(u"{} {} {}".format(room.getName(),missingDegrees,bufferHeatingEnabled))

                    #self.log.info(u"{} {} {}".format(room.getName(),charged,maxBuffer))
                    
                    # Stop buffer heating if buffer more than 75% charged
                    if charged > maxBuffer:
                        hs.setInfo("LOADED")
                    # No heating needed if buffer is changed more than minBufferChargeLevel
                    elif not isHeatingActive and charged > 0:
                        hs.setInfo("UNLOAD")
                    # Currently no buffer heating
                    else:
                        hs.setInfo("CHARGE")
                        #self.log.info(u"3")
                        neededEnergy = maxBuffer - charged
                        neededTime = self.calculateHeatingDemandTime(neededEnergy,rs.getActivePossibleSaldo())
                        hs.setHeatingDemandEnergy(neededEnergy)
                        hs.setHeatingDemandTime(neededTime)

        hs.setChargedBuffer(charged)
            
        return hs
                
    def adjustChargeLevel(self,rs,currentTemp,lastTemp,chargeLevel):
        heatedUpTempDiff = currentTemp - lastTemp
        chargeLevel = chargeLevel - ( rs.getBufferCapacity() * heatedUpTempDiff )
        return chargeLevel
        
    def calculateChargeLevel(self,room,rs):
        totalChargeLevel = self.getCachedItemFloat(self.getHeatingBufferItem(room))
        adjustedChargeDiff = 0
        
        _currentTemp = round(self.getCachedStableItemFloat(self.getTemperatureSensorItem(room),20),1)
        if room.getName() in Heating._stableTemperatureReferences:
            _lastTemp = Heating._stableTemperatureReferences[room.getName()]
            if _currentTemp < _lastTemp:
                self.log.info(u"Cleanup : {:10s} • Reference from {} to {} °C decreased".format(room.getName(),_lastTemp,_currentTemp) )
            elif _currentTemp > _lastTemp:
                if totalChargeLevel > 0:
                    _totalChargeLevel = self.adjustChargeLevel(rs,_currentTemp,_lastTemp,totalChargeLevel)
                    if _totalChargeLevel < 0.0: _totalChargeLevel = 0.0
                    self.log.info(u"Cleanup : {:10s} • Reference from {} to {} °C increased and Charged from {} to {} W adjusted".format(room.getName(),_lastTemp,_currentTemp,round(totalChargeLevel,1),round(_totalChargeLevel,1)) )
                    totalChargeLevel = _totalChargeLevel
                    adjustedChargeDiff = totalChargeLevel - _totalChargeLevel
                else:
                    self.log.info(u"Cleanup : {:10s} • Reference from {} to {} °C increased".format(room.getName(),_lastTemp,_currentTemp) )
        Heating._stableTemperatureReferences[room.getName()]=_currentTemp
        

        # detech last runtime and change calculated values to that timespan
        # all calculations are normally per minute
        timespan = 30.0 if Heating.lastRuntime is None else ( self.now.getMillis() - Heating.lastRuntime.getMillis() ) / 1000.0
        devider = 60.0 / timespan
        #self.log.info(u"{} {}".format(room.getName(),devider))

        totalChargeLevel = totalChargeLevel + ( rs.getActiveSaldo() / 60.0 / devider )
        if totalChargeLevel < 0.0: totalChargeLevel = 0.0
        
        return totalChargeLevel, adjustedChargeDiff
      
    def calculateHeatingDemandTime(self,neededEnergy,activePossibleSaldo):
        if activePossibleSaldo <= 0:
            return Heating.INFINITE_HEATING_TIME
        else:
            neededTime = neededEnergy / activePossibleSaldo
            return neededTime

    def limitHeatingDemandTime(self, roomName, heatingDemandTime, limit = 1.5 ):
        if heatingDemandTime > limit:
            self.log.info(u"        : WARNING heating time for '{}' was limited from {} min to {} min".format(roomName,round(heatingDemandTime*60,0),round(limit*60,0)))
            return limit
        else:
            return heatingDemandTime

    def visualizeHeatingDemandTime(self,heatingDemandTime):
        if heatingDemandTime < 0:
            return u"<1"
        return u"~" if heatingDemandTime == Heating.INFINITE_HEATING_TIME else int( round(heatingDemandTime*60,0) )
        
        
        
        
        
        
        
    def formatEnergy(self,energy,precision=1):
        return round(energy/60.0,precision)
    
    def logCoolingAndRadiations(self,prefix,cr):
        self.log.info(u"{}: {}".format(prefix,cr.getSunDebugInfo()))
        self.log.info(u"        : Wall {} ({}☀) W/min • Air {} W/min • Leak {} W/min • Window {} ({}☀) W/min".format(
            self.formatEnergy(cr.getWallEnergy()),
            self.formatEnergy(cr.getWallRadiation()),
            self.formatEnergy(cr.getVentilationEnergy()),
            self.formatEnergy(cr.getLeakEnergy()),
            self.formatEnergy(cr.getWindowEnergy()),
            self.formatEnergy(cr.getWindowRadiation())
        ))
        msg = u"{} W/min".format(self.formatEnergy(cr.getHeatingRadiation())) if cr.getHeatingRadiation() > 0 else u"{} W/min (FC)".format(self.formatEnergy(cr.getPossibleHeatingRadiation()))
        self.log.info(u"        : ES {} W/min ({}°C) • HU {}".format(self.formatEnergy(cr.getPassiveSaldo()),round(cr.getReferenceTemperature(),1), msg ))
        self.log.info(u"        : ---")
                  
    def logHeatingState(self,room, cr, hhs ):
        
        rs = cr.getRoomState(room.getName())
        rhs = hhs.getHeatingState(room.getName()) if room.getHeatingVolume() != None else None
                        
        name = room.getName().replace("room","")
        infoMsg = u"{:11s} • {}°C".format(name,round(self.getCachedStableItemFloat(self.getTemperatureSensorItem(room)),1))
        
        if rhs != None:
            infoMsg = u"{} ({})".format(infoMsg,rhs.getHeatingTargetTemperature())

            infoValue = rhs.getInfo()
            if rhs.getForcedInfo() != None:
                infoValue = u"{} ({})".format(infoValue, rhs.getForcedInfo())
            infoMsg = u"{} {:6s}".format(infoMsg,infoValue)
        else:
            infoMsg = u"{}              ".format(infoMsg)
            
        details = []
        #details.append(u"{:4.1f}i".format(self.formatEnergy(rs.getIndoorWallEnergy())))
        if cr.getSunSouthRadiation() > 0 or cr.getSunWestRadiation() > 0:
            details.append(u"{:3.1f}☀".format(self.formatEnergy(rs.getWallRadiation()+rs.getWindowRadiation())))
                           
        detailsMsg = u" ({})".format(u", ".join(details)) if len(details) > 0 else u""
        infoMsg = u"{} • ES {:4.1f}{} W/min".format(infoMsg, self.formatEnergy(rs.getPassiveSaldo()), detailsMsg)

        

        # **** DEBUG ****
        #infoMsg = u"{} • DEBUG {} {}".format(infoMsg, rs.getPossibleHeatingRadiation(), rs.getPossibleHeatingVolume())

        if rhs != None:
            # show heating details per room if total heating is active
            if cr.getHeatingRadiation() > 0:
                infoMsg = u"{} • HU {:3.1f} W/min".format(infoMsg, self.formatEnergy(rs.getHeatingRadiation()))
                
            adjustedBuffer = u""
            if rhs.getChargedBuffer() != rs.getChargedEnergy() or rhs.getAdjustedHeatingBuffer() != None:
                if rhs.getChargedBuffer() != rs.getChargedEnergy():
                    adjustedBuffer = u"{}{}".format(adjustedBuffer,round(rs.getChargedEnergy(),1))
                if rhs.getAdjustedHeatingBuffer() != None:
                    adjustedBuffer = u"{} => {}".format(adjustedBuffer,round(rhs.getAdjustedHeatingBuffer(),1))
                adjustedBuffer = u" ({})".format(adjustedBuffer)
            
            percent = int(round(rhs.getChargedBuffer() * 100 / rs.getBufferSlotCapacity() ))
            infoMsg = u"{} • BF {}%, {}{} W".format(infoMsg, percent, round(rhs.getChargedBuffer(),1), adjustedBuffer)

            reductionMsg = []
            if rhs.getOutdoorReduction() > 0:
                reductionMsg.append(u"OR {}".format(rhs.getOutdoorReduction()))
            if rhs.getNightReduction() > 0:
                reductionMsg.append(u"NR {}".format(rhs.getNightReduction()))
            if rhs.getLazyReduction() > 0:
                reductionMsg.append(u"LR {}".format(rhs.getLazyReduction()))
            if len(reductionMsg) > 0:
                infoMsg = u"{} • {}".format(infoMsg, ", ".join(reductionMsg))
      
            if rhs.getHeatingDemandEnergy() > 0:
                infoMsg = u"{} • HU {} W in {} min".format(
                    infoMsg,
                    round(rhs.getHeatingDemandEnergy(),1),
                    self.visualizeHeatingDemandTime( rhs.getHeatingDemandTime() )
                )
                self.log.info(u"     ON : {}{}".format(infoMsg, rhs.getForcedDebugInfo() ))
            elif rhs.getHeatingDemandEnergy() == 0:
                self.log.info(u"    OFF : {}{}".format(infoMsg, rhs.getForcedDebugInfo()))
            else:
                self.log.info(u"SKIPPED : {}".format(infoMsg))
        else:
            self.log.info(u"        : {}".format(infoMsg))

                
    def calculate(self,isHeatingActive):
        # handle outdated ventilation values
        if itemLastUpdateOlderThen(self.ventilationFilterRuntimeItem, self.now.minusMinutes(120)):
            self.cache[self.ventilationLevelItem] = DecimalType(1)
            self.cache[self.ventilationOutgoingTemperatureItem] = DecimalType(0.0)
            self.cache[self.ventilationIncommingTemperatureItem] = DecimalType(0.0)

        # handle outdated forecast values
        if itemLastUpdateOlderThen(self.temperatureGardenFC4Item, self.now.minusMinutes(360) ):
            self.cache[self.temperatureGardenFC4Item] = getCachedItemState(self.temperatureGardenItem)
            self.cache[self.temperatureGardenFC8Item] = getCachedItemState(self.temperatureGardenItem)
            self.cache[self.cloudCoverFC4Item] = DecimalType(9)
            self.cache[self.cloudCoverFC8Item] = DecimalType(9)
            self.cache[self.cloudCoverItem] = DecimalType(9)

        self.cache[u"org_{}".format(self.cloudCoverItem)] = self.getCachedItemState(self.cloudCoverItem)
        self.cache[u"org_{}".format(self.temperatureGardenItem)] = self.getCachedStableItemState(self.temperatureGardenItem)

        # *** 8 HOUR FORECAST ***
        cr8 = self.getCoolingAndRadiations(8)
        self.logCoolingAndRadiations("FC8     ",cr8)

        # *** 4 HOUR FORECAST ***
        cr4 = self.getCoolingAndRadiations(4)
        self.logCoolingAndRadiations("FC4     ",cr4)

        # *** CURRENT ***
        cr = self.getCoolingAndRadiations(0)
        self.logCoolingAndRadiations("Current ",cr)

        if cr.getHeatingVolume() > 0:
            self.log.info(u"        : {} ({} m³) • Factor {}".format(cr.getHeatingDebugInfo(),round(cr.getHeatingVolume() / 1000.0,3),round(cr.getHeatingVolumeFactor(),2)))
            
        # *** NIGHT MODE DETECTION ***
        nightModeActive = self.isNightMode(isHeatingActive)
        nightReduction = self.DEFAULT_NIGHT_REDUCTION if nightModeActive else 0.0
        
        hhs = HouseHeatingState()
        heatingRequested = False
        for room in filter( lambda room: room.getHeatingVolume() != None,Heating.rooms):
            
            # CLEAN CHARGE LEVEL
            rs = cr.getRoomState(room.getName())
            totalChargeLevel, adjustedChargeDiff = self.calculateChargeLevel(room,rs)
            rs.setChargedEnergy(totalChargeLevel)

            rs4 = cr4.getRoomState(room.getName())
            rs4.setChargedEnergy(totalChargeLevel)

            rs8 = cr8.getRoomState(room.getName())
            rs8.setChargedEnergy(totalChargeLevel)

            # *** HEATING STATE ***

            rhs = None
            # *** CLEAN OR RESTORE FORCED HEATING ***
            if room.getName() in Heating._forcedHeatings:
                rhs = Heating._forcedHeatings[room.getName()][0]

                # Apply adjusted charge difference
                if adjustedChargeDiff > 0:
                    Heating._forcedHeatings[room.getName()][1] = Heating._forcedHeatings[room.getName()][1] - adjustedChargeDiff

                neededEnergy = Heating._forcedHeatings[room.getName()][1] - rs.getChargedEnergy()
                if neededEnergy < 0:
                    del Heating._forcedHeatings[room.getName()]
                    rhs = None
                else:
                    rs = cr.getRoomState(room.getName())
                    neededTime = self.calculateHeatingDemandTime(neededEnergy,rs.getActivePossibleSaldo())
                    rhs.setHeatingDemandEnergy(neededEnergy)
                    rhs.setHeatingDemandTime(neededTime)
                    hhs.setHeatingState(room.getName(),rhs)
                
            if rhs == None:
                # *** OUTDOOR REDUCTION ***
                outdoorReduction = self.calculateOutdoorReduction(rs.getPassiveSaldo(),rs4.getPassiveSaldo(),rs8.getPassiveSaldo())

                # *** HEATING DEMAND CALCULATION ***
                rhs = self.getHeatingDemand(room,rs,outdoorReduction,nightReduction,isHeatingActive)
            
                #_neededEnergy = self.getColdFloorHeatingEnergy(lastHeatingChange, rs.getFloorBufferSlotCapacity())
                #neededTime = _neededEnergy / rs.getPossibleHeatingRadiation()
                #neededEnergy = neededTime * rs.getActivePossibleSaldo()
                #self.log.info(u"{} Real Energy {} W - Needed Energy {} W - Needed Time {} min".format(room.getName(),round(_neededEnergy,1),round(neededEnergy,1),self.visualizeHeatingDemandTime(neededTime)))
                
                #neededTime = self.getColdFloorHeatingTime(lastHeatingChange)
                #neededEnergy = neededTime * rs.getActivePossibleSaldo()
                #self.log.info(u"{} saldo: {}, energy: {}, time: {}".format(room.getName(),round(rs.getActivePossibleSaldo(),1),round(neededEnergy,1),self.visualizeHeatingDemandTime(neededTime)))
                
                fh_info_type_r = {'not needed':[], 'wrong time': [], 'other': []}
                if rhs.getHeatingDemandEnergy() == 0:
                    # *** CHECK FOR PRE HEATING IN THE MORNING ***
                    if nightModeActive and self.now.getHourOfDay() < 12:
                        day_rhs = self.getHeatingDemand(room,rs,outdoorReduction,0,isHeatingActive)
                        if day_rhs.getHeatingDemandEnergy() > 0:
                            if not self.isNightModeTime( self.now.plusMinutes( int( round( self.limitHeatingDemandTime( room.getName(), day_rhs.getHeatingDemandTime() ) * 60, 0 ) ) ) ):
                                rhs = day_rhs
                                rhs.setForcedInfo('PRE')
                            else:
                                fh_info_type_r['other'].append(u"'PRE' too early for {} W in {} min".format(round(day_rhs.getHeatingDemandEnergy(),1),self.visualizeHeatingDemandTime(day_rhs.getHeatingDemandTime())))
                        else:
                            fh_info_type_r["not needed"].append('PRE')
                    else:
                        fh_info_type_r["wrong time"].append('PRE')
                    
                    # *** CHECK FOR COLD FLOOR HEATING ***
                    lastHeatingChange = getItemLastUpdate(self.getHeatingDemandItem(room))
                    coldFloorHeatingPossible = not isHeatingActive and self.possibleColdFloorHeating(nightModeActive,lastHeatingChange)
                    if coldFloorHeatingPossible:
                        # 1. calculate needed floor energy demand
                        #_neededEnergy = self.getColdFloorHeatingEnergy(lastHeatingChange, rs.getFloorBufferSlotCapacity())
                        # 2. calculate the time we need to heat this ammount of energy without taking care about cooling
                        # 2.1 no need to use self.calculateHeatingDemandTime here, because getPossibleHeatingRadiation can never be negative
                        #neededTime = _neededEnergy / rs.getPossibleHeatingRadiation()
                        # 3. calculate effective energy to know the end of the heating process                    
                        neededTime = self.getColdFloorHeatingTime(lastHeatingChange)
                        neededEnergy = neededTime * rs.getActivePossibleSaldo()                    
                        if rhs.getHeatingDemandEnergy() < neededEnergy:
                            if not self.isNightModeTime( self.now.plusMinutes( int( round( self.limitHeatingDemandTime( room.getName(), neededTime ) * 60, 0 ) ) ) ):
                                rhs.setHeatingDemandEnergy(neededEnergy)
                                rhs.setHeatingDemandTime(neededTime)
                                rhs.setForcedInfo('CF')
                            else:
                                fh_info_type_r['other'].append(u"'CF' too early for {} W in {} min".format(round(neededEnergy,1),self.visualizeHeatingDemandTime(neededTime)))
                        else:
                            fh_info_type_r["not needed"].append('CF')
                    else:
                        fh_info_type_r["wrong time"].append('CF')
                #else:
                #    fh_info_type_r.append(u"FH not needed")
                  
                if rhs.getForcedInfo() == None:
                    fh_info_r = []
                    for type in fh_info_type_r:
                        if len(fh_info_type_r[type]) == 0:
                            continue
                        
                        if type == 'other':
                            fh_info_r.append( ", ".join(fh_info_type_r[type]) )
                        else:
                            fh_info_r.append( "{} {}".format(" & ".join(fh_info_type_r[type]),type) )
                    
                    rhs.setForcedDebugInfo( u" • ({})".format( ", ".join(fh_info_r) ) if len(fh_info_r) > 0 else u"" )

            if ( isHeatingActive and rhs.getHeatingDemandEnergy() > 0.0 ) or rhs.getHeatingDemandTime() * 60 > Heating.MIN_HEATING_TIME:
                heatingRequested = True

            hhs.setHeatingState(room.getName(),rhs)
            
        hhs.setHeatingRequested(heatingRequested)

        # *** REGISTER FORCED HEATINGS IF HEATING IS POSSIBLE
        if heatingRequested:
            for room in filter( lambda room: room.getHeatingVolume() != None,Heating.rooms):
                rhs = hhs.getHeatingState(room.getName())
                if rhs.getForcedInfo() != None and room.getName() not in Heating._forcedHeatings:
                    Heating._forcedHeatings[room.getName()] = [ rhs, rhs.getHeatingDemandEnergy() ]

        # *** LOGGING ***
        for room in Heating.rooms:
            self.logHeatingState(room, cr, hhs )
            
        Heating.lastRuntime = self.now

        return cr, hhs
