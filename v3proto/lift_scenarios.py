"""Repeatable lift inputs shared by snapshots and visual checks."""
import math


def lift_scenario(animator, name, duration):
    start = animator.clock
    animator.begin_lift((325.,586.),now=start,cheek=True)
    end = min(duration,1.2)
    cursor = 0.
    steps = max(1,math.ceil(end*60))
    for i in range(steps+1):
        at = end*i/steps
        animator.advance(at-cursor,now=start+at)
        x = 130*math.sin(at*math.tau*2.2) if name=='shake' else 100*min(1.,at/.4)
        y = -180*min(1.,at/.4)
        animator.move_lift((x,y),x*.4,now=start+at)
        animator.advance(0)
        cursor = at
    if name in ('release','shake') and duration >= 1.2:
        animator.release_lift(now=start+1.2)
    return animator.advance(max(0.,duration-cursor),now=start+duration)
