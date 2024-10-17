import pygame
import csv
from Node import Node
from Edge import Edge
from ShortestPath import initializeActiveDataStructures, initializeAdjacencyMatrix, shortestPath

# Define colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREY = (200, 200, 200)
NODE_RADIUS = 5  # Assuming a drawing radius for nodes

# Color mapping for edges
color_mapping = {
    'red': (255, 0, 0),
    'green': (0, 255, 0),
    'blue': (0, 0, 255),
    'yellow': (255, 255, 0),
    # Add more colors as needed
}

# Initialize Pygame
pygame.init()

# Set the width and height of the screen (width, height).
screen_size = (559, 559)
screen = pygame.display.set_mode(screen_size)

# Set the caption of the screen
pygame.display.set_caption("Node and Edge Visualization")

# Global variables
A = None
B = None
numOfNodes = 0
numOfMinutes = 0.0
nodes = []
edges = []
active_nodes = []
active_edges = []
adjacency_matrix_indices = []

# Load data from CSV files
def load_data():
    global adjacency_matrix_indices
    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Ex_1_2_4/locations.csv', mode='r') as locations_file:
        locations_reader = csv.reader(locations_file)
        for index, row in enumerate(locations_reader):
            if row:
                label, x, y = row
                nodes.append(Node(label, int(x), int(y), index))

    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Ex_1_2_4/connections.csv', mode='r') as connections_file:
        connections_reader = csv.reader(connections_file)
        for row in connections_reader:
            if len(row) >= 4:  # Ensure the row has at least 4 values (including color)
                station_a, station_b, minutes, color = row[:4]
                from_node = next((node for node in nodes if node.label == station_a), None)
                to_node = next((node for node in nodes if node.label == station_b), None)
                if from_node and to_node:
                    edges.append(Edge(from_node, to_node, float(minutes), len(edges), color, color_mapping))

    # Initialize adjacency matrix and active data structures
    adjacency_matrix_indices = initializeAdjacencyMatrix(nodes, edges)
    initializeActiveDataStructures(active_nodes, active_edges, len(nodes), len(edges))

load_data()


def is_mouse_over_node(node):
    mouse_x, mouse_y = pygame.mouse.get_pos()
    distance = (mouse_x - node.x)**2 + (mouse_y - node.y)**2
    return distance <= NODE_RADIUS**2

# Main Program Loop
done = False
clock = pygame.time.Clock()

while not done:
    # Main event loop
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            done = True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:  # Right-click
            for node in nodes:
                if is_mouse_over_node(node):
                    if A is None:
                        A = node
                        numOfNodes = 1
                    elif B is None:
                        B = node
                        numOfNodes = 2
                        numOfMinutes, path = shortestPath(A.get_index(), B.get_index(), nodes, active_nodes, active_edges)
                    else:
                        # Reset if another right-click is detected
                        A = None
                        B = None
                        numOfNodes = 0
                        numOfMinutes = 0.0
                        initializeActiveDataStructures(active_nodes, active_edges, len(nodes), len(edges))                

    # Drawing code should go here
    screen.fill(WHITE)


    # Draw nodes
    for node in nodes:
        node.draw(screen, active_nodes[node.get_index()])

    for edge in edges:
        edge.draw(screen, active_edges[edge.get_index()])

    # Draw the shortest path information
    if numOfNodes == 2:
        font = pygame.font.Font(None, 24)
        text_surface = font.render(f"Shortest path from {A.label} to {B.label} takes {numOfMinutes} minutes", True, BLACK)
        screen.blit(text_surface, (10, 10))

    # Update the screen with what we've drawn
    pygame.display.flip()

    # Limit to 60 frames per second
    clock.tick(60)

# Close the window and quit
pygame.quit()
