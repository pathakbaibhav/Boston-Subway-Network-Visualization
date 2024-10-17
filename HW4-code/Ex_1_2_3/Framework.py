import pygame
import csv
from ShortestPath import Node, Edge, shortest_path, initialize_active_data_structures, initialize_adjacency_matrix, active_nodes, active_edges

# Define colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)

# Initialize Pygame
pygame.init()

# Set the width and height of the screen (width, height).
screen_size = (559, 559)
screen = pygame.display.set_mode(screen_size)

# Set the caption of the screen
pygame.display.set_caption("Node and Edge Visualization")

# Loop until the user clicks the close button.
done = False

# Used to manage how fast the screen updates
clock = pygame.time.Clock()

# Global variables
A = None
B = None
numOfNodes = 0
numOfMinutes = 0

# Nodes and Edges
nodes = []
edges = []

# Load data from CSV files
def load_data():
    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Framework/locations.csv', mode='r') as locations_file:
        locations_reader = csv.reader(locations_file)
        index = 0
        for row in locations_reader:
            try:
                station_name, x, y = row
                node = Node(station_name, int(x), int(y), index)
                nodes.append(node)
                index += 1
            except ValueError:
                # Skip rows with non-numeric data
                continue

    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Framework/connections.csv', mode='r') as connections_file:
        connections_reader = csv.reader(connections_file)
        for row in connections_reader:
            try:
                station_a, station_b, col, minutes = row
                from_node = next((n for n in nodes if n.label == station_a), None)
                to_node = next((n for n in nodes if n.label == station_b), None)
                if from_node and to_node:
                    edge = Edge(from_node, to_node, float(minutes))
                    edges.append(edge)
            except ValueError:
                # Skip rows with non-numeric data
                continue

def is_mouse_over_node(node):
    mouse_x, mouse_y = pygame.mouse.get_pos()
    over_node = (mouse_x - node.x) ** 2 + (mouse_y - node.y) ** 2 <= 5 ** 2
    if over_node:
        print(f"Mouse over node: {node.label}")
    return over_node

def handle_right_click():
    for node in nodes:
        if is_mouse_over_node(node):
            print(f"Right-clicked on node: {node.label}")
            break


load_data()
initialize_active_data_structures()
initialize_adjacency_matrix()

# Main Program Loop
while not done:
    # --- Main event loop
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            done = True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:  # Right click
            handle_right_click()

    # --- Drawing code should go here

    # First, clear the screen to white.
    screen.fill(WHITE)

    # Draw edges
    for i, edge in enumerate(edges):
        if i < len(active_edges) and active_edges[i]:
            pygame.draw.line(screen, BLACK, (edge.from_node.x, edge.from_node.y), (edge.to_node.x, edge.to_node.y), 1)

    # Draw nodes
    for i, node in enumerate(nodes):
        if i < len(active_nodes) and active_nodes[i]:
            color = RED
        else:
            color = BLACK
        pygame.draw.circle(screen, color, (node.x, node.y), 5)

    # Display shortest path information
    if A and B:
        font = pygame.font.Font(None, 24)
        text_surface = font.render(f"Shortest path: {A.label} -> {B.label}, Minutes: {numOfMinutes}", True, BLACK)
        screen.blit(text_surface, (10, 10))

    # --- Update the screen with what we've drawn.
    pygame.display.flip()

    # --- Limit to 60 frames per second
    clock.tick(60)

# Close the window and quit
pygame.quit()
