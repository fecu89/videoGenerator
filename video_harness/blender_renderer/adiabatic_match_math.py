"""Camera-only approach/reveal schedule; all frame evaluation is stateless."""
import math


def zoom_weight(frame,duration,entry_frames=0,exit_frames=0):
    def ease(p):
        p=min(1,max(0,p));return p*p*(3-2*p)
    entry=1-ease(frame/entry_frames) if entry_frames else 0
    outgoing=ease((frame-(duration-1-exit_frames))/exit_frames) if exit_frames else 0
    return max(entry,outgoing)


def match_distance(radius,lens=85,sensor_width=36,projected_radius=.9):
    if radius<=0:raise ValueError('positive radius required')
    return radius*lens/(sensor_width*projected_radius)
