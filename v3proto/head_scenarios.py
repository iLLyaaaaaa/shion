"""Deterministic inputs shared by head-interaction screenshots and checks."""


def head_scenario(animator, name, duration):
    start = animator.clock
    if name in ('knock', 'combo'):
        events = [(t, 'knock') for t in ((0., .25, .5) if name == 'combo' else (0.,))]
    else:
        events = [(i/40, 'stroke') for i in range(49)] + [(1.2, 'release')]
    cursor = 0.
    for at, action in events:
        if at > duration:
            break
        animator.advance(at-cursor, now=start+at)
        cursor = at
        if action == 'knock':animator.knock_head(now=start+at)
        elif action == 'stroke':animator.stroke_head(-1 if name == 'pat-left' else 1, now=start+at)
        else:animator.release_head(now=start+at)
    return animator.advance(duration-cursor, now=start+duration)
