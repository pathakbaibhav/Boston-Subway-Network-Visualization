import pygame

class Node:
    def __init__(self, label, x, y, index):
        self.label = label
        self.x = x
        self.y = y
        self.index = index

    def get_index(self):
        return self.index

    def draw(self, screen, active):
        color = (0, 0, 0) if active else (200, 200, 200)  # Active nodes are black, inactive are grey
        pygame.draw.circle(screen, color, (self.x, self.y), 5)
