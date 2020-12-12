from shared.helper import rule, getItemState, getNow, itemStateNewerThen, itemStateOlderThen, postUpdateIfChanged, postUpdate
from core.triggers import CronTrigger
from org.joda.time import DateTime
#from org.joda.time.format import DateTimeFormat
#OFFSET_FORMATTER = DateTimeFormat.forPattern("HH:mm")

@rule("values_depending_on_brightness.py")
class ValuesDependingOnBrightnessRule:
    def __init__(self):
        self.triggers = [CronTrigger("0 * * * * ?")]

    def execute(self, module, input):
        now = getNow()
        
        # pOutdoor_Astro_Dawn_Time
        # pOutdoor_Astro_Sunrise_Time
        # pOutdoor_Astro_Sunset_Time
        # pOutdoor_Astro_Dusk_Time
        
        cloudCover = getItemState("Cloud_Cover_Current").intValue()
                
        if getItemState("State_Rollershutter") == ON:
            _upTime = getItemState("pOutdoor_Astro_Sunrise_Time").calendar.getTimeInMillis()
            _upTime = int(_upTime + ( cloudCover * 30.0 / 9.0 ) * 60 * 1000)

            _lastDownTime = getItemState("State_Rollershutter_Down").calendar.getTimeInMillis()

            if now.getMillis() > _upTime and _upTime > _lastDownTime:
                postUpdate("State_Rollershutter", OFF)

            postUpdateIfChanged("State_Rollershutter_Up", DateTime(_upTime).toString() )
        else:
            _downTime = getItemState("pOutdoor_Astro_Dusk_Time").calendar.getTimeInMillis()
            _downTime = int(_downTime - ( cloudCover * 30.0 / 9.0 ) * 60 * 1000)
            
            if now.getMillis() > _downTime:
                postUpdate("State_Rollershutter", ON)

            postUpdateIfChanged("State_Rollershutter_Down", DateTime(_downTime).toString() )




        if itemStateOlderThen("pOutdoor_Astro_Sunset_Time", now) or itemStateNewerThen("pOutdoor_Astro_Sunrise_Time", now):
            postUpdateIfChanged("State_Outdoorlights", ON)
        else:
            postUpdateIfChanged("State_Outdoorlights", OFF)
            
        if itemStateOlderThen("pOutdoor_Astro_Dusk_Time", now) or itemStateNewerThen("pOutdoor_Astro_Dawn_Time", now):
            postUpdateIfChanged("State_Solar", OFF)
        else:
            postUpdateIfChanged("State_Solar", ON)
