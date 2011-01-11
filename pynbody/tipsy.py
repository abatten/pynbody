from . import snapshot, array, util
from . import family

import struct
import numpy as np

class TipsySnap(snapshot.SimSnap) :
    def __init__(self, filename, only_header=False) :
	super(TipsySnap,self).__init__()
	
	self._filename = filename
	
	f = util.open_(filename)
	# factoring out gzip logic opens up possibilities for bzip2,
	# or other more advanced filename -> file object mapping later,
	# carrying this across the suite

	t, n, ndim, ng, nd, ns = struct.unpack("diiiii", f.read(28))
        if (ndim > 3 or ndim < 1):
            byteswap=True
            f.seek(0)
            t, n, ndim, ng, nd, ns = struct.unpack(">diiiii", f.read(28))

        # In non-cosmological simulations, what is t? Is it physical
        # time?  In which case, we need some way of telling what we
        # are dealing with and setting properties accordingly.
        self.properties['a'] = t
        self.properties['z'] = 1.0/t - 1.0

	assert ndim==3
	
	self._num_particles = ng+nd+ns
	f.read(4)

	# Store slices corresponding to different particle types
	self._family_slice[family.gas] = slice(0,ng)
	self._family_slice[family.dm] = slice(ng, nd+ng)
	self._family_slice[family.star] = slice(nd+ng, ng+nd+ns)

        
	self._create_arrays(["pos","vel"],3)
	self._create_arrays(["mass","eps","phi"])
	self.gas._create_arrays(["rho","temp","metals"])
	self.star._create_arrays(["metals","tform"])

	self.gas["temp"].units = "K" # we know the temperature is always in K
	# Other units will be set by the decorators later
	

	# Load in the tipsy file in blocks.  This is the most
	# efficient balance I can see for keeping IO contiguuous, not
	# wasting memory, but also not having too much python <-> C
	# interface overheads

	max_block_size = 1024 # particles

	# describe the file structure as list of (num_parts, [list_of_properties]) 
	file_structure = ((ng,family.gas,["mass","x","y","z","vx","vy","vz","rho","temp","eps","metals","phi"]),
			  (nd,family.dm,["mass","x","y","z","vx","vy","vz","eps","phi"]),
			  (ns,family.star,["mass","x","y","z","vx","vy","vz","metals","tform","eps","phi"]))
	

	self._decorate()
	
        if only_header == True :
            return 

	for n_left, type, st in file_structure :
	    n_done = 0
	    self_type = self[type]
	    while n_left>0 :
		n_block = max(n_left,max_block_size)

		# Read in the block
                if(byteswap):
                    g = np.fromstring(f.read(len(st)*n_block*4),'f').byteswap().reshape((n_block,len(st)))
                else:
                    g = np.fromstring(f.read(len(st)*n_block*4),'f').reshape((n_block,len(st)))
                    
		# Copy into the correct arrays
		for i, name in enumerate(st) :
		    self_type[name][n_done:n_done+n_block] = g[:,i]

		# Increment total ptcls read in, decrement ptcls left of this type
		n_left-=n_block
		n_done+=n_block


	

    def loadable_keys(self) :
	"""Produce and return a list of loadable arrays for this TIPSY file."""

	def is_readable_array(x) :
	    try:
		f = util.open_(x)
		return int(f.readline()) == len(self)
	    except (IOError, ValueError) :
		return False
	    
	import glob
	fs = glob.glob(self._filename+".*")
	res =  map(lambda q: q[len(self._filename)+1:], filter(is_readable_array, fs))
	res+=snapshot.SimSnap.loadable_keys(self)
	return res
	
    def _read_array(self, array_name, fam=None) :
	"""Read a TIPSY-ASCII file with the specified name. If fam is not None,
	read only the particles of the specified family."""
	
	# N.B. this code is a bit inefficient for loading
	# family-specific arrays, because it reads in the whole array
	# then slices it.  But of course the memory is only wasted
	# while still inside this routine, so it's only really the
	# wasted time that's a problem.
	
	filename = self._filename+"."+array_name  # could do some cleverer mapping here
	
	f = util.open_(filename)
	try :
	    l = int(f.readline())
	except ValueError :
	    raise IOError, "Incorrect file format"
	if l!=len(self) :
	    raise IOError, "Incorrect file format"
	
	# Inspect the first line to see whether it's float or int
        l = "0\n"
        while l=="0\n" : l = f.readline()
	if "." in l :
	    tp = float
	else :
	    tp = int

	# Restart at head of file
	del f
	f = util.open_(filename)

	f.readline()
	data = np.fromfile(f, dtype=tp, sep="\n")
	ndim = len(data)/len(self)

	if ndim*len(self)!=len(data) :
	    raise IOError, "Incorrect file format"
	
	if ndim>1 :
	    dims = (len(self),ndim)
	else :
	    dims = len(self)

	if fam is None :
	    self._arrays[array_name] = data.reshape(dims).view(array.SimArray)
            self._arrays[array_name].sim = self
	else :
	    self._create_family_array(array_name, fam, ndim, data.dtype)
	    self._get_family_array(array_name, fam)[:] = data[self._get_family_slice(fam)]
            self._get_family_array(array_name, fam).sim = self
            
	
    @staticmethod
    def _can_load(f) :
	# to implement!
	return True


