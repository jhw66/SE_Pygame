import pygame

pygame.init()

WINDOW_WIDTH=960
WINDOW_HEIGHT=640

screen=pygame.display.set_mode(
    (WINDOW_WIDTH,WINDOW_HEIGHT)
)

pygame.display.set_caption("test")

BACKGROUND_COLOR=(30,35,45)

clock=pygame.time.Clock()

running=True

while running:
    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            running=False
    screen.fill(BACKGROUND_COLOR)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()