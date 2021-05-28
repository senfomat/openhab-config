from shared.helper import rule, getItemState, sendCommand, postUpdate, postUpdateIfChanged, createTimer
from core.triggers import ItemCommandTrigger, ItemStateChangeTrigger
from java.time import ZonedDateTime

ruleTimeouts = {}

@rule("lights_indoor_livingroom_control.py")
class HueColorMainRule:
    def __init__(self):
        self.triggers = [ItemCommandTrigger("gGF_Livingroom_Light_Hue_Color")]

    def execute(self, module, input):
        global ruleTimeouts
        ruleTimeouts["Livingroom_Hue_Color_Backward"] = ZonedDateTime.now().toInstant().toEpochMilli()

        command = input['event'].getItemCommand()
        
        #colors = command.toString().split(",")

        #red = round(float(colors[0]))
        #green = round(float(colors[1]))
        #blue = round(float(colors[1]))
        
        #command = u"{},{},{}".format(red,green,blue)
        
        sendCommand("pGF_Livingroom_Light_Hue1_Color", command)
        sendCommand("pGF_Livingroom_Light_Hue2_Color", command)
        sendCommand("pGF_Livingroom_Light_Hue3_Color", command)
        sendCommand("pGF_Livingroom_Light_Hue4_Color", command)
        sendCommand("pGF_Livingroom_Light_Hue5_Color", command)
        
        postUpdate("pGF_Livingroom_Light_Hue_Scene","")
        sendCommand("pOther_Manual_State_Lightprogram", 0)

@rule("lights_indoor_livingroom_control.py")
class HueColorIndividualRule:
    def __init__(self):
        self.triggers = [
            ItemCommandTrigger("pGF_Livingroom_Light_Hue1_Color"),
            ItemCommandTrigger("pGF_Livingroom_Light_Hue2_Color"),
            ItemCommandTrigger("pGF_Livingroom_Light_Hue3_Color"),
            ItemCommandTrigger("pGF_Livingroom_Light_Hue4_Color"),
            ItemCommandTrigger("pGF_Livingroom_Light_Hue5_Color")
        ]

    def execute(self, module, input):
        global ruleTimeouts
        now = ZonedDateTime.now().toInstant().toEpochMilli()
        last = ruleTimeouts.get("Livingroom_Hue_Color_Backward",0)
        
        if now - last > 1000:
            postUpdate("pGF_Livingroom_Light_Hue_Scene","")
            sendCommand("pOther_Manual_State_Lightprogram", 0)