@TipsySnap.decorator
def param2units(sim) :
    import sys, math, os, glob
    x = os.path.abspath(sim._filename)
    done = False
    
    filename=None
    for i in xrange(2) :
        x = os.path.dirname(x)
	l = glob.glob(os.path.join(x,"*.param"))

	for filename in l :
	    # Attempt the loading of information
	    try :
		f = file(filename)
	    except IOError :
		continue
	    munit = dunit = hub = None
            
            for line in f :
		try :
		    s = line.split()
		    if s[0]=="dMsolUnit" :
			munit_st = s[2]+" Msol"
			munit = float(s[2])
		    elif s[0]=="dKpcUnit" :
                        dunit_st = s[2]+" kpc"
                        dunit = float(s[2])
		    elif s[0]=="dHubble0" :
			hub = float(s[2])
                    elif s[0]=="dOmega0" :
			om_m0 = s[2]
                    elif s[0]=="dLambda" :
			om_lam0 = s[2]
                        
		except IndexError, ValueError :
		    pass

	    if munit==None or dunit==None :
		continue

	    print "Loading units from ",filename

	    denunit = munit/dunit**3
            denunit_st = str(denunit)+" Msol kpc^-3"

	    #
	    # the obvious way:
	    #
	    #denunit_cgs = denunit * 6.7696e-32
	    #kpc_in_km = 3.0857e16
	    #secunit = 1./math.sqrt(denunit_cgs*6.67e-8)
	    #velunit = dunit*kpc_in_km/secunit

	    # the sensible way:
	    # avoid numerical accuracy problems by concatinating factors:
	    velunit = 8.0285 * math.sqrt(6.67e-8*denunit) * dunit   
	    velunit_st = ("%.5g"%velunit)+" km s^-1"

            #You have: kpc s / km
            #You want: Gyr
            #* 0.97781311
            timeunit = dunit / velunit * 0.97781311
            timeunit_st = ("%.5g"%timeunit)+" Gyr"

	    enunit_st = "%.5g km^2 s^-2"%(velunit**2)

            if hub!=None:
                hubunit = 10. * velunit / dunit
                hubunit_st = ("%.3f"%(hubunit*hub))

                # append dependence on 'a' for cosmological runs
                dunit_st += " a"
                denunit_st += " a^-3"
                velunit_st += " a"



	    sim["vel"].units = velunit_st
	    sim["phi"].units = sim["vel"].units**2
	    sim["eps"].units = dunit_st
	    sim["pos"].units = dunit_st
	    sim.gas["rho"].units = denunit_st
	    sim["mass"].units = munit_st
            sim.star["tform"].units = timeunit_st

            sim._file_units_system = [sim["vel"].units, sim["mass"].units, sim["pos"].units]

            if hub!=None:
                sim.properties['h'] = hubunit*hub
                sim.properties['omegaM0'] = float(om_m0)
                sim.properties['omegaL0'] = float(om_lam0)
                
	    done = True
	    break
	if done : break
