"""
Extensions to the wonderful Pandas module
"""

import pandas as pd
from pandas import TimeSeries
from scipy import signal
import numpy as np

import othertime

import pdb

#########################
# Utility functions
#########################
def godin(phi):
    """
    Godin type filter of a time series
    """
    dt = get_dt(phi)
    window24 = 24.*3600//dt
    window25 = 25.*3600//dt
    phi_f = pd.rolling_mean(phi,window24,center=True)
    phi_f = pd.rolling_mean(phi_f,window25,center=True)
    phi_f = pd.rolling_mean(phi_f,window24,center=True)
    return phi_f

def butterfilt(phi,cutoff_dt,btype='low',order=3):
    """
    Butter worth filter the time series
    """
    dt = get_dt(phi)

    if not btype == 'band':
        Wn = dt/cutoff_dt
    else: # Band-pass expects a list of cuttoff frequencies
        Wn = [dt/co for co in cutoff_dt]
        
    (b, a) = signal.butter(order, Wn, btype=btype, analog=0, output='ba')
    
    # filtfilt only likes to operate along the last axis
    ytmp = phi.values.swapaxes(-1,0)
    ytmp = signal.filtfilt(b, a, ytmp, axis=-1)

    # Return a pandas object like the input
    phi_filt = phi.copy()
    phi_filt[:] = ytmp.swapaxes(0,-1)

    return phi_filt
 
def subsample(phi, sample_dt):
    """
    Resamples the data at window dt

    Computes moving average first 
    """
    dt = get_dt(phi)
    window = sample_dt//dt
    phi_mean = pd.rolling_mean(phi,window)
    return phi_mean[::window]


def rms(phi,cutoff_dt):
    """
    rolling rms
    """
    dt = get_dt(phi)
    window = cutoff_dt//dt
    phi_rms = pd.rolling_mean(phi**2,window,center=True)

    return np.sqrt(phi_rms)

def get_dt(phi):
    """Calculates the time step of a pandas object"""
    if type(phi) == pd.Panel:
        time = phi.items
    else:
        time = phi.index

    dt = time[1]-time[0]
    return dt.total_seconds()
    #jdate = time.to_julian_date()*86400.
    #return jdate[1]-jdate[0]

############################
# Extension classes
############################
class MetaData(object):

    units = None
    long_name = None
    stationid = None
    stationname = None
    height = None
    longitude = None
    latitude = None


    def __init__(self,**kwargs):
	"""
	Class for storing metadata for a TimeSeries object
	"""
        self.update(**kwargs)
     
    def update(self,**kwargs):
        self.__dict__.update(kwargs)
    

class ObsTimeSeries(TimeSeries):

    baseyear = 2000
    has_metadata = False

    def __init__(self, data, dtime,**kwargs):
	"""
	Time series w/ specific IO methods
	"""
        self.__dict__.update(kwargs)

        TimeSeries.__init__(self, data, index=dtime)
	#super(ObsTimeSeries,self).__init__(data,index=dtime)

	# Time coordinates
	self.nt = self.index.shape
	self.tsec = othertime.SecondsSince(self.index,\
		basetime = pd.datetime(self.baseyear,1,1))

    def __new__(cls, *args, **kwargs):
        arr = pd.TimeSeries.__new__(cls, *args, **kwargs)
        return arr.view(ObsTimeSeries)

    def interp(self, other):
	"""
	Interpolate onto another time series
        """
        return self.interpolate()[other.index]

    def set_metadata(self, **kwargs):
	"""Quickly sets the metadata"""

	if self.has_metadata:
	    self.metadata.update(**kwargs)
	else:
	    self.metadata = MetaData(**kwargs)

        self.has_metadata = True

    def to_nc4(self, ncfile, varname, groupid=None):
	"""
	
  	"""
 	# Open the file
	try:
	     nc = Dataset(ncfile, mode='w', clobber=False)
	except:
	     # File must exist
	     nc = Dataset(ncfile, mode='a')
	
	# Create the group 
        if groupid == None:
	    grp = nc
	else:
	    if groupid in nc.groups.keys():
		grp = nc.groups[groupid]
	    else:
		grp = nc.createGroup(groupid)
        
	# Create the time dimension (unlimited)
        if not 'time' in grp.dimensions.keys():
	    grp.createDimension('time',0)
                
	    # Create the coordinate variables
	    tmpvar=grp.createVariable('time','f8',('time',))
	    tmpvar[:] = self.tsec

	## Create the attributes
	#for aa in cc.keys():
	#    if aa !='Name' and aa !='Value':
	#	tmpvar.setncattr(aa,cc[aa]) 

