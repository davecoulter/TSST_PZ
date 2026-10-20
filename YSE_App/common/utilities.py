from astropy.coordinates import SkyCoord
from astropy.coordinates import EarthLocation
import astropy.units as u
import numpy as np
from astroplan import Observer
from astropy.time import Time
import requests

def coordstr_to_decimal(coord):
	if ',' in coord:
		ra,dec = coord.split(',')
	elif ' ' in coord:
		ra,dec = coord.split()
	else:
		raise RuntimeError('RA/Dec format not recognized')

	try:
		ra = float(ra); dec = float(dec)
		return ra,dec
	except:
		if ':' in ra and ':' in dec:
			sc = SkyCoord(ra,dec,unit=(u.hourangle,u.deg))
			return sc.ra.degree,sc.dec.degree
		else:
			sc = SkyCoord(ra,dec)
			return sc.ra.degree,sc.dec.degree

def date_to_mjd(date):
	time = Time(date,scale='utc')
	return time.mjd

def mjd_to_date(mjd):
    time = Time(mjd,format='mjd',scale='utc')
    return time.isot

def getSeparation(ra1_decimal,dec1_decimal,
				  ra2_decimal,dec2_decimal):
		c1 = SkyCoord(ra1_decimal,dec1_decimal,unit=(u.deg, u.deg))
		c2 = SkyCoord(ra2_decimal,dec2_decimal,unit=(u.deg, u.deg))
		return(c1.separation(c2).arcsec)
		
def GetSexigesimalString(ra_decimal, dec_decimal):
	"""(ra, dec) in degrees as ('HH:MM:SS.ss', '+DD:MM:SS.ss').

	Each is rounded once, in whole hundredths of a second, and then split, so 59.996 s carries
	into the minute instead of printing as 60.00, RA wraps at 24 h, and a Dec that rounds to zero
	is '+00:00:00.00' (#61).
	"""
	if not -90.0 <= dec_decimal <= 90.0:
		raise ValueError('Dec must be within [-90, 90] degrees, got %r' % dec_decimal)

	centi = int(round((ra_decimal % 360.0) / 15.0 * 3600 * 100)) % (24 * 3600 * 100)
	hours, rest = divmod(centi, 3600 * 100)
	minutes, centi = divmod(rest, 60 * 100)
	ra_string = '%02d:%02d:%02d.%02d' % (hours, minutes, centi // 100, centi % 100)

	centi = int(round(abs(dec_decimal) * 3600 * 100))
	sign = '-' if dec_decimal < 0 and centi else '+'
	degrees, rest = divmod(centi, 3600 * 100)
	minutes, centi = divmod(rest, 60 * 100)
	dec_string = '%s%02d:%02d:%02d.%02d' % (sign, degrees, minutes, centi // 100, centi % 100)
	return (ra_string, dec_string)

def get_psstamp_url(request, transient_id, Transient):

	ps1url = ("http://ps1images.stsci.edu/cgi-bin/ps1cutouts?pos=%.7f+%.7f&filter=color"%(
		Transient.objects.get(pk=transient_id).ra,Transient.objects.get(pk=transient_id).dec))

	try:
		t = Transient.objects.get(pk=transient_id)
	except t.DoesNotExist:
		raise Http404("Transient id does not exist")
	
	ps1url = ("http://plpsipp1v.stsci.edu/cgi-bin/ps1cutouts?pos=%.7f+%.7f&filter=color" % (t.ra,t.dec))
	try:
		response = requests.get(url=ps1url,timeout=5)
	except: return("")
	response_text = response.content.decode('utf-8')
	if "<td><img src=" in response.content.decode('utf-8'):
		jpegurl = response.content.decode('utf-8').split('<td><img src="')[1].split('" width="240" height="240" /></td>')[0]
		jpegurl = "http:%s"%jpegurl
	else:
		jpegurl=""

	return(jpegurl)

def telescope_can_observe(ra,dec,date,tel):
	time = Time(date)
	sc = SkyCoord(ra,dec,unit=u.deg)
	tel = Observer.at_site(tel)

	night_start = tel.twilight_evening_astronomical(time,which="previous")
	night_end = tel.twilight_morning_astronomical(time,which="previous")
	can_obs = False
	for jd in np.arange(night_start.mjd,night_end.mjd,0.02):
			time = Time(jd,format="mjd")
			target_up = tel.target_is_up(time,sc)
			if target_up:
					can_obs = True
					break

	return(can_obs)

def getRADecBox(ra,dec,size=None):
	RAboxsize = DECboxsize = size

	# get the maximum 1.0/cos(DEC) term: used for RA cut
	minDec = dec-0.5*DECboxsize
	if minDec<=-90.0:minDec=-89.9
	maxDec = dec+0.5*DECboxsize
	if maxDec>=90.0:maxDec=89.9

	invcosdec = max(1.0/np.cos(dec*np.pi/180.0),
					1.0/np.cos(minDec  *np.pi/180.0),
					1.0/np.cos(maxDec  *np.pi/180.0))

	ramin = ra-0.5*RAboxsize*invcosdec
	ramax = ra+0.5*RAboxsize*invcosdec
	decmin = dec-0.5*DECboxsize
	decmax = dec+0.5*DECboxsize

	if ra<0.0: ra+=360.0
	if ra>=360.0: ra-=360.0

	if ramin!=None:
		if (ra-ramin)<-180:
			ramin-=360.0
			ramax-=360.0
		elif (ra-ramin)>180:
			ramin+=360.0
			ramax+=360.0
	return(ramin,ramax,decmin,decmax)

def angular_separation_arcsec(ra1, dec1, ra2, dec2):
	"""Angular separation of two positions (degrees), in arcsec."""
	return SkyCoord(ra1,dec1,unit=u.deg).separation(SkyCoord(ra2,dec2,unit=u.deg)).arcsec

def find_nearest_within(queryset, ra, dec, radius_arcsec):
	"""Return (obj, separation_arcsec) for the object in `queryset` nearest to
	ra/dec (deg) within `radius_arcsec`, or (None, None).

	`queryset` is any model with `ra`/`dec` fields (e.g. Transient), possibly
	pre-filtered by the caller. A box query narrows it first; the true angular
	separation then decides.
	"""
	size = 2*radius_arcsec/3600.
	ramin,ramax,decmin,decmax = getRADecBox(ra,dec,size=size)
	candidates = queryset.filter(ra__gte=ramin,ra__lte=ramax,dec__gte=decmin,dec__lte=decmax)

	target = SkyCoord(ra,dec,unit=u.deg)
	nearest, nearest_sep = None, None
	for obj in candidates:
		sep = target.separation(SkyCoord(obj.ra,obj.dec,unit=u.deg)).arcsec
		if sep <= radius_arcsec and (nearest_sep is None or sep < nearest_sep):
			nearest, nearest_sep = obj, sep
	return(nearest,nearest_sep)
