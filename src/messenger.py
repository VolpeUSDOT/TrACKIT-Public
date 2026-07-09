import logging
import arcpy
import datetime
from pathlib import Path
from enum import Enum


class custTypes(Enum):
    """
    Logging output types
    """
    PYLOGGING = 1
    ARCPYMESSAGE = 2
    ALLLOGGING = 3
    INFORMATION = 4
    WARNING = 5
    ERROR = 6

class arcpyMessenger(object):
    def __init__(self):
        self.sendMessage = True

    def info(self, message):
        dt = datetime.datetime.now()
        arcpy.AddMessage("@ {0} INFO  Message: {1}".format(dt,message))

    def warning(self, message):
        dt = datetime.datetime.now()
        arcpy.AddWarning("@ {0} WARNING Message: {1}".format(dt,message))

    def error(self, message):
        dt = datetime.datetime.now()
        arcpy.AddError("@ {0} ERROR Message: {1}".format(dt,message))

class custMessenger(object):

    def __init__(self,loggingType:custTypes,logPath:Path=None,logFileName:str=None):
        self.all_logs = []
        self.LOGGINGTYPE = loggingType
        
        if self.LOGGINGTYPE == custTypes.PYLOGGING or self.LOGGINGTYPE == custTypes.ALLLOGGING:
            logger = logging.getLogger('Custom Logger')
            format = logging.Formatter("@ %(asctime)s %(levelname)s Message: %(message)s")
            logger.setLevel(logging.INFO)
            shandler = logging.StreamHandler()
            shandler.setFormatter(format)
            shandler.setLevel(logging.INFO)
            logger.addHandler(shandler)
            if logPath:
                file_output = logPath / logFileName
                handler = logging.FileHandler(str(file_output))
                handler.setFormatter(format)
                handler.setLevel(logging.INFO)
                logger.addHandler(handler)
            
            self.all_logs.append(logger)


        if self.LOGGINGTYPE == custTypes.ARCPYMESSAGE or self.LOGGINGTYPE == custTypes.ALLLOGGING:
            logger = arcpyMessenger()
            self.all_logs.append(logger)      

    def set_progressor(self, message:str, minrange:int, maxrange:int, step:int):
        arcpy.SetProgressor("step",message, minrange, maxrange)

    def set_progressor_position(self, position):
        arcpy.SetProgressorPosition(position)

    def reset_progressor(self):
        arcpy.ResetProgressor()
        
    def send_message(self,message:str,message_type:custTypes=custTypes.INFORMATION):
        for logger in self.all_logs:
            if message_type == custTypes.INFORMATION:
                logger.info(message)
            if message_type == custTypes.WARNING:
                logger.warning(message)
            if message_type == custTypes.ERROR:
                logger.error(message)
