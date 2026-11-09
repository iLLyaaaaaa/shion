"""Repeatable rubbing, stop and lift transitions through the real gesture filter."""
from .tickle import BellyGesture


def tickle_scenario(animator, name, duration):
    start = animator.clock
    gesture = BellyGesture()
    gesture.press((0.,0.))
    end = min(duration,1.2)
    cursor = 0.
    steps = max(1,round(end*60))
    for i in range(steps+1):
        at = end*i/steps
        animator.advance(max(0.,at-cursor),now=start+at)
        # 16 logical pixels either side, with no vertical / jitter shortcut.
        cycle = (at/.2)%2
        x = -16+32*cycle if cycle <= 1 else 48-32*cycle
        action = gesture.move((x,0.),start+at)
        if action == 'tickle':animator.tickle_belly(now=start+at)
        animator.advance(0)
        cursor = at
    if duration >= 1.2 and name != 'rub':
        animator.release_tickle(now=start+1.2)
        if name == 'lift':
            animator.begin_lift((325.,586.),now=start+1.2,cheek=True)
            move_end = min(duration,1.6)
            animator.advance(move_end-cursor,now=start+move_end)
            animator.move_lift((0.,-150*(move_end-1.2)/.4),0.,now=start+move_end)
            cursor = move_end
            if duration >= 1.6:animator.release_lift(now=start+1.6)
    return animator.advance(max(0.,duration-cursor),now=start+duration)
