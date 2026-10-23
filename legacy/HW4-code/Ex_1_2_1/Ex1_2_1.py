import pygame
import random
import sys
import os
from PIL import Image
from reportlab.pdfgen import canvas

# Define the Node class
class Node:
    def __init__(self, label, x, y, index):
        self.label = label
        self.x = x
        self.y = y
        self.index = index

    def draw(self, screen):
        pygame.draw.circle(screen, (0, 0, 0), (int(self.x), int(self.y)), 5)
        font = pygame.font.SysFont("SansSerif", 10)
        text = font.render(self.label, True, (0, 0, 0))
        screen.blit(text, (self.x + 5, self.y + 5))

# Define the Edge class
class Edge:
    def __init__(self, from_node, to_node, minutes):
        self.from_node = from_node
        self.to_node = to_node
        self.minutes = minutes

    def draw(self, screen):
        pygame.draw.line(screen, (0, 0, 0), (self.from_node.x, self.from_node.y), (self.to_node.x, self.to_node.y), 1)

# Function to save the screen to a PDF file
def save_to_pdf(screen, filename):
    pygame.image.save(screen, "temp.png")
    image = Image.open("temp.png")
    pdf = canvas.Canvas(filename)
    pdf.setPageSize((image.width, image.height))
    pdf.drawInlineImage("temp.png", 0, 0)
    pdf.save()
    os.remove("temp.png")

# Initialize Pygame
pygame.init()

# Set up the display
screen = pygame.display.set_mode((559, 559))
pygame.display.set_caption("Graph Visualization")
clock = pygame.time.Clock()

# Initialize variables
node_count = 0
nodes = []
node_table = {}
selection = None
edge_count = 0
edges = []

# Function to add an edge
def add_edge(from_label, to_label, minutes):
    from_node = find_node(from_label)
    to_node = find_node(to_label)
    for edge in edges:
        if edge.from_node == from_node and edge.to_node == to_node:
            return
    edge = Edge(from_node, to_node, minutes)
    edges.append(edge)

# Function to find a node, or add it if it doesn't exist
def find_node(label):
    if label in node_table:
        return node_table[label]
    else:
        return add_node(label)

# Function to add a new node
def add_node(label):
    global node_count
    x = random.randint(50, 509)
    y = random.randint(50, 509)
    node = Node(label, x, y, node_count)
    node_table[label] = node
    nodes.append(node)
    node_count += 1
    return node

# Load data
def load_data():
    add_edge("A", "B", 7.0)
    add_edge("B", "C", 7.0)
    add_edge("C", "D", 3.5)
    add_edge("D", "E", 3.0)
    add_edge("C", "F", 2.5)
    add_edge("F", "G", 1.2)
    add_edge("G", "H", 0.1)

# Main loop
running = True
load_data()
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                closest = 5
                for node in nodes:
                    d = ((event.pos[0] - node.x) ** 2 + (event.pos[1] - node.y) ** 2) ** 0.5
                    if d < closest:
                        selection = node
                        closest = d
        elif event.type == pygame.MOUSEBUTTONUP:
            selection = None
        elif event.type == pygame.MOUSEMOTION:
            if selection is not None:
                selection.x, selection.y = event.pos
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
            save_to_pdf(screen, "output.pdf")

    # Draw everything
    screen.fill((255, 255, 255))
    for edge in edges:
        edge.draw(screen)
    for node in nodes:
        node.draw(screen)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
