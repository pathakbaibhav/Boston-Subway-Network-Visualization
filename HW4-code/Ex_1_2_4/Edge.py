import pygame

class Edge:
    def __init__(self, from_node, to_node, minutes, index, color, color_mapping):
        self.from_node = from_node
        self.to_node = to_node
        self.minutes = minutes
        self.index = index
        self.color = color
        self.color_mapping = color_mapping  # Store the color mapping dictionary

    def get_from_node(self):
        return self.from_node

    def get_to_node(self):
        return self.to_node

    def get_minutes(self):
        return self.minutes

    def get_index(self):
        return self.index

    def draw(self, screen, active):
        color_rgb = self.color_mapping.get(self.color, (200, 200, 200)) if active else (200, 200, 200)
        pygame.draw.line(screen, color_rgb, (self.from_node.x, self.from_node.y), (self.to_node.x, self.to_node.y), 2)