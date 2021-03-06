# -*- coding: utf-8 -*-
"""
Tools for modifying suntans boundary condition files


Examples:
---------

Example 1) Modify the boundary condition markers with a shapefile:
------------------------------------------------------------------
    
    >>from sunboundary import modifyBCmarker
    >># Path to the grid
    >>suntanspath = 'C:/Projects/GOMGalveston/MODELLING/GRIDS/GalvestonCoarseBC'
    >># Name of the shapefile
    >>bcfile = '%s/Galveston_BndPoly.shp'%suntanspath 
    >>modifyBCmarker(suntanspath,bcfile)
    
Created on Fri Nov 02 15:24:12 2012

@author: mrayson
"""


import sunpy
from sunpy import Grid,Spatial
from netCDF4 import Dataset, num2date
import numpy as np
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
#import matplotlib.nxutils as nxutils #inpolygon equivalent lives here
from inpolygon import inpolygon
from datetime import datetime, timedelta
import othertime
import os
from maptools import readShpPoly,ll2utm
from get_metocean_dap import get_metocean_local
from interpXYZ import Interp4D

import pdb

class Boundary(object):
    """
    Generic SUNTANS boundary class
    
    Usage: 
        Boundary(suntanspath,timeinfo)
        
    Inputs:
        suntanspath - (string) 
        timeinfo - (3x1 tuple) (starttime,endtime,dt) where starttime/endtime
            have format 'yyyymmdd.HHMM' and dt in seconds
    """
    
    utmzone = 15
    isnorth = True
    loadfromnc = False

    # Interpolation options dictionary
    interpdict = dict(
        method='idw', # Interpolation method:  'nn', 'idw', 'kriging', 'griddata'
        NNear=4, 
        p = 1.0, #  power for inverse distance weighting (idw only)
        varmodel = 'spherical', #(kriging only)
        nugget = 0.1,
        sill = 0.8,
        vrange = 10000.0,
    )
 
    
    def __init__(self,suntanspath,timeinfo,**kwargs):
        """
        Initialise boundary path.
        
        To load data directly from an existing file:
            Boundary('boundary_ncfile.nc',0)
        """
        self.__dict__.update(**kwargs)

        if os.path.isdir(suntanspath) or self.loadfromnc:
        
            self.suntanspath = suntanspath
            self.timeinfo = timeinfo
            
            self.grd = sunpy.Grid(suntanspath)
            
            self._loadBoundary()
            
            self.getTime()
            
            # Initialise the output arrays
            self.initArrays()
            
        else:
            print 'Loading boundary data from a NetCDF file...'
            self.infile = suntanspath
            print '\t%s'%self.infile
            self._loadBoundaryNC()

            self.tsec = self.ncTime()
        

    def __call__(self,tsec,varname,method='quadratic'):
        """
        Interpolates the boundary variable "varname" onto the time step "tsec"
        """
        # Check to see if the interpolate class has been set up
        iclass = '_I_%s'%varname
        if not self.__dict__.has_key(iclass):
            setattr( self,iclass,interp1d(self.tsec,self[varname][:],kind=method,\
                axis=0,bounds_error=False,fill_value=0) )

        # Returns the interpolated array [1,Nk,Nc/Ne]
        return getattr(self,iclass)(tsec)
        
    def _loadBoundary(self):
        """
        Load the coordinates and indices for type 2 and 3 BC's
        """
        ind2 = np.argwhere(self.grd.mark==2)
        ind3 = np.argwhere(self.grd.mark==3)
        
        # Edge index of type 2 boundaries
        self.edgep = ind2
        self.N2 = len(self.edgep)
        
        # Cell index of type 3 boundaries
        cellp1 = self.grd.grad[ind3,0]
        cellp2 = self.grd.grad[ind3,1]
        cellp=[]
        for c1,c2 in zip(cellp1,cellp2):
            if c1==-1:
                cellp.append(c2)
            elif c2==-1:
                cellp.append(c1)
        
        self.N3 = len(cellp)
        
        # Store the coordinates of the type 2 and 3 boundaries
        if self.N3>0:
            cellp = np.array(cellp)
            self.cellp = np.unique(cellp)
            self.N3 = self.cellp.shape[0]
            self.xv = self.grd.xv[self.cellp]
            self.yv = self.grd.yv[self.cellp]
        
        # Find the edge points
        if self.N2>0:
            xe = np.mean(self.grd.xp[self.grd.edges],axis=1)
            ye = np.mean(self.grd.yp[self.grd.edges],axis=1)
            self.xe = xe[self.edgep]
            self.ye = ye[self.edgep]
            
            # Determine the unique flux segments (these are a subset of Type-2 boundaries)
            indseg = np.argwhere(self.grd.edge_id>0)
            segID = self.grd.edge_id[indseg]
            self.segp = np.unique(segID)
            self.Nseg = np.size(self.segp)
            # This is the pointer for the edge to the segment
            self.segedgep=self.edgep*0
            n=-1            
            for ii in self.edgep:
                n+=1
                if self.grd.edge_id[ii]>0:
                    self.segedgep[n]=self.grd.edge_id[ii]
        else:
            self.Nseg=0
             
        # Get the depth info
        self.Nk = self.grd.Nkmax
        self.z = self.grd.z_r

    def setDepth(self,dv):
        """
        Sets the depth at the type2 and 3 points
        """
        if self.N3>0:
            self.dv = dv[self.cellp]
        if self.N2>0:
            nc1 = self.grd.grad[:,0]
            nc2 = self.grd.grad[:,1]
                    
            # check for edges (use logical indexing)
            ind1 = nc1==-1
            nc1[ind1]=nc2[ind1]
            ind2 = nc2==-1
            nc2[ind2]=nc1[ind2]
            
            de = dv[nc1]
            self.de = de[self.edgep.ravel()]


    def getTime(self):
        """
        Load the timeinfo into a list of datetime objects
        """
        # build a list of timesteps
        t1 = datetime.strptime(self.timeinfo[0],'%Y%m%d.%H%M%S')
        t2 = datetime.strptime(self.timeinfo[1],'%Y%m%d.%H%M%S')
        
        self.time = []
        t0=t1
        while t0 <= t2:
            self.time.append(t0)
            t0 += timedelta(seconds=self.timeinfo[2])
        
        self.Nt = len(self.time)

        self.tsec = self.ncTime()
                
    def ncTime(self):
        """
        Return the time as seconds since 1990-01-01
        """        
        nctime = []
        for t in self.time:
            dt = t-datetime(1990,1,1)
            nctime.append(dt.total_seconds())
            
        return np.asarray(nctime)
        
    def initArrays(self):
        """
        Initialise the boundary condition arrays
        
        Type 3 variables are at the cell-centre (xv,yv) and are named:
            uv, vc, wc, h, T, S
            
            Dimensions: [Nt,Nk,N3]
            
        Type 2 variables are at the cell edges (xe, ye) and are named:
            boundary_u
            boundary_v
            boundary_w
            boundary_T
            boundary_S
            (no h)
            
            Dimensions: [Nt, Nk, N2]
        """
        
        # Type 2 arrays
        self.boundary_h = np.zeros((self.Nt,self.N2))
        self.boundary_u = np.zeros((self.Nt,self.Nk,self.N2))
        self.boundary_v = np.zeros((self.Nt,self.Nk,self.N2))
        self.boundary_w = np.zeros((self.Nt,self.Nk,self.N2))
        self.boundary_T = np.zeros((self.Nt,self.Nk,self.N2))
        self.boundary_S = np.zeros((self.Nt,self.Nk,self.N2))
        
        # Type 3 arrays
        self.uc = np.zeros((self.Nt,self.Nk,self.N3))
        self.vc = np.zeros((self.Nt,self.Nk,self.N3))
        self.wc = np.zeros((self.Nt,self.Nk,self.N3))
        self.T = np.zeros((self.Nt,self.Nk,self.N3))
        self.S = np.zeros((self.Nt,self.Nk,self.N3))
        self.h = np.zeros((self.Nt,self.N3))
        
        # Type 2 flux array
        self.boundary_Q = np.zeros((self.Nt,self.Nseg))
        
    
    def write2NC(self,ncfile):
        """
        Method for writing to the suntans boundary netcdf format
        
        """
        from netCDF4 import Dataset
        
        nc = Dataset(ncfile, 'w', format='NETCDF4_CLASSIC')
        
        # Define the dimensions
        nc.createDimension('Nt',None) # unlimited
        nc.createDimension('Nk',self.Nk)
        if self.N2>0:
            nc.createDimension('Ntype2',self.N2)
        if self.N3>0:    
            nc.createDimension('Ntype3',self.N3)
        if self.Nseg>0:
            nc.createDimension('Nseg',self.Nseg)
            
        ###
        # Define the coordinate variables and their attributes
        
        if self.N3>0:    
            # xv
            tmpvar=nc.createVariable('xv','f8',('Ntype3',))
            tmpvar[:] = self.xv
            tmpvar.setncattr('long_name','Easting of type-3 boundary points')
            tmpvar.setncattr('units','metres')
    
            # yv
            tmpvar=nc.createVariable('yv','f8',('Ntype3',))
            tmpvar[:] = self.yv
            tmpvar.setncattr('long_name','Northing of type-3 boundary points')
            tmpvar.setncattr('units','metres')
            
            # Type 3 indices
            tmpvar=nc.createVariable('cellp','i4',('Ntype3',))
            tmpvar[:] = self.cellp
            tmpvar.setncattr('long_name','Index of suntans grid cell corresponding to type-3 boundary')
            tmpvar.setncattr('units','')
        
        if self.N2>0:    
            # xe
            tmpvar=nc.createVariable('xe','f8',('Ntype2',))
            tmpvar[:] = self.xe
            tmpvar.setncattr('long_name','Easting of type-2 boundary points')
            tmpvar.setncattr('units','metres')
    
            # ye
            tmpvar=nc.createVariable('ye','f8',('Ntype2',))
            tmpvar[:] = self.ye
            tmpvar.setncattr('long_name','Northing of type-2 boundary points')
            tmpvar.setncattr('units','metres')
    
            # Type 2 indices
            tmpvar=nc.createVariable('edgep','i4',('Ntype2',))
            tmpvar[:] = self.edgep
            tmpvar.setncattr('long_name','Index of suntans grid edge corresponding to type-2 boundary')
            tmpvar.setncattr('units','')
        
        if self.Nseg>0:
            # Type 2 indices
            tmpvar=nc.createVariable('segedgep','i4',('Ntype2',))
            tmpvar[:] = self.segedgep
            tmpvar.setncattr('long_name','Pointer to boundary segment flag for each type-2 edge')
            tmpvar.setncattr('units','')     
            
            tmpvar=nc.createVariable('segp','i4',('Nseg',))
            tmpvar[:] = self.segp
            tmpvar.setncattr('long_name','Boundary segment flag')
            tmpvar.setncattr('units','')  
        # z
        tmpvar=nc.createVariable('z','f8',('Nk',))
        tmpvar[:] = self.z
        tmpvar.setncattr('long_name','Vertical grid mid-layer depth')
        tmpvar.setncattr('units','metres')
        
        # time
        tmpvar=nc.createVariable('time','f8',('Nt',))
        tmpvar[:] = self.ncTime()
        tmpvar.setncattr('long_name','Boundary time')
        tmpvar.setncattr('units','seconds since 1990-01-01 00:00:00')
        
        ###
        # Define the boundary data variables and their attributes
        
        ###
        # Type-2 boundaries
        if self.N2>0:    
            tmpvar=nc.createVariable('boundary_h','f8',('Nt','Ntype2'))
            tmpvar[:] = self.boundary_h
            tmpvar.setncattr('long_name','Free-surface elevation at type-2 boundary point')
            tmpvar.setncattr('units','metre')
 
            tmpvar=nc.createVariable('boundary_u','f8',('Nt','Nk','Ntype2'))
            tmpvar[:] = self.boundary_u
            tmpvar.setncattr('long_name','Eastward velocity at type-2 boundary point')
            tmpvar.setncattr('units','metre second-1')
                    
            tmpvar=nc.createVariable('boundary_v','f8',('Nt','Nk','Ntype2'))
            tmpvar[:] = self.boundary_v
            tmpvar.setncattr('long_name','Northward velocity at type-2 boundary point')
            tmpvar.setncattr('units','metre second-1')
                    
            tmpvar=nc.createVariable('boundary_w','f8',('Nt','Nk','Ntype2'))
            tmpvar[:] = self.boundary_w
            tmpvar.setncattr('long_name','Vertical velocity at type-2 boundary point')
            tmpvar.setncattr('units','metre second-1')
    
            tmpvar=nc.createVariable('boundary_T','f8',('Nt','Nk','Ntype2'))
            tmpvar[:] = self.boundary_T
            tmpvar.setncattr('long_name','Water temperature at type-2 boundary point')
            tmpvar.setncattr('units','degrees C')
    
            tmpvar=nc.createVariable('boundary_S','f8',('Nt','Nk','Ntype2'))
            tmpvar[:] = self.boundary_S
            tmpvar.setncattr('long_name','Salinity at type-2 boundary point')
            tmpvar.setncattr('units','psu')
        
        # Type-2 flux boundaries
        if self.Nseg>0:
            tmpvar=nc.createVariable('boundary_Q','f8',('Nt','Nseg'))
            tmpvar[:] = self.boundary_Q
            tmpvar.setncattr('long_name','Volume flux  at boundary segment')
            tmpvar.setncattr('units','metre^3 second-1')
            
        ###
        # Type-3 boundaries
        if self.N3>0:
            tmpvar=nc.createVariable('uc','f8',('Nt','Nk','Ntype3'))
            tmpvar[:] = self.uc
            tmpvar.setncattr('long_name','Eastward velocity at type-3 boundary point')
            tmpvar.setncattr('units','metre second-1')
                    
            tmpvar=nc.createVariable('vc','f8',('Nt','Nk','Ntype3'))
            tmpvar[:] = self.vc
            tmpvar.setncattr('long_name','Northward velocity at type-3 boundary point')
            tmpvar.setncattr('units','metre second-1')
                    
            tmpvar=nc.createVariable('wc','f8',('Nt','Nk','Ntype3'))
            tmpvar[:] = self.wc
            tmpvar.setncattr('long_name','Vertical velocity at type-3 boundary point')
            tmpvar.setncattr('units','metre second-1')
    
            tmpvar=nc.createVariable('T','f8',('Nt','Nk','Ntype3'))
            tmpvar[:] = self.T
            tmpvar.setncattr('long_name','Water temperature at type-3 boundary point')
            tmpvar.setncattr('units','degrees C')
    
            tmpvar=nc.createVariable('S','f8',('Nt','Nk','Ntype3'))
            tmpvar[:] = self.S
            tmpvar.setncattr('long_name','Salinity at type-3 boundary point')
            tmpvar.setncattr('units','psu')
            
            tmpvar=nc.createVariable('h','f8',('Nt','Ntype3'))
            tmpvar[:] = self.h
            tmpvar.setncattr('long_name','Water surface elevation at type-3 boundary point')
            tmpvar.setncattr('units','metres')
        
        nc.close()
        
        print 'Boundary data sucessfully written to: %s'%ncfile
        
    def _loadBoundaryNC(self):
        """
        Load the boundary class data from a netcdf file
        """
        
        nc = Dataset(self.infile, 'r')     
        
        # Get the dimension sizes
        self.Nk = nc.dimensions['Nk'].__len__()
        try:
            self.N2 = nc.dimensions['Ntype2'].__len__()
        except:
            self.N2=0
        try:
            self.N3 = nc.dimensions['Ntype3'].__len__()
        except:
            self.N3=0
        try:
            self.Nseg = nc.dimensions['Nseg'].__len__()
        except:
            self.Nseg=0 
        self.Nt = nc.dimensions['Nt'].__len__()
        
        t = nc.variables['time']
        self.time = num2date(t[:],t.units)
        
        self.z = nc.variables['z'][:]
        
        if self.N3>0:
            self.cellp = nc.variables['cellp'][:]
            self.xv = nc.variables['xv'][:]
            self.yv = nc.variables['yv'][:]
            self.uc = nc.variables['uc'][:]
            self.vc = nc.variables['vc'][:]
            self.wc = nc.variables['wc'][:]
            self.T = nc.variables['T'][:]
            self.S = nc.variables['S'][:]
            self.h = nc.variables['h'][:]
            
        if self.N2>0:
            self.edgep = nc.variables['edgep'][:]
            self.xe = nc.variables['xe'][:]
            self.ye = nc.variables['ye'][:]
            self.boundary_h = nc.variables['boundary_h'][:]
            self.boundary_u = nc.variables['boundary_u'][:]
            self.boundary_v = nc.variables['boundary_v'][:]
            self.boundary_w = nc.variables['boundary_w'][:]
            self.boundary_T = nc.variables['boundary_T'][:]
            self.boundary_S = nc.variables['boundary_S'][:]
            
        if self.Nseg>0:
            self.segp = nc.variables['segp'][:]
            self.segedgep = nc.variables['segedgep'][:]
            self.boundary_Q = nc.variables['boundary_Q'][:]
                    
        nc.close()
        
    def scatter(self,varname='S',klayer=0,tstep=0,**kwargs):
        """
        Colored scatter plot of boundary data
        """
        
        z = self[varname]
        if len(z.shape)==2:
            z = z[tstep,:]
        else:
            z = z[tstep,klayer,:]
        
        if varname in ['S','T','h','uc','vc','wc']:
            x = self.xv
            y = self.yv
        else:
            x = self.xe
            y = self.ye
        
        self.fig = plt.gcf()
        ax = self.fig.gca()
        
        s1 = plt.scatter(x,y,s=30,c=z,**kwargs)
        
        ax.set_aspect('equal')
        plt.colorbar()
        
        titlestr='Boundary variable : %s \n z: %3.1f [m], Time: %s'%(varname,self.z[klayer],\
        datetime.strftime(self.time[tstep],'%d-%b-%Y %H:%M:%S'))
        
        plt.title(titlestr)
        
        return s1
        
    def plot(self,varname='S',klayer=0,j=0,rangeplot=True,**kwargs):
        """
        Colored scatter plot of boundary data
        """
        
        z = self[varname]
        if len(z.shape)==2:
            z = z[:,j]
        else:
            z = z[:,klayer,j]
        
        self.fig = plt.gcf()
        s1 = plt.plot(self.time,z,**kwargs)
        if rangeplot:
            upper = np.max(self[varname],axis=-1)
            lower = np.min(self[varname],axis=-1)
            if len(upper.shape)==2:
                upper=np.max(upper,axis=-1)
                lower=np.max(lower,axis=-1)
            plt.fill_between(self.time,lower,y2=upper,color=[0.5, 0.5, 0.5],alpha=0.7)
        
        plt.xticks(rotation=17)
        
        
        titlestr='Boundary variable : %s \n z: %3.1f [m]'%(varname,self.z[klayer])
        
        plt.title(titlestr)
        
        return s1
        
    def savefig(self,outfile,dpi=150):
        
        self.fig.savefig(outfile,dpi=dpi)
        print 'Boundary condition image saved to file:%s'%outfile
    
    def roms2boundary(self,romsfile,setUV=False,seth=False,**kwargs):
        """
        Interpolates ROMS data onto the type-3 boundary cells
        
        """
        import romsio

        # Include type 3 cells only
        roms = romsio.roms_interp(romsfile,self.xv,self.yv,-self.z,self.time,**kwargs)
        
        h, T, S, uc, vc = roms.interp(setUV=setUV,seth=seth)

        self.T+=T
        self.S+=S
        
        if seth:
            self.h+=h
        if setUV:
            self.uc+=uc
            self.vc+=vc

    def oceanmodel2bdy(self,ncfile,convert2utm=True,setUV=True,seth=True,name='HYCOM'):
        """
        Interpolate data from a downloaded netcdf file to the open boundaries

        """
        print 'Loading boundary data from ocean model netcdf file:\n\t%s...'%ncfile
        # Load the temperature salinity data and coordinate data
        temp, nc = get_metocean_local(ncfile,'temp',name=name)
        salt, nc = get_metocean_local(ncfile,'salt')
        if setUV:
            u, nc = get_metocean_local(ncfile,'u')
            v, nc = get_metocean_local(ncfile,'v')


        # Convert to utm
        ll = np.vstack([nc.X.ravel(),nc.Y.ravel()]).T
        if convert2utm:
            xy = ll2utm(ll,self.utmzone,north=self.isnorth)
        else:
            xy = ll

        # Construct a 3D mask
        mask3d = temp.mask
        mask3d = mask3d[0,...]
        mask3d = mask3d.reshape((nc.nz,xy.shape[0]))

        # Type 3 cells
        if self.N3>0:
            # Construct the 4D interp class
            F4d =\
                Interp4D(xy[:,0],xy[:,1],nc.Z,nc.time,\
                    self.xv,self.yv,self.z,self.time,mask=mask3d,**self.interpdict)

            tempnew = F4d(temp)
            self.T[:] = tempnew

            saltnew = F4d(salt)
            self.S[:] = saltnew

            # Never do this for type-3
            #if setUV:
            #    unew = F4d(u)
            #    self.u[:] += unew
            #    vnew = F4d(v)
            #    self.v[:] += vnew

            if seth:
                # Construct the 3D interp class for surface height
                ssh, nc2d = get_metocean_local(ncfile,'ssh')
                mask2d = ssh.mask
                mask2d = mask2d[0,...].ravel()

                F3d = Interp4D(xy[:,0],xy[:,1],None,nc2d.time,\
                    self.xv,self.yv,None,self.time,mask=mask2d,**self.interpdict)
                sshnew = F3d(ssh)
                self.h[:] += sshnew

        # Type 2 cells : no free-surface
        if self.N2>0:
            # Construct the 4D interp class
            F4d =\
             Interp4D(xy[:,0],xy[:,1],nc.Z,nc.time,\
                 self.xe,self.ye,self.z,self.time,mask=mask3d,**self.interpdict)

            tempnew = F4d(temp)
            self.boundary_T[:] = tempnew

            saltnew = F4d(salt)
            self.boundary_S[:] = saltnew

            if setUV:
                unew = F4d(u)
                self.boundary_u[:] += unew
                vnew = F4d(v)
                self.boundary_v[:] += vnew

        
    def otis2boundary(self,otisfile,conlist=None,setUV=False):
        """
        Interpolates the OTIS tidal data onto all type-3 boundary cells
        
        Note that the values are added to the existing arrays (h, uc, vc)
        """
        from maptools import utm2ll
        import read_otps
        
        if self.N3>0:
            print 'Interolating otis onto type 3 bc''s...'
            xy = np.vstack((self.xv,self.yv)).T
            ll = utm2ll(xy,self.utmzone,north=self.isnorth)
            
            if self.__dict__.has_key('dv'):
                z=self.dv
            else:
                print 'Using OTIS depths to calculate velocity. Use setDepth()\
                to set this.'
                z=None
                
            h,U,V = read_otps.tide_pred(otisfile,ll[:,0],ll[:,1],np.array(self.time),z=z,conlist=conlist)
            
            # Update the arrays - note that the values are added to the existing arrays
            self.h += h
            if setUV:
                for k in range(self.Nk):
                    self.uc[:,k,:] += U
                    self.vc[:,k,:] += V

        if self.N2>0:
            print 'Interolating otis onto type 2 bc''s...'
            xy = np.hstack((self.xe,self.ye))
            ll = utm2ll(xy,self.utmzone,north=self.isnorth)
            
            if self.__dict__.has_key('de'):
                z=self.de
            else:
                print 'Using OTIS depths to calculate velocity. Use setDepth()\
                to set this .'
                z=None
                
            h,U,V = read_otps.tide_pred(otisfile,ll[:,0],ll[:,1],np.array(self.time),z=z,conlist=conlist)
            
            # Update the arrays - note that the values are added to the existing arrays
            for k in range(self.Nk):
                self.boundary_u[:,k,:] += U
                self.boundary_v[:,k,:] += V

            
        print 'Finished interpolating OTIS tidal data onto boundary arrays.'
       
    def otisfile2boundary(self,otisfile,dbfile,stationID,setUV=False,conlist=None):
        """
        Interpolates the OTIS tidal data onto all type-3 boundary cells
        
        Note that the values are added to the existing arrays (h, uc, vc)

	Applies an amplitude and phase correction based on a time series. 
	Also adds the residual (low-frequency) water level variability.
        """
        from maptools import utm2ll
        import read_otps
        
        xy = np.vstack((self.xv.ravel(),self.yv.ravel())).T
        ll = utm2ll(xy,self.utmzone,north=self.isnorth)
        
        if self.__dict__.has_key('dv'):
            z=self.dv
        else:
            print 'Using OTIS depths to calculate velocity. Set self.dv to change this.'
            z=None
            
        h,U,V,residual = read_otps.tide_pred_correc(otisfile,ll[:,0],ll[:,1],np.array(self.time),dbfile,stationID,z=z,conlist=conlist)

        # Update the arrays - note that the values are added to the existing arrays
        self.h += h
        # Add the residual
        for ii in range(self.N3):
            self.h[:,ii] += residual

        if setUV:
            for k in range(self.Nk):
                self.uc[:,k,:] += U
                self.vc[:,k,:] += V

        print 'Finished interpolating OTIS tidal data onto boundary arrays.'

        
    def __getitem__(self,y):
        x = self.__dict__.__getitem__(y)
        return x
        
