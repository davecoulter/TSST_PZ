import datetime
from django.utils import timezone
from astropy.coordinates import EarthLocation
from astropy.coordinates import get_moon, SkyCoord, FK5
from astroplan import Observer
from astropy.time import Time
import astropy.units as u
from django import template
from ..models import *
from astropy.cosmology import FlatLambdaCDM
cosmo = FlatLambdaCDM(70,0.3)

register = template.Library()

@register.filter(name='tags_list')
def tags_list(tags):
	return tags.all().values_list('name',flat=True)

@register.filter(name='DL')
def DL(redshift):
	return '%.3f'%cosmo.luminosity_distance(redshift).value

@register.filter(name='distmod')
def distmod(redshift):
	return '%.3f'%cosmo.distmod(redshift).value

@register.filter(name='galcoords')
def galcoords(coordstring):

	sc = SkyCoord('%s %s'%(coordstring[0],coordstring[1]),frame="fk5",unit=(u.hourangle,u.deg))
	return '%.7f  %.7f'%(sc.galactic.l.value,sc.galactic.b.value)

@register.filter(name='galcoordsl')
def galcoordsl(coordstring):

	sc = SkyCoord('%s %s'%(coordstring[0],coordstring[1]),frame="fk5",unit=(u.hourangle,u.deg))
	return '%.7f'%sc.galactic.l.value

@register.filter(name='galcoordsb')
def galcoordsb(coordstring):

	sc = SkyCoord('%s %s'%(coordstring[0],coordstring[1]),frame="fk5",unit=(u.hourangle,u.deg))
	return '%.7f'%sc.galactic.b.value


@register.filter(name='replace_space')
def replace_space(object):
	return(object.name.replace(' ','_'))

@register.filter(name='rise_time')
def rise_time(obsnight,coords,tel=None):

	import time
	tstart = time.time()
	
	tme = Time(str(obsnight.obs_date).split()[0])
	sc = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))


	location = EarthLocation.from_geodetic(
		obsnight.resource.telescope.longitude*u.deg,obsnight.resource.telescope.latitude*u.deg,
		obsnight.resource.telescope.elevation*u.m)
	tel = Observer(location=location, timezone="UTC")

	target_rise_time = tel.target_rise_time(tme,sc,horizon=18*u.deg,which="previous")

	if target_rise_time:
		returnstarttime = target_rise_time.isot.split('T')[-1]
	else: returnstarttime = None

	print(time.time()-tstart)
	
	return(returnstarttime)

@register.filter(name='set_time')
def set_time(obsnight,coords):
	
	time = Time(str(obsnight.obs_date).split()[0])
	sc = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))

	location = EarthLocation.from_geodetic(
		obsnight.resource.telescope.longitude*u.deg,obsnight.resource.telescope.latitude*u.deg,
		obsnight.resource.telescope.elevation*u.m)
	tel = Observer(location=location, timezone="UTC")

	target_set_time = tel.target_set_time(time,sc,horizon=18*u.deg,which="previous")

	if target_set_time:
		returnendtime = target_set_time.isot.split('T')[-1]
	else: returnendtime = None

	return(returnendtime)

@register.filter(name='tonight_rise_time')
def tonight_rise_time(obsnight,coords):
	
	time = Time(datetime.datetime.now())
	sc = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))

	location = EarthLocation.from_geodetic(
		obsnight.telescope.longitude*u.deg,obsnight.telescope.latitude*u.deg,
		obsnight.telescope.elevation*u.m)
	tel = Observer(location=location, timezone="UTC")

	target_rise_time = tel.target_rise_time(time,sc,horizon=18*u.deg,which="previous")

	if target_rise_time:
		returnstarttime = target_rise_time.isot.split('T')[-1]
	else: returnstarttime = None

	return(returnstarttime)

@register.filter(name='tonight_set_time')
def tonight_set_time(obsnight,coords):

	time = Time(datetime.datetime.now())
	sc = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))

	location = EarthLocation.from_geodetic(
		obsnight.telescope.longitude*u.deg,obsnight.telescope.latitude*u.deg,
		obsnight.telescope.elevation*u.m)
	tel = Observer(location=location, timezone="UTC")

	target_set_time = tel.target_set_time(time,sc,horizon=18*u.deg,which="previous")

	if target_set_time:
		returnendtime = target_set_time.isot.split('T')[-1]
	else: returnendtime = None

	return(returnendtime)

@register.filter(name='moon_angle')
def moon_angle(obsnight,coords):

	obstime = Time(str(obsnight.obs_date).split()[0],scale='utc')

	mooncoord = get_moon(obstime)
	cs = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))
	return('%.1f'%cs.separation(mooncoord).deg)

@register.filter(name='too_moon_angle')
def too_moon_angle(too_resource,coords):
	obstime = Time(datetime.datetime.now())
	mooncoord = get_moon(obstime)
	cs = SkyCoord('%s %s'%(coords[0],coords[1]),unit=(u.hourangle,u.deg))
	return('%.1f'%cs.separation(mooncoord).deg)
