"""
Script that creates a recording schedule.

To use this script:

    1. Change the values of the variables below that have all-caps names
       (LON, LAT, etc., all near the top of the file) for your use.
       
    2. At an operating system command prompt, change to the directory
       containing this script and then run the script with the command:

           python create_recording_schedule.py
           
       With the default value of OUTPUT_FILE_PATH below, the script will
       write its output to the file Schedule.csv in the same directory.
    
       Note that the Vesper `src` directory must be on your Python path
       for this script to be able to find certain Python modules that it
       depends upon.
"""


from __future__ import print_function
import datetime

import pytz

import vesper.util.os_utils as os_utils
import vesper.util.sun_utils as sun_utils
import vesper.util.time_utils as time_utils



# longitude in degrees east
LON = -114.076499

# latitude in degrees north
LAT = 46.641042

# start night (arguments to datetime.date function are year, month, and day)
START_NIGHT = datetime.date(2015, 8, 20)

# end night (arguments to datetime.date function are year, month, and day)
END_NIGHT = datetime.date(2015, 10, 30)

# sunset offset in minutes
SUNSET_OFFSET = -30

# sunrise offset in minutes
SUNRISE_OFFSET = 30

# Time zone name. Note that if you specify the name of a time zone in which
# DST is observed, the times output by the script will reflect DST-related
# time changes. If this isn't what you want, choose the name of a time
# zone with the appropriate UTC offset in which DST is not observed. You
# can see a list of Olson database time zones, including both their names
# (any of which should work below) and UTC offsets, at:
#
#     https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
#
# For example, if you'd like a time zone that's six hours behind UTC
# (like MDT) in which DST is not observed, you can choose 'Pacific/Galapagos'.
TIME_ZONE = pytz.timezone('US/Mountain')

OUTPUT_FILE_PATH = 'Schedule.csv'


def _main():
    
    get_sunset = sun_utils.get_sunset_time
    get_sunrise = sun_utils.get_sunrise_time
    night = START_NIGHT
    one_day = datetime.timedelta(days=1)
    sunset_offset = datetime.timedelta(minutes=SUNSET_OFFSET)
    sunrise_offset = datetime.timedelta(minutes=SUNRISE_OFFSET)
    
    lines = ['Night,Start Time,End Time']
    
    while night <= END_NIGHT:
        
        next_day = night + one_day
        
        start_time = _get_time(get_sunset, night, LON, LAT, sunset_offset)
        end_time = _get_time(get_sunrise, next_day, LON, LAT, sunrise_offset)
                
        line = '{:s},{:s},{:s}'.format(str(night), start_time, end_time)
        lines.append(line)
        
        night += one_day
        
    text = ''.join(line + '\n' for line in lines)
    os_utils.write_file(OUTPUT_FILE_PATH, text)


def _get_time(function, date, lon, lat, offset):
    
    dt = function(date, lon, lat)
    dt += offset
    dt = time_utils.round_datetime(dt, 60)
    dt = dt.astimezone(TIME_ZONE)
    
    return dt.strftime('%Y-%m-%d %H:%M')


if __name__ == '__main__':
    _main()