class InitialCond(Grid):
    """
    SUNTANS initial condition class
    """
    utmzone = 15
    isnorth = True

    # Interpolation options dictionary
    interpdict = dict(
        method='idw', # Interpolation method:  'nn', 'idw', 'kriging', 'griddata'
        NNear=4, 
        p = 1.0, #  power for inverse distance weighting (idw only)
        varmodel = 'spherical', #(kriging only)
        nugget = 0.1,
        sill = 0.8,
        vrange = 10000.0,
    )
    
   
    def __init__(self,suntanspath,timestep,**kwargs):
        
        self.__dict__.update(**kwargs)
        
        self.suntanspath = suntanspath
        
        Grid.__init__(self,suntanspath)
        
        # Get the time timestep
        self.time = datetime.strptime(timestep,'%Y%m%d.%H%M%S')
        
        # Initialise the output array
        self.initArrays()
        
    def initArrays(self):
        """
        Initialise the output arrays
        """

        self.uc = np.zeros((1,self.Nkmax,self.Nc))
        self.vc = np.zeros((1,self.Nkmax,self.Nc))
        #self.wc = np.zeros((self.Nkmax,self.Nc))
        self.T = np.zeros((1,self.Nkmax,self.Nc))
        self.S = np.zeros((1,self.Nkmax,self.Nc))
        self.h = np.zeros((1,self.Nc))
        
        # Age variables
        self.agec = np.zeros((1,self.Nkmax,self.Nc))
        self.agealpha = np.zeros((1,self.Nkmax,self.Nc))

        self.agesource = np.zeros((self.Nkmax,self.Nc))

    def roms2ic(self,romsfile,setUV=False,seth=False,**kwargs):
        """
        Interpolates ROMS data onto the SUNTANS grid
        """
        import romsio
        
        romsi = romsio.roms_interp(romsfile,self.xv.reshape((self.Nc,1)),\
            self.yv.reshape((self.Nc,1)),-self.z_r,[self.time,self.time],**kwargs)

        self.h, self.T, self.S, self.uc, self.vc = romsi.interp()
        
        if not setUV:
            self.uc *= 0 
            self.vc *= 0
        if not seth:
            self.h *= 0

    def suntans2ic(self,hisfile,setUV=False,seth=False):
        """
        Uses data from another suntans file as initial conditions

        Data needs to be on the same grid

        """
        # Load the history file
        sunhis = Spatial(hisfile, tstep=-1, klayer=[-99])

        # Set the time step to grab from the history file
        #...
        tstep = sunhis.getTstep(self.time,self.time)
        sunhis.tstep = [tstep[0]]
        print 'Setting the intial condition with time step: %s\nfrom the file:%s'\
            %(datetime.strftime(sunhis.time[tstep[0]],\
            '%Y-%m-%d %H-%M-%S'),hisfile)

        # Npw grab each variable and save in the IC object
        if seth:
            self.h = sunhis.loadData(variable='eta').reshape((1,self.h.shape))

        if sunhis.hasVar('temp'):
            self.T = sunhis.loadData(variable='temp').reshape((1,)+self.T.shape)
        if sunhis.hasVar('salt'):
            self.S = sunhis.loadData(variable='salt').reshape((1,)+self.S.shape)

        if setUV:
            self.uc = sunhis.loadData(variable='uc').reshape((1,)+self.uc.shape)
            self.vc = sunhis.loadData(variable='vc').reshape((1,)+self.vc.shape)

        # Load the age
        if sunhis.hasVar('agec'):
            self.agec = sunhis.loadData(variable='agec').reshape((1,)+self.agec.shape)       
            self.agealpha = sunhis.loadData(variable='agealpha').reshape((1,)+self.agealpha.shape)       

        print 'Done setting initial condition data from file.'

    def oceanmodel2ic(self,ncfile,convert2utm=True,setUV=False,seth=False,name='HYCOM'):
        """
        Interpolate data from a downloaded netcdf file to the initial condition

        """
        print 'Loading initial condition data from ocean model netcdf file:\n\t%s...'%ncfile
        # Get the temperature data and coordinate data
        temp, nc = get_metocean_local(ncfile,'temp',name=name)

        # Convert to utm
        ll = np.vstack([nc.X.ravel(),nc.Y.ravel()]).T
        if convert2utm:
            xy = ll2utm(ll,self.utmzone,north=self.isnorth)
        else:
            xy = ll

        # Construct a 3D mask
        mask3d = temp.mask
        mask3d = mask3d[0,...]
        mask3d = mask3d.reshape((nc.nz,xy.shape[0]))

        # Construct the 4D interp class
        F4d =\
            Interp4D(xy[:,0],xy[:,1],nc.Z,nc.time,\
                self.xv,self.yv,self.z_r,self.time,mask=mask3d,**self.interpdict)

        tempnew = F4d(temp)
        self.T[:] = tempnew

        salt, nc = get_metocean_local(ncfile,'salt')
        saltnew = F4d(salt)
        self.S[:] = saltnew

        if seth:
            # Construct the 3D interp class for surface height
            ssh, nc = get_metocean_local(ncfile,'ssh')
            mask2d = ssh.mask
            mask2d = mask2d[0,...].ravel()

            F3d = Interp4D(xy[:,0],xy[:,1],None,nc.time,\
                self.xv,self.yv,None,self.time,mask=mask2d,**self.interpdict)
            sshnew = F3d(ssh)
            self.h[:] = sshnew


    def filteric(self,dx):
        """
        Apply a spatial low pass filter to all initial condition fields
        """
        print 'Spatially filtering initial conditions...'

        self.h[0,:]  = self.spatialfilter(self.h[0,:].ravel(),dx)

        for k in range(self.Nkmax):
            print '\t filtering layer %d...'%k
            self.uc[:,k,:] = self.spatialfilter(self.uc[:,k,:].ravel(),dx)
            self.vc[:,k,:] = self.spatialfilter(self.vc[:,k,:].ravel(),dx)
            self.S[:,k,:] = self.spatialfilter(self.S[:,k,:].ravel(),dx)
            self.T[:,k,:] = self.spatialfilter(self.T[:,k,:].ravel(),dx)

    def setAgeSource(self,shpfile):
        """
        Sets the age source term using a polygon shapefile
        """
        # Read the shapefile
        XY,tmp = readShpPoly(shpfile,FIELDNAME=None)
        if len(XY)<1:
            raise Exception, ' could not find any polygons in shapefile: %s'%shpfile

        for xpoly in XY:
            xycells = np.asarray([self.xv,self.yv])
            #ind1 = nxutils.points_inside_poly(xycells.T,xpoly)
            ind1 = inpolygon(xycells.T,xpoly)
            # Sets all vertical layers for now...
            self.agesource[:,ind1] = 1.

     
    
    def writeNC(self,outfile,dv=None):
        """
        Export the results to a netcdf file
        """
        from suntans_ugrid import ugrid
        from netCDF4 import Dataset
        
        # Fill in the depths with zero
        #if not self.__dict__.has_key('dv'):
        if dv==None:
            self.dv = np.zeros((self.Nc,))
        else:
            self.dv = dv
        if not self.__dict__.has_key('Nk'):
            self.Nk = self.Nkmax*np.ones((self.Nc,))
            
        Grid.writeNC(self,outfile)
        
        # write the time variable
        t= othertime.SecondsSince(self.time)
        self.create_nc_var(outfile,'time', ugrid['time']['dimensions'], ugrid['time']['attributes'])        
        
        # Create the other variables
        self.create_nc_var(outfile,'eta',('time','Nc'),{'long_name':'Sea surface elevation','units':'metres','coordinates':'time yv xv'})
        self.create_nc_var(outfile,'uc',('time','Nk','Nc'),{'long_name':'Eastward water velocity component','units':'metre second-1','coordinates':'time z_r yv xv'})
        self.create_nc_var(outfile,'vc',('time','Nk','Nc'),{'long_name':'Northward water velocity component','units':'metre second-1','coordinates':'time z_r yv xv'})
        self.create_nc_var(outfile,'salt',('time','Nk','Nc'),{'long_name':'Salinity','units':'ppt','coordinates':'time z_r yv xv'})
        self.create_nc_var(outfile,'temp',('time','Nk','Nc'),{'long_name':'Water temperature','units':'degrees C','coordinates':'time z_r yv xv'})
        self.create_nc_var(outfile,'agec',('time','Nk','Nc'),{'long_name':'Age concentration','units':''})
        self.create_nc_var(outfile,'agealpha',('time','Nk','Nc'),{'long_name':'Age alpha parameter','units':'seconds','coordinates':'time z_r yv xv'})
        self.create_nc_var(outfile,'agesource',('Nk','Nc'),\
        {'long_name':'Age source grid cell (>0 = source)',\
        'units':'','coordinates':'z_r yv xv'})
        
        # now write the variables...
        nc = Dataset(outfile,'a')
        nc.variables['time'][:]=t
        nc.variables['eta'][:]=self.h
        nc.variables['uc'][:]=self.uc
        nc.variables['vc'][:]=self.vc
        nc.variables['salt'][:]=self.S
        nc.variables['temp'][:]=self.T
        nc.variables['agec'][:]=self.agec
        nc.variables['agealpha'][:]=self.agealpha
        nc.variables['agesource'][:]=self.agesource
        nc.close()
                
        print 'Initial condition file written to: %s'%outfile

        
