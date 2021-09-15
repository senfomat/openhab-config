<?php
class Environment
{
    public static function getInfluxDBIntervalConfigs()
    {
        return array();
    }
    
    public static function getInfluxPersistanceGroups()
    {
        return array( 'gPersistance_Chart' );
    }

    public static function getMySQLIntervalConfigs()
    {
        return array();
    }
    
    public static function getMySQLPersistanceGroups()
    {
        return array( 'gPersistance_History' );     
    }
}
 
