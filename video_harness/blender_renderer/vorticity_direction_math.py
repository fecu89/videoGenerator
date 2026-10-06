"""Framing for the vorticity explanation; all timings are scene-relative."""
import math


def smooth(value):
    value=max(0.,min(1.,value))
    return value*value*(3-2*value)


def window(progress,start,end=1.):
    return smooth((progress-start)/(end-start))


def framing(scene,progress):
    q=smooth(progress)
    zoom=1.;focus=(-4.,0.);yaw=0.;bridge=0.
    if scene==1:zoom=1-.04*q
    elif scene==2:zoom=.96+.04*q
    elif scene==3:zoom=1-.08*q
    elif scene==4:
        bridge=window(progress,.72)
        zoom=.92+(.85/3.3-.92)*bridge
        focus=(-4-2*bridge,1.5*bridge)
    elif scene==5:
        zoom=1-.12*q;focus=(-4.,.111)
        yaw=.12*math.sin(math.pi*progress)
    elif scene==6:
        zoom=.88+.12*q;bridge=window(progress,.80)
        focus=(-4.,.111*(1-bridge))
        yaw=-.12*math.sin(math.pi*progress)*(1-bridge)
    elif scene==7:zoom=1-.06*q
    elif scene==8:zoom=.94
    elif scene==9:zoom=.94+.06*q
    elif scene==12:
        bridge=window(progress,.73)
        zoom=1-.45*bridge
    elif scene==13:zoom=1-.06*q
    elif scene==14:zoom=.94+.06*q
    elif scene==15:bridge=window(progress,.78)
    elif scene==16:zoom=1-.06*q
    elif scene==17:zoom=.94-.04*q
    elif scene==18:zoom=.90
    elif scene==19:zoom=.90+.10*q
    return dict(zoom=zoom,focus=focus,yaw=yaw,bridge=bridge)