def modifyBCmarker(suntanspath,bcfile):
    """
    Modifies SUNTANS boundary markers with a shapefile

    The shapefile must contain polygons with the integer-type field "marker"
    """
    
    print '#######################################################'
    print '     Modifying the boundary markers for grid in folder:'
    print '         %s'%suntanspath

    # Load the grid into an object
    grd = sunpy.Grid(suntanspath)
    
    # Find the edge points
    xe = np.mean(grd.xp[grd.edges],axis=1)
    ye = np.mean(grd.yp[grd.edges],axis=1)
    
    # Read the shapefile
    if not bcfile==None:
        XY,newmarker = readShpPoly(bcfile,FIELDNAME='marker')
        if len(XY)<1:
            print 'Error - could not find any polygons with the field name "marker" in shapefile: %s'%bcfile
            return
        
        XY,edge_id = readShpPoly(bcfile,FIELDNAME='edge_id')
        if len(XY)<1:
            print 'Error - could not find any polygons with the field name "edge_id" in shapefile: %s'%bcfile
            return
    else:
        XY=[]
        newmarker=[]
        edge_id=[]
    
    # Plot before updates
    #plt.figure()
    #grd.plotBC()
    #plt.plot(XY[0][:,0],XY[0][:,1],'m',linewidth=2)
    #plt.show()
    
    # Reset all markers to one (closed)
    ind0 = grd.mark>0
    grd.mark[ind0]=1
        
    # Find the points inside each of the polygon and assign new bc
    grd.edge_id = grd.mark*0 # Flag to identify linked edges/segments (marker=4 only)
    for xpoly, bctype,segmentID in zip(XY,newmarker,edge_id):
        ind0 = grd.mark>0
        edges = np.asarray([xe[ind0],ye[ind0]])
        mark = grd.mark[ind0]
        
        #ind1 = nxutils.points_inside_poly(edges.T,xpoly)
        ind1 = inpolygon(edges.T,xpoly)
        if bctype==4:
            eflag = grd.edge_id[ind0]
            eflag[ind1]=segmentID
            grd.edge_id[ind0]=eflag
            bctype=2
        mark[ind1]=bctype
        grd.mark[ind0]=mark
    
    # Save the new markers to edges.dat
    edgefile = suntanspath+'/edges.dat'
    grd.saveEdges(edgefile)
    print 'Updated markers written to: %s'%(edgefile)
    
    # Plot the markers
    plt.figure()
    grd.plotBC()
    if len(XY)>0:
        plt.plot(XY[0][:,0],XY[0][:,1],'m',linewidth=2)
    figfile = suntanspath+'/BoundaryMarkerTypes.pdf'
    plt.savefig(figfile)
    
    print 'Marker plot saved to: %s'%(figfile)
    print 'Done.'
    print '#######################################################'
    

###################
# Testing stuff