@rule("lights_indoor_livingroom_control.py")
class HueColorProgramRule:
    def __init__(self):
        self.triggers = [ItemStateChangeTrigger("pOther_Manual_State_Lightprogram")]
        self.orgColors = None
        self.timer = None
        
        self.timeout = 30        
        
        self.fadingSteps = 20.0
        
    def _fixColor(self,color):
        if color < 0:
            return 0
        elif color > 255:
            return 255
        return int( color )
    
    def _getCurrentColors(self):
        color1 = getItemState("pGF_Livingroom_Light_Hue1_Color").toString().split(",")
        color2 = getItemState("pGF_Livingroom_Light_Hue2_Color").toString().split(",")
        color3 = getItemState("pGF_Livingroom_Light_Hue3_Color").toString().split(",")
        color4 = getItemState("pGF_Livingroom_Light_Hue4_Color").toString().split(",")
        color5 = getItemState("pGF_Livingroom_Light_Hue5_Color").toString().split(",")
        return [color1,color2,color3,color4,color5]
    
    def _setCurrentColors(self,data):
        global ruleTimeouts
        ruleTimeouts["Livingroom_Hue_Color_Backward"] = ZonedDateTime.now().toInstant().toEpochMilli()
        
        sendCommand("pGF_Livingroom_Light_Hue1_Color",u"{},{},{}".format(data[0][0],data[0][1],data[0][2]))
        sendCommand("pGF_Livingroom_Light_Hue2_Color",u"{},{},{}".format(data[1][0],data[1][1],data[1][2]))
        sendCommand("pGF_Livingroom_Light_Hue3_Color",u"{},{},{}".format(data[2][0],data[2][1],data[2][2]))
        sendCommand("pGF_Livingroom_Light_Hue4_Color",u"{},{},{}".format(data[3][0],data[3][1],data[3][2]))
        sendCommand("pGF_Livingroom_Light_Hue5_Color",u"{},{},{}".format(data[4][0],data[4][1],data[4][2]))

    def _fade(self,step,fromColor,toColor,currentColor):
        start = float(fromColor[0])
        diff = ( float(toColor[0]) - start ) / self.fadingSteps
        red = self._fixColor( start + ( diff * step ) )

        start = float(fromColor[1])
        diff = ( float(toColor[1]) - start ) / self.fadingSteps
        green = self._fixColor( start + ( diff * step ) )

        start = float(fromColor[2])
        diff = ( float(toColor[2]) - start ) / self.fadingSteps
        blue = self._fixColor( start + ( diff * step ) )

        return [u"{}".format(red),u"{}".format(green),u"{}".format(blue)]
    
    def callbackFaded(self,step,data):
        if getItemState("pOther_Manual_State_Lightprogram").intValue() == 0:
            return
            
        color1, color2, color3, color4, color5 = data
        
        if step == self.fadingSteps:
            newColor1 = color2
            newColor2 = color3
            newColor3 = color4
            newColor4 = color5
            newColor5 = color1
        else:
            currentColor1, currentColor2, currentColor3, currentColor4 , currentColor5 = self._getCurrentColors()
            
            newColor1 = self._fade( step, color1, color2, currentColor1 )
            newColor2 = self._fade( step, color2, color3, currentColor2 )
            newColor3 = self._fade( step, color3, color4, currentColor3 )
            newColor4 = self._fade( step, color4, color5, currentColor4 )
            newColor5 = self._fade( step, color5, color1, currentColor5 )
            
        self.log.info(u"{} - 1 {}, from {} => {}".format(step,newColor1,color1, color2))
        self.log.info(u"{} - 2 {}, from {} => {}".format(step,newColor2,color2, color3))
        self.log.info(u"{} - 3 {}, from {} => {}".format(step,newColor3,color3, color4))
        self.log.info(u"{} - 4 {}, from {} => {}".format(step,newColor4,color4, color5))
        self.log.info(u"{} - 5 {}, from {} => {}".format(step,newColor5,color5, color1))
        
        self._setCurrentColors([newColor1,newColor2,newColor3,newColor4,newColor5])
        
        if step < self.fadingSteps:
            self.timer = createTimer(self.log, self.timeout, self.callbackFaded, [step + 1, data] )
            self.timer.start()
        else:
            self.timer = createTimer(self.log, self.timeout, self.callbackFaded, [1, self._getCurrentColors() ] )
            self.timer.start()
    
    def callback(self):
        if getItemState("pOther_Manual_State_Lightprogram").intValue() == 0:
            return
        
        color1 = getItemState("pGF_Livingroom_Light_Hue1_Color")
        color2 = getItemState("pGF_Livingroom_Light_Hue2_Color")
        color3 = getItemState("pGF_Livingroom_Light_Hue3_Color")
        color4 = getItemState("pGF_Livingroom_Light_Hue4_Color")
        color5 = getItemState("pGF_Livingroom_Light_Hue5_Color")
            
        global ruleTimeouts
        ruleTimeouts["Livingroom_Hue_Color_Backward"] = ZonedDateTime.now().toInstant().toEpochMilli()
    
        sendCommand("pGF_Livingroom_Light_Hue1_Color",color2)
        sendCommand("pGF_Livingroom_Light_Hue2_Color",color3)
        sendCommand("pGF_Livingroom_Light_Hue3_Color",color4)
        sendCommand("pGF_Livingroom_Light_Hue4_Color",color5)
        sendCommand("pGF_Livingroom_Light_Hue5_Color",color1)
                    
        self.timer = createTimer(self.log, self.timeout, self.callback )
        self.timer.start()
            
    def execute(self, module, input):
        if self.timer != None:
            self.timer.cancel()
            self.timer = None
            
            if self.orgColors != None:
                self._setCurrentColors(self.orgColors)
                self.orgColors = None
        
        itemState = input["event"].getItemState().intValue()
        
        if itemState > 0:
            self.orgColors = self._getCurrentColors()

            if itemState == 1:

                self.timer = createTimer(self.log, 1, self.callback)
                self.timer.start()

            elif itemState == 2:
        
                self.timer = createTimer(self.log, 1, self.callbackFaded, [1, self.orgColors])
                self.timer.start()
