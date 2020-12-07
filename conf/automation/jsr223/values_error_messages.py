from shared.helper import rule, getNow, itemLastUpdateOlderThen, sendNotificationToAllAdmins, getItemState, postUpdateIfChanged
from core.triggers import CronTrigger, ItemStateChangeTrigger


@rule("values_error_messages.py")
class ValuesErrorMessagesRule:
    def __init__(self):
        self.triggers = [
            CronTrigger("0 */5 * * * ?"),
            ItemStateChangeTrigger("Ventilation_Filter_Error"),
            ItemStateChangeTrigger("Ventilation_Error_Message"),
            ItemStateChangeTrigger("WeatherStation_Is_Working"),
            ItemStateChangeTrigger("Heating_Common_Fault"),
            ItemStateChangeTrigger("State_Server")
        ]

    def execute(self, module, input):
        group = u"Fehler"
        active = []

        if getItemState("Ventilation_Filter_Error") == ON or getItemState("Ventilation_Error_Message").toString() != "No Errors":
            active.append(u"Lüftung")

        if getItemState("Heating_Common_Fault").intValue() > 0:
            active.append(u"Heizung Fehler")

        if itemLastUpdateOlderThen("Heating_Common_Fault", getNow().minusMinutes(10)):
            active.append(u"Heizung Update")
            
        if getItemState("WeatherStation_Is_Working") == OFF:
            active.append(u"Wetterstation")
            
        if getItemState("State_Server").intValue() > 1:
            active.append(u"Server")

        refDate = getNow().minusMinutes(1440)  # last 24 hours

        if itemLastUpdateOlderThen("Temperature_GF_Livingroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_GF_Boxroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_GF_Guestroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_GF_GuestWC", refDate) \
                or itemLastUpdateOlderThen("Temperature_GF_Corridor", refDate) \
                or itemLastUpdateOlderThen("Temperature_GF_Utilityroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_Garage", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Bedroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Dressingroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Child1", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Child2", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Bathroom", refDate) \
                or itemLastUpdateOlderThen("Temperature_FF_Corridor", refDate) \
                or itemLastUpdateOlderThen("Temperature_Attic", refDate):
            active.append("Sensors")

        if len(active) == 0:
            active.append(u"Alles normal")
            group = u"Info"

        msg = u", ".join(active)

        if postUpdateIfChanged("MainStatus", msg):
            sendNotificationToAllAdmins(group, msg)
