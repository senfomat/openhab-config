from shared.helper import rule, sendCommand, getItemState
from core.triggers import ItemStateChangeTrigger, ItemStateUpdateTrigger


@rule("lights_indoor_bedroom_control.py")
class LightsIndoorBedroomControlRule:
    def __init__(self):
        self.triggers = [
            ItemStateChangeTrigger("Light_FF_Bedroom_Left_Long_Pressed", state="ON"),
            ItemStateChangeTrigger("Light_FF_Bedroom_Right_Long_Pressed", state="ON")
        ]

    def execute(self, module, input):
        sendCommand("Scene4", ON)

@rule("lights_indoor_bedroom_left_control.py")
class LightsIndoorBedroomLeftControlRule:
    def __init__(self):
        self.triggers = [
            ItemStateUpdateTrigger("pFF_Bedroom_Light_Hue_Left_Switch", state="ON")
        ]

    def execute(self, module, input):
        if getItemState("pFF_Bedroom_Light_Hue_Left_Brightness").intValue() == 0:
            sendCommand("pFF_Bedroom_Light_Hue_Left_Brightness",100)
        else:
            sendCommand("pFF_Bedroom_Light_Hue_Left_Brightness",0)
            
@rule("lights_indoor_bedroom_right_control.py")
class LightsIndoorBedroomRightControlRule:
    def __init__(self):
        self.triggers = [
            ItemStateUpdateTrigger("pFF_Bedroom_Light_Hue_Right_Switch", state="ON")
        ]

    def execute(self, module, input):
        if getItemState("pFF_Bedroom_Light_Hue_Right_Brightness").intValue() == 0:
            sendCommand("pFF_Bedroom_Light_Hue_Right_Brightness",100)
        else:
            sendCommand("pFF_Bedroom_Light_Hue_Right_Brightness",0)
