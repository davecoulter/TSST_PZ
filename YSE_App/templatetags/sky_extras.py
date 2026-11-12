"""Static sky cutouts (#70): CDS's hips2fits service renders a HiPS survey around a position as a plain
image, so a page that only shows a picture needs no Aladin, no WebGL and no script. The image loads after
the page has rendered; if CDS is slow it stays blank and nothing else waits on it."""
from urllib.parse import urlencode

from django import template

register = template.Library()

HIPS2FITS = 'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'
DSS2_COLOR = 'CDS/P/DSS2/color'


@register.simple_tag
def hips2fits_url(ra, dec, fov=0.017, width=400, height=400, hips=DSS2_COLOR):
    """{% hips2fits_url ra dec fov width height %}: a JPEG of `hips` (DSS2 colour by default) centred on
    ra/dec (degrees, ICRS), `fov` degrees across, `width` x `height` pixels."""
    return HIPS2FITS + '?' + urlencode({
        'hips': hips, 'ra': ra, 'dec': dec, 'fov': fov, 'width': int(float(width)), 'height': int(float(height)),
        'projection': 'TAN', 'coordsys': 'icrs', 'format': 'jpg'})
