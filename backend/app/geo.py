"""坐标系转换；高德提供 GCJ-02，Open-Meteo 需要 WGS84。"""
import math


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    x, y = lon - 105.0, lat - 35.0
    dlat = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*math.sqrt(abs(x))
    dlat += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    dlat += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi))*2/3
    dlat += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30))*2/3
    dlon = 300 + x + 2*y + .1*x*x + .1*x*y + .1*math.sqrt(abs(x))
    dlon += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    dlon += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi))*2/3
    dlon += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi))*2/3
    earth, ee = 6378245.0, .006693421622965943
    rad = lat / 180 * math.pi
    magic = 1 - ee * math.sin(rad)**2
    dlat = dlat * 180 / ((earth * (1-ee)) / (magic * math.sqrt(magic)) * math.pi)
    dlon = dlon * 180 / (earth / math.sqrt(magic) * math.cos(rad) * math.pi)
    return lon - dlon, lat - dlat
