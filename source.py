import time

def goRobot(r):
    while True:
        if r.x > 50:
            r.x=-50
        if r.y > 50:
            r.y=-50
        
        r.pose = r.x+1, r.y+2, r.heading+3
        time.sleep(1/30.0)
